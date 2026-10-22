"""Cambio entre el iPhone y este equipo (la lógica está en ..handoff)."""
import logging
import time

from ..audio import airpods_sink_prefix
from ..handoff import HandoffLogic
from ..media import PLAYER_IFACE
from .ears import players

log = logging.getLogger("airpodsd")


class HandoffController:
    def __init__(self, daemon):
        self.d = daemon
        self.logic = HandoffLogic()

    def watch(self) -> None:
        # Conexión y desconexión al instante (el sondeo de Daemon._poll_connection va cada 5 s).
        self.d.system_bus.add_signal_receiver(self._on_bluez_props, "PropertiesChanged",
                                              "org.freedesktop.DBus.Properties", "org.bluez",
                                              path_keyword="path")
        # Algo empieza a sonar en este equipo (MPRIS).
        self.d.session_bus.add_signal_receiver(self._on_mpris_props, "PropertiesChanged",
                                               "org.freedesktop.DBus.Properties", None,
                                               "/org/mpris/MediaPlayer2")

    def _ear_seen(self) -> tuple[float | None, bool]:
        """Cuándo se vio la oreja por última vez y si había algún auricular puesto."""
        f_left, f_right = self.d.store.get("left_in_ear"), self.d.store.get("right_in_ear")
        seen = max((f["ts"] for f in (f_left, f_right) if f), default=None)
        in_ear = bool((f_left and f_left["value"]) or (f_right and f_right["value"]))
        return seen, in_ear

    def tick(self) -> bool:
        """Cada 2 s: ¿sale el audio de este equipo por los AirPods? Y, si se los llevó otro
        dispositivo con una llamada en marcha aquí, ¿toca devolverlos?"""
        d = self.d
        address = d.airpods_address()
        if not address:
            return True
        connected = d.connected(address)
        if connected is True:
            default = d.sinks.default() or ""
            self.logic.note_default_sink(default.startswith(airpods_sink_prefix(address)))
            return True
        now = time.time()
        f_state = d.store.get("audio_state")
        self.logic.note_audio_state(f_state["value"] if f_state and now - f_state["ts"] < 60 else None, now)
        seen, in_ear = self._ear_seen()
        if self.logic.should_return(now, connected, seen, in_ear, d.sinks.audio_active()):
            log.info("el otro dispositivo ha dejado de reproducir y aquí sigue sonando algo: vuelvo a conectar los AirPods")
            self.connect(address, "al dejar de usarlos el otro dispositivo")
        return True

    def connect(self, address: str, why: str) -> None:
        path = f"{self.d.scanner.adapter_path}/dev_{address.upper().replace(':', '_')}"
        self.d.system_bus.get_object("org.bluez", path).Connect(
            dbus_interface="org.bluez.Device1", timeout=20,
            reply_handler=lambda: log.info("AirPods conectados a este equipo (%s)", why),
            error_handler=lambda e: log.warning("no se pudo conectar los AirPods: %s", e.get_dbus_message()))

    def _on_bluez_props(self, iface, changed, _invalidated, path=None) -> None:
        address = self.d.airpods_address()
        if (iface != "org.bluez.Device1" or "Connected" not in changed or not address
                or not str(path).endswith("dev_" + address.upper().replace(":", "_"))):
            return
        if bool(changed["Connected"]):
            log.info("AirPods conectados a este equipo")
            self.logic.on_connected()
            return
        if self.logic.on_disconnected(time.time()):
            paused = self.d.media.pause_playing()
            self.d.media.forget()   # no se reanuda solo: como en iOS, al volver le das a play
            log.info("AirPods desconectados (¿se los ha llevado otro dispositivo?): %s",
                     f"pausado {players(paused)}" if paused else "nada sonando")
            self.d.airplay.on_airpods_taken(bool(paused))

    def _on_mpris_props(self, iface, changed, _invalidated) -> None:
        if iface != PLAYER_IFACE or str(changed.get("PlaybackStatus", "")) != "Playing":
            return
        seen, in_ear = self._ear_seen()
        address = self.d.airpods_address()
        if address and self.logic.should_connect(time.time(), self.d.connected(address), seen, in_ear):
            log.info("empieza a sonar algo en este equipo con los AirPods puestos: los conecto aquí")
            self.connect(address, "por reproducción")
