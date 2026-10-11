"""Cambio de los AirPods entre el iPhone (u otro dispositivo) y este equipo.

Los AirPods solo mantienen el audio con un dispositivo: cuando el iPhone se los lleva,
cortan la conexión con el PC. Aquí, como hace iOS entre dispositivos de Apple:

1. Si se desconectan mientras el audio del PC salía por ellos, se pausa lo que sonaba
   (y así tampoco salta a los altavoces).
2. Si empieza a sonar algo en el PC con los AirPods cerca y alguno puesto, pero
   conectados a otro dispositivo, se conectan a este equipo.
3. Si se fueron mientras el PC tenía audio que no se puede pausar (una llamada de
   Discord), vuelven en cuanto el otro dispositivo deja de reproducir: los AirPods
   anuncian por BLE su estado de audio (byte 10), también con el otro dispositivo.
"""
from dataclasses import dataclass

NEARBY_S = 60           # anuncio BLE de los AirPods como mucho así de antiguo
CONNECT_COOLDOWN_S = 30  # entre intentos de conexión
IDLE_BEFORE_RETURN_S = 3  # el otro dispositivo debe llevar este tiempo sin reproducir
RETURN_WINDOW_S = 3600   # pasado este tiempo ya no se intenta devolverlos

# Byte 10 del anuncio de los AirPods: estado del audio con su dispositivo. Base de
# LibrePods, completada con lo visto en unos AirPods Pro 3 (2026-10-11): en reposo es
# 0x04 con el PC y 0x08 con el iPhone. 0x09 es otra forma de "reproduciendo" (estuvo
# 19 min así con el iPhone sonando) y 0x0d, la transición entre contenidos.
AUDIO_DISCONNECTED, AUDIO_IDLE, AUDIO_MUSIC, AUDIO_CALL, AUDIO_RINGING = 0x00, 0x04, 0x05, 0x06, 0x07
AUDIO_IDLE_OTHER, AUDIO_PLAYING_OTHER = 0x08, 0x09
AUDIO_PLAYING = {AUDIO_MUSIC, AUDIO_CALL, AUDIO_RINGING, AUDIO_PLAYING_OTHER}
AUDIO_STOPPED = {AUDIO_DISCONNECTED, AUDIO_IDLE, AUDIO_IDLE_OTHER}   # el resto: transiciones
AUDIO_STATE_NAMES = {AUDIO_DISCONNECTED: "sin conexión", AUDIO_IDLE: "en reposo", AUDIO_IDLE_OTHER: "en reposo",
                     AUDIO_MUSIC: "reproduciendo", AUDIO_CALL: "en llamada", AUDIO_RINGING: "sonando",
                     AUDIO_PLAYING_OTHER: "reproduciendo", 0x0D: "cambiando"}


@dataclass
class HandoffLogic:
    audio_on_airpods: bool = False      # ¿la salida por defecto eran los AirPods?
    last_attempt: float | None = None
    left_at: float | None = None        # se fueron con audio del PC saliendo por ellos
    idle_since: float | None = None     # desde cuándo el otro dispositivo está en reposo
    # Solo cuenta el reposo después de ver reproducir al otro dispositivo: justo al
    # llevárselos pasa unos segundos en reposo antes de empezar (visto con un iPhone).
    other_played: bool = False

    def note_default_sink(self, is_airpods: bool) -> None:
        """Llamar periódicamente con los AirPods conectados."""
        self.audio_on_airpods = is_airpods

    def on_disconnected(self, now: float) -> bool:
        """Los AirPods se han desconectado de este equipo. True = pausar la reproducción."""
        pause, self.audio_on_airpods = self.audio_on_airpods, False
        if pause:
            self.left_at, self.idle_since, self.other_played = now, None, False
        return pause

    def on_connected(self) -> None:
        self.left_at = self.idle_since = None
        self.other_played = False

    def note_audio_state(self, state: int | None, now: float) -> None:
        """Estado de audio anunciado por los AirPods (con el dispositivo que los tenga)."""
        if state in AUDIO_PLAYING:
            self.other_played = True
        if state in AUDIO_STOPPED and self.other_played:
            if self.idle_since is None:
                self.idle_since = now
        else:
            self.idle_since = None

    def should_return(self, now: float, connected: bool | None, seen_ts: float | None, in_ear: bool,
                      pc_audio_active: bool) -> bool:
        """True = el otro dispositivo ha dejado de reproducir y el PC sigue con audio
        (p. ej. una llamada): devolver los AirPods a este equipo."""
        if self.left_at is None:
            return False
        if now - self.left_at > RETURN_WINDOW_S:
            self.left_at = None
            return False
        if not pc_audio_active or self.idle_since is None or now - self.idle_since < IDLE_BEFORE_RETURN_S:
            return False
        return self.should_connect(now, connected, seen_ts, in_ear)

    def should_connect(self, now: float, connected: bool | None, seen_ts: float | None,
                       in_ear: bool) -> bool:
        """Ha empezado a sonar algo en el PC. True = conectar los AirPods a este equipo.

        connected: None si no están emparejados con este equipo (no se puede).
        seen_ts: último anuncio BLE de los AirPods; in_ear: alguno puesto según ese anuncio.
        """
        if connected is not False or seen_ts is None or not in_ear:
            return False
        if now - seen_ts > NEARBY_S:
            return False
        if self.last_attempt is not None and now - self.last_attempt < CONNECT_COOLDOWN_S:
            return False
        self.last_attempt = now
        return True
