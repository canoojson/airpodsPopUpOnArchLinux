"""UxPlay: el iPhone sonando por AirPlay en el PC a la vez que el resto (ver ..airplay)."""
import logging
import time

import dbus

from .. import airplay
from ..desktop import notify
from ..i18n import _
from ..media import MPRIS_PATH, PLAYER_IFACE, PROPS_IFACE

log = logging.getLogger("airpodsd")


class AirplayController:
    def __init__(self, daemon):
        self.d = daemon
        self.hint = airplay.HintPolicy()
        self.info = airplay.status(False, None, None)

    def watch(self) -> None:
        bus = self.d.session_bus
        bus.add_signal_receiver(lambda *_a: self.refresh(), "NameOwnerChanged", "org.freedesktop.DBus",
                                arg0=airplay.UXPLAY_BUS)
        bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS_IFACE, airplay.UXPLAY_BUS, MPRIS_PATH)
        self.refresh()

    def _running(self) -> bool:
        try:
            return bool(self.d.session_bus.name_has_owner(airplay.UXPLAY_BUS))
        except dbus.DBusException:
            return False

    def _mpris(self) -> dict | None:
        try:
            obj = self.d.session_bus.get_object(airplay.UXPLAY_BUS, MPRIS_PATH, introspect=False)
            return obj.GetAll(PLAYER_IFACE, dbus_interface=PROPS_IFACE)
        except dbus.DBusException:
            return None

    def _on_props(self, iface, _changed, _invalidated) -> None:
        if iface == PLAYER_IFACE:
            self.refresh()

    def refresh(self) -> None:
        running = self._running()
        streams = self.d.sinks.sink_inputs() if running and self.d.audio else None
        info = airplay.status(running, self._mpris() if running else None, streams)
        if info != self.info:
            if info["playing"] != self.info["playing"]:
                log.info("AirPlay (UxPlay): %s", "sonando" if info["playing"] else "parado")
            self.info = info
            self.d.changed()

    def tick(self) -> bool:
        """Cada 2 s con UxPlay en marcha. Su MPRIS no siempre avisa de que suena (con el audio de
        Música del iPhone se queda en "Stopped"), así que se mira el flujo de PipeWire igualmente;
        además su volumen puede cambiar desde el iPhone o pavucontrol."""
        if self.info["running"]:
            self.refresh()
        return True

    def state(self) -> dict:
        return {**self.info, "receiver": airplay.receiver_name() if self.info["running"] else None,
                "hint": bool(self.d.config.get("airplay_hint", True))}

    def on_airpods_taken(self, pc_was_playing: bool) -> None:
        """El otro dispositivo se ha llevado los AirPods: recordar que con AirPlay suenan los dos."""
        if not self.d.config.get("airplay_hint", True):
            return
        if self.hint.should_hint(time.time(), self.info["running"], pc_was_playing):
            name = airplay.receiver_name()
            target = f"«{name}»" if name else _("este equipo")
            log.info("aviso: con AirPlay a %s se oyen el iPhone y el PC a la vez", target)
            notify(_("¿El iPhone y el PC a la vez?"),
                   _("En el iPhone, manda el audio por AirPlay a {target}: así los AirPods se quedan "
                     "en el PC y suenan los dos.").format(target=target))
