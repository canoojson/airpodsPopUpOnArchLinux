"""Pausa y reanudación de reproductores por MPRIS (Spotify, navegadores, mpv…)."""
import logging

import dbus

log = logging.getLogger(__name__)

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


class MediaController:
    def __init__(self, bus=None):
        self.bus = bus or dbus.SessionBus()
        self.paused_by_us: list[str] = []

    def _players(self) -> list[str]:
        try:
            return [str(n) for n in self.bus.list_names() if str(n).startswith(MPRIS_PREFIX)]
        except dbus.DBusException:
            return []

    def _status(self, name: str) -> str | None:
        try:
            return str(self.bus.get_object(name, MPRIS_PATH).Get(PLAYER_IFACE, "PlaybackStatus",
                                                                 dbus_interface=PROPS_IFACE))
        except dbus.DBusException:
            return None

    def _call(self, name: str, method: str) -> bool:
        try:
            getattr(dbus.Interface(self.bus.get_object(name, MPRIS_PATH), PLAYER_IFACE), method)()
            return True
        except dbus.DBusException as e:
            log.debug("%s.%s: %s", name, method, e.get_dbus_message())
            return False

    def pause_playing(self) -> list[str]:
        """Pausa los reproductores que estén sonando y recuerda cuáles eran."""
        self.paused_by_us = [n for n in self._players() if self._status(n) == "Playing" and self._call(n, "Pause")]
        return self.paused_by_us

    def resume(self) -> list[str]:
        """Reanuda solo lo que pausamos nosotros y sigue en pausa (no lo que pausó el usuario después)."""
        resumed = [n for n in self.paused_by_us if self._status(n) == "Paused" and self._call(n, "Play")]
        self.paused_by_us = []
        return resumed

    def forget(self) -> None:
        self.paused_by_us = []
