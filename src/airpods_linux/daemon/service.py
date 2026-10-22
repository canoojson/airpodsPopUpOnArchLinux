"""Objeto D-Bus de airpodsd en el bus de sesión.

io.github.AirpodsLinux  /io/github/AirpodsLinux  io.github.AirpodsLinux1
  GetState() -> s (JSON)      StateChanged(s)   CaseOpened(s)   CaseClosed()
  SetSetting(s nombre, s valor)   FetchKeys() -> b   (con la conexión AAP propia)
"""
import json

import dbus
import dbus.service

BUS_NAME = "io.github.AirpodsLinux"
OBJ_PATH = "/io/github/AirpodsLinux"
IFACE = "io.github.AirpodsLinux1"


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
        self._daemon.updates.check(manual=True)

    @dbus.service.method(IFACE, in_signature="ss")
    def SetSetting(self, name, value):
        """Cambia un ajuste de los AirPods por AAP (ver aap.SETTINGS)."""
        err = self._daemon.aap.set_setting(str(name), str(value))
        if err:
            raise dbus.exceptions.DBusException(err, name=IFACE + ".Error")

    @dbus.service.method(IFACE, out_signature="b")
    def FetchKeys(self):
        """Pide las claves de proximidad por la conexión AAP; se guardan al llegar."""
        return self._daemon.aap.request_keys()

    @dbus.service.signal(IFACE, signature="s")
    def StateChanged(self, state_json):
        pass

    @dbus.service.signal(IFACE, signature="s")
    def CaseOpened(self, state_json):
        pass

    @dbus.service.signal(IFACE)
    def CaseClosed(self):
        pass
