"""Cambio de los AirPods entre el iPhone (u otro dispositivo) y este equipo.

Los AirPods solo mantienen el audio con un dispositivo: cuando el iPhone se los lleva,
cortan la conexión con el PC. Aquí, como hace iOS entre dispositivos de Apple:

1. Si se desconectan mientras el audio del PC salía por ellos, se pausa lo que sonaba
   (y así tampoco salta a los altavoces).
2. Si empieza a sonar algo en el PC con los AirPods cerca y alguno puesto, pero
   conectados a otro dispositivo, se conectan a este equipo.
"""
from dataclasses import dataclass

NEARBY_S = 60           # anuncio BLE de los AirPods como mucho así de antiguo
CONNECT_COOLDOWN_S = 30  # entre intentos de conexión


@dataclass
class HandoffLogic:
    audio_on_airpods: bool = False      # ¿la salida por defecto eran los AirPods?
    last_attempt: float | None = None

    def note_default_sink(self, is_airpods: bool) -> None:
        """Llamar periódicamente con los AirPods conectados."""
        self.audio_on_airpods = is_airpods

    def on_disconnected(self) -> bool:
        """Los AirPods se han desconectado de este equipo. True = pausar la reproducción."""
        pause, self.audio_on_airpods = self.audio_on_airpods, False
        return pause

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
