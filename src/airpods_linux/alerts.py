"""Aviso de batería baja: una vez por umbral (20 % y 10 %) y por ciclo de carga.

- Auriculares: solo con los AirPods conectados a este equipo (si los usas con el móvil,
  el aviso es cosa del móvil), fuera de la caja y sin cargar.
- Caja: con cualquier observación fresca, si no está cargando.
- Solo cuentan los datos frescos: un valor antiguo del estado guardado no avisa.
- Se vuelve a armar al cargar o al subir 5 puntos por encima del umbral.
"""
from dataclasses import dataclass, field

THRESHOLDS = (20, 10)
REARM_MARGIN = 5
FRESH_S = 120

NAMES = {"left": "Izquierdo", "right": "Derecho", "case": "Caja"}


@dataclass(frozen=True)
class Alert:
    part: str        # left | right | case
    level: int
    threshold: int


@dataclass
class LowBatteryAlerts:
    alerted: dict = field(default_factory=dict)   # parte -> umbral más bajo ya avisado

    def _check(self, part: str, f: dict | None, now: float, eligible: bool) -> Alert | None:
        if not f or now - f["ts"] > FRESH_S:
            return None
        level, charging = f["value"]["level"], f["value"]["charging"]
        done = self.alerted.get(part)
        if charging or (done is not None and level > done + REARM_MARGIN):
            self.alerted.pop(part, None)
            done = None
        if charging or not eligible:
            return None
        hit = min((t for t in THRESHOLDS if level <= t), default=None)
        if hit is None or (done is not None and hit >= done):
            return None
        self.alerted[part] = hit
        return Alert(part, level, hit)

    def check(self, store, now: float, connected: bool | None) -> list[Alert]:
        out = []
        for side in ("left", "right"):
            in_case = store.value(f"{side}_in_case")
            a = self._check(side, store.get(side), now, connected is True and in_case is not True)
            if a:
                out.append(a)
        a = self._check("case", store.get("case"), now, True)
        if a:
            out.append(a)
        return out


def message(alerts: list[Alert]) -> tuple[str, str, bool]:
    """(título, cuerpo, urgente) de una notificación que agrupa los avisos."""
    body = " · ".join(f"{NAMES[a.part]} {a.level} %" for a in alerts)
    urgent = any(a.threshold <= THRESHOLDS[-1] for a in alerts)
    pods = [a for a in alerts if a.part != "case"]
    if pods and len(pods) < len(alerts):
        title = "AirPods y caja con batería baja"
    elif pods:
        title = "AirPods con batería baja"
    else:
        title = "Caja de los AirPods con batería baja"
    return title, body, urgent
