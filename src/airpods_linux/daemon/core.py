"""Daemon: estado compartido, conexión con BlueZ y bucle principal.

Cada área vive en su propio controlador (popup, ears, handoff, aapctl, updates); este
módulo los crea, les da acceso al estado y reparte los temporizadores.
"""
import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from .. import config as config_mod
from .. import history as history_mod
from .. import keys as keys_mod
from .. import update as update_mod
from ..alerts import LowBatteryAlerts, message as alert_message
from ..audio import AudioRouter, PactlSinks, VolumeDucker
from ..bluez import get_alias, paired_devices, select_airpods
from ..desktop import POPUP_PANEL, notify
from ..fsutil import atomic_write_text
from ..handoff import AUDIO_STATE_NAMES
from ..media import MediaController
from ..proximity import MODEL_NAMES
from ..state import STATE_PATH, StateStore, runtime_status_path
from .aapctl import AapController
from .airplay import AirplayController
from .ears import EarController
from .handoff import HandoffController
from .popup import CasePopup
from .service import Service
from .updates import UpdateChecker

log = logging.getLogger("airpodsd")


class Daemon:
    def __init__(self, args):
        self.args = args
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.store = StateStore(STATE_PATH).load()
        self.keys = keys_mod.load()
        if not self.keys:
            log.warning("sin claves de proximidad: batería al 10 %% y sin datos con la caja cerrada "
                        "(airpodsctl keys fetch)")
        self.config = config_mod.load()
        self._last_connected = None
        self._last_audio_state = None
        self._alias = None
        self.service = Service(dbus.SessionBus(), self)
        self.session_bus = dbus.SessionBus()
        self.system_bus = dbus.SystemBus()
        self.media = MediaController(self.session_bus)
        self.sinks = PactlSinks()
        self.audio = AudioRouter(self.sinks) if self.sinks.available() else None
        self.ducker = VolumeDucker(self.sinks) if self.sinks.available() else None
        if not self.audio:
            log.warning("pactl no está instalado: el audio no seguirá a la oreja")
        self.alerts = LowBatteryAlerts()
        self.history = history_mod.BatteryHistory().load()
        self.history.prune(time.time())

        self.popup = CasePopup(self, args.popup, args.popup_panel, args.popup_timeout)
        self.ears = EarController(self)
        self.aap = AapController(self)
        self.handoff = HandoffController(self)
        self.updates = UpdateChecker(self)
        self.airplay = AirplayController(self)

        from ..scanner import BleScanner, Tracker
        self.tracker = Tracker(self.store, self.keys, on_change=self._on_ble_change, on_own=self.popup.on_own)
        self.scanner = BleScanner(self.tracker.handle, window=(args.on, args.off), passive=not args.no_passive)
        log.info("modo de escaneo: %s", "pasivo (AdvertisementMonitor)" if self.scanner.passive
                 else f"ventanas {args.on}/{args.off} s")
        self.ears.watch_helper()
        self.handoff.watch()
        self.airplay.watch()

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
            "audio": {"follow_ear": bool(self.config.get("audio_follow_ear", True)),
                      "available": self.audio is not None},
            "ear": {"pause": bool(self.config.get("ear_pause", True)),
                    "resume": bool(self.config.get("ear_resume", True)),
                    "source": self.ears.source()},
            "alerts": {"low_battery": bool(self.config.get("low_battery_alert", True))},
            "aap": self.aap.state(v("model")),
            "history": history_mod.summary(self.history, time.time()),
            "update": self.updates.state(),
            "airplay": self.airplay.state(),
            **self.store.to_dict(),
        }

    def write_status(self) -> str:
        data = json.dumps(self.state())
        path = runtime_status_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_text(path, data, mode=0o644)
        except OSError as e:
            log.warning("no se pudo escribir %s: %s", path, e)
        return data

    def changed(self) -> None:
        """Algo del estado ha cambiado: historial, avisos, D-Bus, fichero de estado y popup."""
        self._battery_tick()
        self.service.StateChanged(self.write_status())
        self.popup.refresh()

    def _on_ble_change(self, _store) -> None:
        state = self.store.value("audio_state")
        if state != self._last_audio_state:
            self._last_audio_state = state
            log.info("AirPods (BLE): audio %s (0x%02x)", AUDIO_STATE_NAMES.get(state, "desconocido"), state or 0)
        self.ears.on_ble()
        self.changed()

    def _battery_tick(self) -> None:
        now = time.time()
        self.history.record(self.store, now)
        alerts = self.alerts.check(self.store, now, self.connected())
        if alerts and self.config.get("low_battery_alert", True):
            title, body, urgent = alert_message(alerts)
            log.info("batería baja: %s", body)
            notify(title, body, icon="battery-caution" if urgent else "battery-low",
                   urgency="critical" if urgent else "normal")

    def _poll_connection(self) -> bool:
        # "Conectado a este equipo" no llega por BLE: se consulta a BlueZ periódicamente.
        connected = self.connected()
        if connected != self._last_connected:
            self._last_connected = connected
            self.changed()
        self.aap.manage(connected)
        return True

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
            self.updates.check()
        self.changed()

    def _quit(self) -> bool:
        if self.ducker:
            self.ducker.restore()
        self.aap.stop()
        self.scanner.quit()
        return False

    def run(self) -> None:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit)
        GLib.timeout_add_seconds(86400, lambda: (self.history.prune(time.time()), True)[1])
        self.write_status()
        GLib.timeout_add_seconds(5, self._poll_connection)
        GLib.timeout_add_seconds(2, self.ears.audio_tick)
        GLib.timeout_add_seconds(2, self.aap.call_tick)
        GLib.timeout_add_seconds(2, self.handoff.tick)
        GLib.timeout_add_seconds(2, self.airplay.tick)
        self.updates.schedule()
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
