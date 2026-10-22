"""Lanzar clientes gráficos desde airpodsd: popup de Noctalia y notificaciones.

airpodsd es un servicio systemd de usuario que puede arrancar antes que la sesión
gráfica; aquí se completa el entorno en el momento de lanzar cada proceso.
"""
import json
import logging
import os
import shutil
from pathlib import Path

import dbus
from gi.repository import Gio, GLib

log = logging.getLogger("airpodsd")

NOCTALIA_PLUGIN = "canoojson/airpods"
POPUP_PANEL = NOCTALIA_PLUGIN + ":popup"


def noctalia_running() -> bool:
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as fh:
                    if fh.read().strip() == "noctalia":
                        return True
            except OSError:
                pass
    return False


GRAPHICAL_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP",
                  "DBUS_SESSION_BUS_ADDRESS")


def systemd_user_environment() -> dict[str, str]:
    """Entorno actual del gestor systemd de usuario (la sesión gráfica lo rellena al arrancar)."""
    try:
        mgr = dbus.SessionBus().get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
        env = mgr.Get("org.freedesktop.systemd1.Manager", "Environment",
                      dbus_interface="org.freedesktop.DBus.Properties")
        return dict(str(e).split("=", 1) for e in env if "=" in str(e))
    except dbus.DBusException:
        return {}


def graphical_env(base: dict[str, str] | None = None, manager_env: dict[str, str] | None = None,
                  runtime_dir: str | None = None) -> dict[str, str]:
    """Entorno para lanzar clientes gráficos (noctalia msg, notify-send).

    airpodsd puede arrancar antes que la sesión gráfica (default.target), así que su
    propio entorno no tiene WAYLAND_DISPLAY. Se completa en el momento de lanzar:
    primero con el entorno de systemd, y si no, con el socket de Wayland del runtime dir.
    """
    env = dict(os.environ if base is None else base)
    if not env.get("WAYLAND_DISPLAY"):
        mgr = systemd_user_environment() if manager_env is None else manager_env
        for k in GRAPHICAL_VARS:
            if mgr.get(k) and not env.get(k):
                env[k] = mgr[k]
    if not env.get("WAYLAND_DISPLAY"):
        rt = Path(runtime_dir or env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        sockets = sorted(p.name for p in rt.glob("wayland-*") if not p.name.endswith(".lock") and p.is_socket())
        if sockets:
            env["WAYLAND_DISPLAY"] = sockets[0]
    return env


def spawn(argv: list[str]) -> None:
    env = graphical_env()
    if not env.get("WAYLAND_DISPLAY"):
        log.warning("sin sesión Wayland: no se puede mostrar el popup")
    # GLib.spawn_async con STDOUT_TO_DEV_NULL lanza AssertionError desde GLib 2.90 + PyGObject 3.58.
    # Gio.SubprocessLauncher hace lo mismo y además recoge el proceso hijo al terminar.
    launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    launcher.set_environ([f"{k}={v}" for k, v in env.items()])
    try:
        launcher.spawnv(argv)
    except GLib.Error as e:
        log.warning("no se pudo lanzar %s: %s", argv[0], e.message)


class Popup:
    """Muestra el popup en Noctalia; sin Noctalia, una notificación de escritorio."""

    def __init__(self, mode: str, panel_id: str = POPUP_PANEL):
        self.mode = mode
        self.panel_id = panel_id
        self.open = False
        self._last = None

    def show(self, payload: dict) -> None:
        if self.mode == "none":
            return
        if self.mode in ("auto", "noctalia") and shutil.which("noctalia") and noctalia_running():
            spawn(["noctalia", "msg", "panel-open", self.panel_id, json.dumps(payload)])
            self.open = True
            self._last = self._key(payload)
        elif self.mode in ("auto", "notify") and shutil.which("notify-send"):
            spawn(["notify-send", "-a", "AirPods", "-i", "audio-headphones", "-t", "8000",
                   payload["title"], payload["summary"]])

    @staticmethod
    def _key(payload: dict) -> str:
        # Lo que se ve en el popup, sin timestamps: solo se reenvía si cambia.
        return json.dumps([payload.get("connected"),
                           {k: v["value"] for k, v in payload.get("fields", {}).items() if k != "rssi"}],
                          sort_keys=True)

    def update(self, payload: dict) -> None:
        if self.open and (key := self._key(payload)) != self._last:
            self._last = key
            spawn(["noctalia", "msg", "plugin", self.panel_id, "all", "state", json.dumps(payload)])

    def close(self) -> None:
        if self.open:
            spawn(["noctalia", "msg", "panel-close", self.panel_id])
            self.open = False


def notify(title: str, body: str, icon: str = "audio-headphones", urgency: str | None = None,
           timeout_ms: int | None = None) -> None:
    """Notificación de escritorio con notify-send, si está instalado."""
    if not shutil.which("notify-send"):
        return
    argv = ["notify-send", "-a", "AirPods", "-i", icon]
    if urgency:
        argv += ["-u", urgency]
    if timeout_ms is not None:
        argv += ["-t", str(timeout_ms)]
    spawn(argv + [title, body])
