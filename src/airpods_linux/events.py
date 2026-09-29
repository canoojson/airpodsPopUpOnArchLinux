"""Detección de eventos de la caja a partir de observaciones sucesivas.

"Abierta" = una observación con la tapa abierta y algún auricular dentro, tras
haber visto la tapa cerrada o tras un silencio largo (la caja cerrada puede
callarse minutos, y al abrirla los auriculares empiezan a anunciarse enseguida).
Se emite una sola vez por apertura.
"""
from dataclasses import dataclass

from .state import StateStore

OPENED, CLOSED = "opened", "closed"
SILENCE_REARM_S = 90  # sin datos durante este tiempo, la siguiente apertura vuelve a avisar


@dataclass
class CaseEventDetector:
    armed: bool = True           # ¿puede emitir "opened"?
    lid_closed: bool | None = None
    last_obs: float | None = None

    def observe(self, store: StateStore, ts: float) -> str | None:
        """Llamar tras cada observación propia ya volcada en `store`."""
        f = store.get("lid_closed")
        # Solo vale si la tapa se ha observado en *esta* observación.
        lid = f["value"] if f and f["ts"] >= ts else None
        pods_in = bool(store.value("left_in_case") or store.value("right_in_case"))
        if self.last_obs is not None and ts - self.last_obs > SILENCE_REARM_S:
            self.armed = True
        self.last_obs = ts

        event = None
        if lid is True:
            if self.lid_closed is False:
                event = CLOSED
            self.armed = True
        elif lid is False and pods_in and self.armed:
            event = OPENED
            self.armed = False
        if lid is not None:
            self.lid_closed = lid
        return event
