"""Pausa/reanudación automática al quitarse o ponerse un auricular (como en iOS).

- Pausa cuando un auricular que estaba en la oreja deja de estarlo: vale igual con
  los dos puestos que con uno en la caja y otro en la oreja.
- Reanuda si ese mismo auricular vuelve a la oreja antes de RESUME_WINDOW_S.
- No reanuda si mientras tanto se quita también el otro (te los has quitado todos).
- Solo con los AirPods conectados a este equipo: si los usas con el móvil, nada.
"""
from dataclasses import dataclass, field

PAUSE, RESUME = "pause", "resume"
RESUME_WINDOW_S = 120
SIDES = ("left", "right")


@dataclass
class EarPauseLogic:
    prev: dict = field(default_factory=lambda: {"left": None, "right": None})
    pending: set | None = None      # auriculares que deben volver para reanudar
    remaining: set = field(default_factory=set)  # los que seguían puestos al pausar
    paused_at: float | None = None

    def reset(self) -> None:
        self.prev = {"left": None, "right": None}
        self.cancel_resume()

    def cancel_resume(self) -> None:
        self.pending, self.remaining, self.paused_at = None, set(), None

    def update(self, left: bool | None, right: bool | None, connected: bool | None, now: float) -> str | None:
        """Nuevo estado de oreja. Devuelve PAUSE, RESUME o None."""
        if connected is not True:
            self.reset()
            return None
        cur = {"left": left, "right": right}
        removed = {s for s in SIDES if self.prev[s] is True and cur[s] is False}
        inserted = {s for s in SIDES if self.prev[s] is False and cur[s] is True}
        for s in SIDES:
            if cur[s] is not None:
                self.prev[s] = cur[s]

        if self.pending is not None and self.paused_at is not None and now - self.paused_at > RESUME_WINDOW_S:
            self.cancel_resume()

        action = None
        if removed:
            if self.pending is None:
                action = PAUSE
                self.pending = set(removed)
                self.remaining = {s for s in SIDES if cur[s] is True}
                self.paused_at = now
            elif removed & self.remaining:
                # Se ha quitado también el que seguía puesto: no se reanuda.
                self.cancel_resume()
        elif inserted and self.pending is not None and self.pending <= {s for s in SIDES if cur[s] is True}:
            action = RESUME
            self.cancel_resume()
        return action
