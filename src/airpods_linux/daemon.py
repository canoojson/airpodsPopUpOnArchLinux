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
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

from . import keys as keys_mod
from .events import CLOSED, OPENED, CaseEventDetector
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore

log = logging.getLogger("airpodsd")

BUS_NAME = "io.github.AirpodsLinux"
OBJ_PATH = "/io/github/AirpodsLinux"
IFACE = "io.github.AirpodsLinux1"
NOCTALIA_PLUGIN = "canoojson/airpods"
POPUP_PANEL = NOCTALIA_PLUGIN + ":popup"


def runtime_status_path() -> Path:
    """Estado en vivo para widgets que no hablan D-Bus (Noctalia lo lee con readFileAsync)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "airpods-linux" / "status.json"


class Service(dbus.service.Object):
    def __init__(self, bus, get_state):
        super().__init__(dbus.service.BusName(BUS_NAME, bus), OBJ_PATH)
        self._get_state = get_state

    @dbus.service.method(IFACE, out_signature="s")
    def GetState(self):
        return json.dumps(self._get_state())

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


def spawn(argv: list[str]) -> None:
    try:
        GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
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
        self.service = Service(dbus.SessionBus(), self.state)
        self.system_bus = dbus.SystemBus()

        from .scanner import BleScanner, Tracker
        self.tracker = Tracker(self.store, self.keys, on_change=self._on_change, on_own=self._on_own)
        self.scanner = BleScanner(self.tracker.handle, window=(args.on, args.off), passive=not args.no_passive)
        log.info("modo de escaneo: %s", "pasivo (AdvertisementMonitor)" if self.scanner.passive
                 else f"ventanas {args.on}/{args.off} s")

    def connected(self) -> bool | None:
        if not self.keys:
            return None
        path = f"{self.scanner.adapter_path}/dev_{self.keys.address.replace(':', '_')}"
        try:
            return bool(self.system_bus.get_object("org.bluez", path).Get(
                "org.bluez.Device1", "Connected", dbus_interface="org.freedesktop.DBus.Properties"))
        except dbus.DBusException:
            return None

    def state(self) -> dict:
        v = self.store.value
        return {
            "now": time.time(),
            "keys": self.keys is not None,
            "model_name": MODEL_NAMES.get(v("model"), "AirPods"),
            "address": self.keys.address if self.keys else None,
            "connected": self.connected(),
            **self.store.to_dict(),
        }

    def popup_payload(self) -> dict:
        st = self.state()
        g = self.store.get
        st["title"] = st["model_name"]
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

    def _on_change(self, _store) -> None:
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
            self.scanner.burst(self.popup_timeout)
            self._arm_popup_timeout()
        elif event == CLOSED:
            log.info("caja cerrada")
            self.service.CaseClosed()
            self.popup.close()
            self.scanner.end_burst()

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

    def run(self) -> None:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.scanner.quit)
        self.write_status()
        GLib.timeout_add_seconds(5, self._poll_connection)
        self.scanner.run()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsd")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--popup", choices=["auto", "noctalia", "notify", "none"], default="auto")
    ap.add_argument("--popup-timeout", type=int, default=10)
    ap.add_argument("--popup-panel", default=POPUP_PANEL, help="id del panel de Noctalia para el popup")
    ap.add_argument("--no-passive", action="store_true", help="no usar AdvertisementMonitor")
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
