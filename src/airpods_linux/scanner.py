"""Escaneo BLE pasivo con BlueZ (D-Bus) y filtrado de los AirPods propios.

Solo se consideran frescos los datos que llegan por señal (InterfacesAdded o
PropertiesChanged con RSSI/ManufacturerData): la caché de BlueZ puede tener
anuncios de hace minutos y no debe presentarse como actual.
"""
import logging
import time
from typing import Callable

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from . import advmon
from . import keys as keys_mod
from .crypto import resolves_rpa
from .proximity import MODEL_NAMES, decrypt_case, decrypt_pod, is_case_advert, parse_pod_advert
from .state import StateStore, apply_case, apply_pod

log = logging.getLogger(__name__)

APPLE = 0x004C
BLUEZ = "org.bluez"
DEVICE_IFACE = "org.bluez.Device1"
# Sin claves: heurística de modelo conocido + cercanía (hay AirPods ajenos alrededor).
NO_KEYS_MIN_RSSI = -65

Advert = Callable[[str, int, bytes, float], None]


class BleScanner:
    """Llama a `on_advert(addr, rssi, data, ts)` por cada anuncio Apple 0x07.

    `window=(on, off)` alterna discovery activo/parado para no impedir que el
    kernel reconecte otros dispositivos LE. `window=None` escanea sin pausa.
    `passive=True` usa AdvertisementMonitor (sin discovery) si BlueZ lo ofrece,
    y si no, vuelve a las ventanas.
    """

    def __init__(self, on_advert: Advert, window: tuple[float, float] | None = (4, 8),
                 passive: bool = False):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.on_advert = on_advert
        self.window = window
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.adapter_path = self._find_adapter()
        self.adapter = dbus.Interface(self.bus.get_object(BLUEZ, self.adapter_path), "org.bluez.Adapter1")
        self.cache: dict[str, dict] = {}
        self._scanning = False
        self.passive = passive and advmon.supported(self.bus, self.adapter_path)
        if passive and not self.passive:
            log.warning("AdvertisementMonitor no disponible (¿Experimental = true en main.conf?); "
                        "uso escaneo por ventanas")
        self._monitor = None

    def _find_adapter(self) -> str:
        om = dbus.Interface(self.bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
        for path, ifaces in om.GetManagedObjects().items():
            if "org.bluez.Adapter1" in ifaces:
                return str(path)
        raise RuntimeError("No hay adaptador Bluetooth")

    def _on_monitor_found(self, path: str) -> None:
        """El monitor acaba de ver un anuncio de este dispositivo: sus datos son frescos."""
        try:
            props = self.bus.get_object(BLUEZ, path).GetAll(
                DEVICE_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
        except dbus.DBusException:
            return
        self._handle(path, props, fresh=True)

    def _fallback_to_windows(self, _err=None) -> None:
        self.passive = False
        self.window = self.window or (4, 8)
        self._start()

    def _handle(self, path: str, props, fresh: bool) -> None:
        d = self.cache.setdefault(path, {"addr": None, "mfg": None, "rssi": None})
        if "Address" in props:
            d["addr"] = str(props["Address"])
        if "RSSI" in props:
            d["rssi"] = int(props["RSSI"])
        md = props.get("ManufacturerData")
        if md is not None and APPLE in md:
            d["mfg"] = bytes(md[APPLE])
        if not fresh or not ("RSSI" in props or "ManufacturerData" in props):
            return
        if d["addr"] is None:
            try:
                d["addr"] = str(self.bus.get_object(BLUEZ, path).Get(
                    DEVICE_IFACE, "Address", dbus_interface="org.freedesktop.DBus.Properties"))
            except dbus.DBusException:
                return
        if d["mfg"] and d["mfg"][0] == 0x07 and d["rssi"] is not None:
            self.on_advert(d["addr"], d["rssi"], d["mfg"], time.time())

    def _on_added(self, path, ifaces):
        if DEVICE_IFACE in ifaces:
            self._handle(str(path), ifaces[DEVICE_IFACE], fresh=True)

    def _on_changed(self, iface, changed, invalidated, path=None):
        if iface == DEVICE_IFACE:
            self._handle(str(path), changed, fresh=True)

    def _start(self) -> bool:
        try:
            self.adapter.SetDiscoveryFilter({"Transport": "le", "DuplicateData": dbus.Boolean(True)})
            self.adapter.StartDiscovery()
            self._scanning = True
        except dbus.DBusException as e:
            log.warning("StartDiscovery: %s", e.get_dbus_message())
        if self.window:
            GLib.timeout_add(int(self.window[0] * 1000), self._stop)
        return False

    def _stop(self) -> bool:
        if self._scanning:
            try:
                self.adapter.StopDiscovery()
            except dbus.DBusException:
                pass
            self._scanning = False
        if self.window and self.loop.is_running():
            GLib.timeout_add(int(self.window[1] * 1000), self._start)
        return False

    def run(self, duration: float | None = None) -> None:
        self.bus.add_signal_receiver(self._on_added, "InterfacesAdded",
                                     "org.freedesktop.DBus.ObjectManager", BLUEZ)
        self.bus.add_signal_receiver(self._on_changed, "PropertiesChanged",
                                     "org.freedesktop.DBus.Properties", BLUEZ, path_keyword="path")
        if duration:
            GLib.timeout_add(int(duration * 1000), self.loop.quit)
        if self.passive:
            self._monitor = advmon.register(self.bus, self.adapter_path, self._on_monitor_found,
                                            on_error=self._fallback_to_windows)
        else:
            self._start()
        try:
            self.loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.window = None
            self._stop()

    def burst(self, seconds: float) -> None:
        """Escaneo activo temporal (p. ej. mientras se muestra el popup) sobre el modo pasivo."""
        if not self.passive:
            return  # las ventanas ya escanean activamente
        if getattr(self, "_burst_timer", None):
            GLib.source_remove(self._burst_timer)
        else:
            try:
                self.adapter.SetDiscoveryFilter({"Transport": "le", "DuplicateData": dbus.Boolean(True)})
                self.adapter.StartDiscovery()
                self._scanning = True
            except dbus.DBusException as e:
                log.warning("StartDiscovery: %s", e.get_dbus_message())
        self._burst_timer = GLib.timeout_add(int(seconds * 1000), self._end_burst)

    def end_burst(self) -> None:
        if getattr(self, "_burst_timer", None):
            GLib.source_remove(self._burst_timer)
            self._end_burst()

    def _end_burst(self) -> bool:
        self._burst_timer = None
        if self._scanning:
            try:
                self.adapter.StopDiscovery()
            except dbus.DBusException:
                pass
            self._scanning = False
        return False

    def quit(self) -> None:
        self.loop.quit()


class Tracker:
    """Filtra los anuncios propios y los vuelca en el StateStore."""

    def __init__(self, store: StateStore, keys: keys_mod.ProximityKeys | None,
                 on_change: Callable[[StateStore], None] | None = None,
                 on_own: Callable[[str, float], None] | None = None):
        self.store, self.keys = store, keys
        self.on_change, self.on_own = on_change, on_own
        self._own_addrs: dict[str, bool] = {}

    def _is_own_pod(self, addr: str) -> bool:
        if addr not in self._own_addrs:
            self._own_addrs[addr] = resolves_rpa(self.keys.irk, addr)
        return self._own_addrs[addr]

    def handle(self, addr: str, rssi: int, data: bytes, ts: float) -> None:
        changed, kind = False, None
        adv = parse_pod_advert(data)
        if adv:
            if self.keys and self._is_own_pod(addr):
                changed = apply_pod(self.store, adv, decrypt_pod(adv, self.keys.enc_key), rssi, ts)
                kind = "pod"
            elif not self.keys and adv.model in MODEL_NAMES and rssi >= NO_KEYS_MIN_RSSI:
                changed = apply_pod(self.store, adv, None, rssi, ts)
                kind = "pod"
        elif self.keys and is_case_advert(data):
            case = decrypt_case(data, self.keys.enc_key)
            if case:
                changed = apply_case(self.store, case, rssi, ts)
                kind = "case"
        if kind:
            self.store.save()
            if self.on_own:
                self.on_own(kind, ts)
        if changed and self.on_change:
            self.on_change(self.store)
