"""Monitor pasivo de anuncios con org.bluez.AdvertisementMonitorManager1.

El controlador (o el kernel, si no hay offload) filtra los anuncios de fabricante
Apple 0x07 sin mantener un discovery activo, así que no interfiere con la
reconexión de otros dispositivos LE. Los datos llegan como siempre, por
PropertiesChanged de org.bluez.Device1. Requiere `Experimental = true` en
/etc/bluetooth/main.conf.
"""
import logging

import dbus
import dbus.service

log = logging.getLogger(__name__)

BLUEZ = "org.bluez"
MANAGER_IFACE = "org.bluez.AdvertisementMonitorManager1"
MONITOR_IFACE = "org.bluez.AdvertisementMonitor1"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
APP_PATH = "/io/github/airpods_linux/advmon"
AD_MANUFACTURER = 0xFF
# 4C 00 = Apple (little-endian), 07 = Proximity Pairing
APPLE_PROXIMITY = bytes([0x4C, 0x00, 0x07])


class Monitor(dbus.service.Object):
    def __init__(self, bus, path: str, on_found=None):
        super().__init__(bus, path)
        self.path = path
        self.on_found = on_found

    def props(self) -> dict:
        return {
            "Type": dbus.String("or_patterns"),
            # 0 = informar de todos los anuncios (por defecto 0xFF: uno por periodo)
            "RSSISamplingPeriod": dbus.UInt16(0),
            "Patterns": dbus.Array([dbus.Struct((dbus.Byte(0), dbus.Byte(AD_MANUFACTURER),
                                                 dbus.Array(APPLE_PROXIMITY, signature="y")))],
                                   signature="(yyay)"),
        }

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.props() if iface == MONITOR_IFACE else {}

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.props()[name]

    @dbus.service.method(MONITOR_IFACE)
    def Release(self):
        log.info("monitor liberado por BlueZ")

    @dbus.service.method(MONITOR_IFACE)
    def Activate(self):
        log.info("monitor activo")

    @dbus.service.method(MONITOR_IFACE, in_signature="o")
    def DeviceFound(self, device):
        log.debug("DeviceFound %s", device)
        if self.on_found:
            self.on_found(str(device))

    @dbus.service.method(MONITOR_IFACE, in_signature="o")
    def DeviceLost(self, device):
        log.debug("DeviceLost %s", device)


class MonitorApp(dbus.service.Object):
    def __init__(self, bus, on_found=None):
        super().__init__(bus, APP_PATH)
        self.monitor = Monitor(bus, APP_PATH + "/apple0", on_found)

    @dbus.service.method(OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {dbus.ObjectPath(self.monitor.path): {MONITOR_IFACE: self.monitor.props()}}


def supported(bus, adapter_path: str) -> bool:
    try:
        types = bus.get_object(BLUEZ, adapter_path).Get(MANAGER_IFACE, "SupportedMonitorTypes",
                                                         dbus_interface=PROPS_IFACE)
        return "or_patterns" in types
    except dbus.DBusException:
        return False


def register(bus, adapter_path: str, on_found=None, on_error=None) -> MonitorApp:
    """Registra el monitor (asíncrono). `on_found(device_path)` en cada DeviceFound;
    `on_error(exc)` si BlueZ lo rechaza."""
    app = MonitorApp(bus, on_found)
    mgr = dbus.Interface(bus.get_object(BLUEZ, adapter_path), MANAGER_IFACE)
    mgr.RegisterMonitor(dbus.ObjectPath(APP_PATH),
                        reply_handler=lambda: log.info("monitor registrado"),
                        error_handler=lambda e: (log.warning("RegisterMonitor: %s", e),
                                                 on_error and on_error(e)))
    return app
