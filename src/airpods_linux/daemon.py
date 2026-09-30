"""airpodsd: daemon de usuario. Vigila los anuncios, guarda el estado, lo expone
por D-Bus (bus de sesión) y muestra un popup al abrir la caja con los auriculares dentro.

D-Bus: io.github.AirpodsLinux  /io/github/AirpodsLinux  io.github.AirpodsLinux1
  GetState() -> s (JSON)      StateChanged(s)   CaseOpened(s)   CaseClosed()
"""
import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

from . import keys as keys_mod
from . import config as config_mod
from . import update as update_mod
from .bluez import get_alias, paired_devices, select_airpods
from .ear import PAUSE, RESUME, EarPauseLogic
from .media import MediaController
from .events import CLOSED, OPENED, CaseEventDetector
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore

log = logging.getLogger("airpodsd")

BUS_NAME = "io.github.AirpodsLinux"
OBJ_PATH = "/io/github/AirpodsLinux"
IFACE = "io.github.AirpodsLinux1"
NOCTALIA_PLUGIN = "canoojson/airpods"
POPUP_PANEL = NOCTALIA_PLUGIN + ":popup"
UPDATE_INTERVAL_S = 24 * 3600
HELPER_BUS = "org.costa.AirPods"   # airpods-helper: detección en oreja al instante (AAP)
HELPER_PATH = "/org/costa/AirPods"


def runtime_status_path() -> Path:
    """Estado en vivo para widgets que no hablan D-Bus (Noctalia lo lee con readFileAsync)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "airpods-linux" / "status.json"


class Service(dbus.service.Object):
    def __init__(self, bus, daemon):
        super().__init__(dbus.service.BusName(BUS_NAME, bus), OBJ_PATH)
        self._daemon = daemon

    @dbus.service.method(IFACE, out_signature="s")
    def GetState(self):
        return json.dumps(self._daemon.state())

    @dbus.service.method(IFACE)
    def Reload(self):
        """Relee config.json y el nombre del dispositivo (lo llama airpodsctl config/rename)."""
        self._daemon.reload()

    @dbus.service.method(IFACE)
    def CheckUpdates(self):
        """Busca una versión nueva ya; el resultado aparece en el estado ('update')."""
        self._daemon.check_updates(manual=True)

    @dbus.service.signal(IFACE, signature="s")
    def StateChanged(self, state_json):
        pass

    @dbus.service.signal(IFACE, signature="s")
    def CaseOpened(self, state_json):
        pass

    @dbus.service.signal(IFACE)
    def CaseClosed(self):
        pass


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
    try:
        GLib.spawn_async(argv, envp=[f"{k}={v}" for k, v in env.items()],
                         flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
                         | GLib.SpawnFlags.STDERR_TO_DEV_NULL)
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


def pct(field: dict | None) -> str:
    return f"{field['value']['level']} %" if field else "--"


class Daemon:
    def __init__(self, args):
        self.args = args
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.store = StateStore(STATE_PATH).load()
        self.keys = keys_mod.load()
        if not self.keys:
            log.warning("sin claves de proximidad: batería al 10 %% y sin datos con la caja cerrada "
                        "(airpodsctl keys fetch)")
        self.detector = CaseEventDetector()
        self.popup = Popup(args.popup, args.popup_panel)
        self.popup_timeout = args.popup_timeout
        self._popup_timer = None
        self._refresh_timer = None
        self._last_connected = None
        self.config = config_mod.load()
        self.update_info = {"checked": None, "latest": None, "available": False, "error": None}
        self._checking = False
        self._alias = None
        self.service = Service(dbus.SessionBus(), self)
        self.session_bus = dbus.SessionBus()
        self.ear = EarPauseLogic()
        self.media = MediaController(self.session_bus)
        self._helper_ear = {"left": None, "right": None}
        self.system_bus = dbus.SystemBus()

        from .scanner import BleScanner, Tracker
        self.tracker = Tracker(self.store, self.keys, on_change=self._on_change, on_own=self._on_own)
        self.scanner = BleScanner(self.tracker.handle, window=(args.on, args.off), passive=not args.no_passive)
        log.info("modo de escaneo: %s", "pasivo (AdvertisementMonitor)" if self.scanner.passive
                 else f"ventanas {args.on}/{args.off} s")
        self._watch_helper()

    def airpods_address(self) -> str | None:
        """MAC de los AirPods emparejados: la de las claves o, sin claves, la que encuentre BlueZ."""
        if self.keys:
            return self.keys.address
        try:
            chosen, _ = select_airpods(paired_devices())
        except dbus.DBusException:
            return None
        return chosen["address"] if chosen else None

    def connected(self, address: str | None = None) -> bool | None:
        """True/False si los AirPods están emparejados con este equipo; None si no lo están."""
        address = address or self.airpods_address()
        if not address:
            return None
        path = f"{self.scanner.adapter_path}/dev_{address.replace(':', '_')}"
        try:
            return bool(self.system_bus.get_object("org.bluez", path).Get(
                "org.bluez.Device1", "Connected", dbus_interface="org.freedesktop.DBus.Properties"))
        except dbus.DBusException:
            return None

    def state(self) -> dict:
        v = self.store.value
        address = self.airpods_address()
        return {
            "now": time.time(),
            "keys": self.keys is not None,
            "model_name": MODEL_NAMES.get(v("model"), "AirPods"),
            "address": address,
            # None = los AirPods no están emparejados con este equipo (no se pueden conectar)
            "connected": self.connected(address),
            "name": self._device_name(address),
            "version": update_mod.current_version(),
            # Ruta absoluta para que los widgets puedan llamar a airpodsctl sin depender del PATH.
            "ctl": str(Path(sys.argv[0]).resolve().with_name("airpodsctl")),
            "ear": {"pause": bool(self.config.get("ear_pause", True)),
                    "resume": bool(self.config.get("ear_resume", True)),
                    "source": "airpods-helper" if self._helper_active() else "ble"},
            "update": {**self.update_info, "enabled": bool(self.config.get("update_check")),
                       "managed": update_mod.managed_install()},
            **self.store.to_dict(),
        }

    def popup_payload(self) -> dict:
        st = self.state()
        g = self.store.get
        st["title"] = st["name"] or st["model_name"]
        st["summary"] = f"Izquierdo {pct(g('left'))} · Derecho {pct(g('right'))} · Caja {pct(g('case'))}"
        return st

    def write_status(self) -> str:
        data = json.dumps(self.state())
        path = runtime_status_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(data)
            os.replace(tmp, path)
        except OSError as e:
            log.warning("no se pudo escribir %s: %s", path, e)
        return data

    # --- pausa automática al quitarse un auricular -----------------------------

    def _helper_active(self) -> bool:
        try:
            return bool(self.session_bus.name_has_owner(HELPER_BUS))
        except dbus.DBusException:
            return False

    def _watch_helper(self) -> None:
        def changed(iface, props, _inv):
            if iface != HELPER_BUS:
                return
            if "EarLeft" in props:
                self._helper_ear["left"] = bool(props["EarLeft"])
            if "EarRight" in props:
                self._helper_ear["right"] = bool(props["EarRight"])
            if "EarLeft" in props or "EarRight" in props:
                self._ear_changed(self._helper_ear["left"], self._helper_ear["right"], "airpods-helper")
        self.session_bus.add_signal_receiver(changed, "PropertiesChanged", "org.freedesktop.DBus.Properties",
                                             HELPER_BUS, HELPER_PATH)
        try:
            obj = self.session_bus.get_object(HELPER_BUS, HELPER_PATH, introspect=False)
            props = obj.GetAll(HELPER_BUS, dbus_interface="org.freedesktop.DBus.Properties")
            self._helper_ear = {"left": bool(props.get("EarLeft")), "right": bool(props.get("EarRight"))}
            self.ear.update("airpods-helper", self._helper_ear["left"], self._helper_ear["right"],
                            self.connected(), time.time())
            log.info("detección en oreja: airpods-helper (instantánea) + anuncios BLE")
        except dbus.DBusException:
            log.info("detección en oreja: anuncios BLE (airpods-helper no está en marcha)")

    def _ear_changed(self, left, right, source: str, left_case=None, right_case=None) -> None:
        action = self.ear.update(source, left, right, self.connected(), time.time(), left_case, right_case)
        if action == PAUSE and self.config.get("ear_pause", True):
            paused = self.media.pause_playing()
            log.info("auricular fuera de la oreja (%s): %s", source,
                     f"pausado {', '.join(p.rsplit('.', 1)[-1] for p in paused)}" if paused else "nada sonando")
            if not self.config.get("ear_resume", True):
                self.media.forget()
        elif action == RESUME and self.config.get("ear_resume", True) and self.media.paused_by_us:
            resumed = self.media.resume()
            log.info("auricular de vuelta en la oreja o guardado en la caja (%s): reanudado %s", source,
                     ", ".join(p.rsplit('.', 1)[-1] for p in resumed) or "nada")
        elif action == RESUME:
            self.media.forget()

    def _on_change(self, _store) -> None:
        # Los anuncios BLE siempre cuentan: con un auricular en la caja airpods-helper deja
        # de informar de la oreja, y sin airpods-helper son la única fuente.
        self._ear_changed(self.store.value("left_in_ear"), self.store.value("right_in_ear"), "BLE",
                          self.store.value("left_in_case"), self.store.value("right_in_case"))
        self.service.StateChanged(self.write_status())
        self.popup.update(self.popup_payload())

    def _poll_connection(self) -> bool:
        # "Conectado a este equipo" no llega por BLE: se consulta a BlueZ periódicamente.
        connected = self.connected()
        if connected != self._last_connected:
            self._last_connected = connected
            self._on_change(self.store)
        return True

    def _on_own(self, _kind: str, ts: float) -> None:
        event = self.detector.observe(self.store, ts)
        if event == OPENED:
            log.info("caja abierta con auriculares dentro")
            payload = self.popup_payload()
            log.info("popup: %s", "noctalia" if self.popup.mode != "none" else "desactivado")
            self.service.CaseOpened(json.dumps(payload))
            self.popup.show(payload)
            self._arm_popup_timeout()
        elif event == CLOSED:
            log.info("caja cerrada")
            self.service.CaseClosed()
            self.popup.close()

    def _arm_popup_timeout(self) -> None:
        if self._popup_timer:
            GLib.source_remove(self._popup_timer)
        # Red de seguridad: el panel se cierra solo, pero por si se queda abierto.
        self._popup_timer = GLib.timeout_add_seconds(self.popup_timeout + 2, self._popup_expired)
        if not self._refresh_timer:
            self._refresh_timer = GLib.timeout_add_seconds(1, self._refresh_popup)

    def _refresh_popup(self) -> bool:
        # Refresca también lo que no llega por BLE (p. ej. conectado a este equipo).
        if not self.popup.open:
            self._refresh_timer = None
            return False
        self.popup.update(self.popup_payload())
        return True

    def _popup_expired(self) -> bool:
        self._popup_timer = None
        self.popup.close()
        return False

    def _device_name(self, address: str | None) -> str | None:
        if address and self._alias is None:
            self._alias = get_alias(address) or ""
        return self._alias or None

    def reload(self) -> None:
        was_enabled = self.config.get("update_check")
        self.config = config_mod.load()
        self._alias = None
        log.info("configuración recargada (comprobar actualizaciones: %s)",
                 "sí" if self.config.get("update_check") else "no")
        if self.config.get("update_check") and not was_enabled:
            self.check_updates()
        self._on_change(self.store)

    # --- actualizaciones -------------------------------------------------------

    def _periodic_update_check(self) -> bool:
        if self.config.get("update_check"):
            self.check_updates()
        return True

    def check_updates(self, manual: bool = False) -> None:
        """Consulta GitHub en un hilo (no bloquea el bucle BLE) y avisa una vez por versión."""
        if self._checking:
            return
        self._checking = True

        def worker():
            info = update_mod.check()
            GLib.idle_add(self._update_checked, info, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _update_checked(self, info: dict, manual: bool) -> bool:
        self._checking = False
        self.update_info = {"checked": time.time(), "latest": info["latest"],
                            "available": info["available"], "error": info["error"]}
        if info["error"]:
            log.warning("no se pudo comprobar si hay actualizaciones: %s", info["error"])
        elif info["available"]:
            log.info("versión nueva disponible: %s (instalada %s)", info["latest"], info["current"])
            if not manual and self.config.get("notified_version") != info["latest"]:
                self.config["notified_version"] = info["latest"]
                config_mod.save(self.config)
                if shutil.which("notify-send"):
                    spawn(["notify-send", "-a", "AirPods", "-i", "software-update-available",
                           f"AirPods Linux {info['latest']} disponible",
                           "Actualiza con: airpodsctl update (o desde el ⚙ del panel)"])
        self._on_change(self.store)
        return False

    def run(self) -> None:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.scanner.quit)
        self.write_status()
        GLib.timeout_add_seconds(5, self._poll_connection)
        # Primera comprobación al minuto de arrancar (con la red ya lista) y luego cada día.
        GLib.timeout_add_seconds(60, lambda: (self._periodic_update_check(), False)[1])
        GLib.timeout_add_seconds(UPDATE_INTERVAL_S, self._periodic_update_check)
        self.scanner.run(scan=not self.args.no_ble)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsd")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--popup", choices=["auto", "noctalia", "notify", "none"], default="auto")
    ap.add_argument("--popup-timeout", type=int, default=10)
    ap.add_argument("--popup-panel", default=POPUP_PANEL, help="id del panel de Noctalia para el popup")
    ap.add_argument("--no-passive", action="store_true", help="no usar AdvertisementMonitor")
    ap.add_argument("--no-ble", action="store_true", help="no escanear anuncios BLE (diagnóstico)")
    ap.add_argument("--on", type=float, default=4, help="ventana de escaneo activa (s), sin modo pasivo")
    ap.add_argument("--off", type=float, default=8, help="pausa entre ventanas (s), sin modo pasivo")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        Daemon(args).run()
    except dbus.exceptions.NameExistsException:
        log.error("ya hay otro airpodsd en ejecución")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
