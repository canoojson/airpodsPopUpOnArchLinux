"""Pausa/reanudación automática al quitarse o ponerse un auricular (como en iOS).

Se razona con el NÚMERO de auriculares puestos, no con el lado: con un auricular en
la caja las fuentes no siempre coinciden en cuál es el izquierdo, y para pausar da igual.

- Baja el número (2→1, 1→0): pausa. Vale igual con los dos puestos que con uno en
  la caja y otro en la oreja.
- Vuelve al número de antes en menos de RESUME_WINDOW_S: reanuda.
- Si mientras tanto baja aún más (te quitas también el otro): no se reanuda.
- Solo con los AirPods conectados a este equipo: si los usas con el móvil, nada.

Hay varias fuentes (airpods-helper por AAP, instantánea pero muda con un auricular en
la caja; anuncios BLE, más lentos pero siempre presentes). Cada una solo cuenta cuando
ella misma ve un cambio, así un dato atrasado de una no deshace lo que ya dijo la otra.
"""
from dataclasses import dataclass, field

PAUSE, RESUME = "pause", "resume"
RESUME_WINDOW_S = 120


@dataclass
class EarPauseLogic:
    count: int | None = None                      # auriculares puestos (vista combinada)
    source_counts: dict = field(default_factory=dict)
    pending: int | None = None                    # número al que hay que volver para reanudar
    remaining: int = 0                            # los que seguían puestos al pausar
    paused_at: float | None = None

    def reset(self) -> None:
        self.count = None
        self.source_counts = {}
        self.cancel_resume()

    def cancel_resume(self) -> None:
        self.pending, self.remaining, self.paused_at = None, 0, None

    def update(self, source: str, left: bool | None, right: bool | None,
               connected: bool | None, now: float) -> str | None:
        """Estado de oreja visto por `source`. Devuelve PAUSE, RESUME o None."""
        if connected is not True:
            self.reset()
            return None
        if left is None and right is None:
            return None
        c = int(left is True) + int(right is True)
        seen = self.source_counts.get(source)
        self.source_counts[source] = c
        if seen is None or seen == c:
            if self.count is None:
                self.count = c
            return None

        prev = self.count if self.count is not None else seen
        self.count = c
        if self.pending is not None and self.paused_at is not None and now - self.paused_at > RESUME_WINDOW_S:
            self.cancel_resume()

        if c < prev:
            if self.pending is None:
                self.pending, self.remaining, self.paused_at = prev, c, now
                return PAUSE
            if c < self.remaining:
                self.cancel_resume()   # te has quitado también el que seguía puesto
        elif c > prev and self.pending is not None and c >= self.pending:
            self.cancel_resume()
            return RESUME
        return None
