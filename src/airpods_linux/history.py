"""Historial de batería en ~/.local/state/airpods-linux/history.jsonl.

Una línea por muestra: {"ts", "left", "right", "case"} con el nivel (o null si no hay
dato fresco) y "lc"/"rc"/"cc" si está cargando. Se escribe cuando cambia algún nivel
y, como mínimo, cada SAMPLE_EVERY_S mientras llegan datos. Se guardan KEEP_DAYS días.

Con él se dibuja la gráfica del panel y se estima el tiempo restante con el ritmo
de descarga de la sesión actual.
"""
import json
import logging
from pathlib import Path

from .fsutil import atomic_write_text
from .state import state_dir

log = logging.getLogger(__name__)

HISTORY_PATH = state_dir() / "history.jsonl"
PARTS = ("left", "right", "case")
CHG = {"left": "lc", "right": "rc", "case": "cc"}
FRESH_S = 120
SAMPLE_EVERY_S = 600
KEEP_DAYS = 30
MIN_SPAN_S = 15 * 60       # descarga mínima observada para estimar
MIN_DROP = 3               # puntos de batería perdidos como mínimo
MAX_GAP_S = 30 * 60        # un hueco mayor corta la sesión de uso


def sample_from(store, now: float) -> dict | None:
    """Muestra con los niveles frescos del estado; None si no hay ninguno."""
    s = {"ts": round(now, 1)}
    for part in PARTS:
        f = store.get(part)
        if f and now - f["ts"] <= FRESH_S:
            s[part] = f["value"]["level"]
            if f["value"]["charging"]:
                s[CHG[part]] = 1
        else:
            s[part] = None
    return s if any(s[p] is not None for p in PARTS) else None


class BatteryHistory:
    def __init__(self, path: Path | None = HISTORY_PATH):
        self.path = path
        self.samples: list[dict] = []

    def load(self) -> "BatteryHistory":
        self.samples = []
        if self.path and self.path.exists():
            try:
                for line in self.path.read_text().splitlines():
                    try:
                        self.samples.append(json.loads(line))
                    except ValueError:
                        continue
            except OSError as e:
                log.warning("no se pudo leer %s: %s", self.path, e)
        return self

    def _same_levels(self, a: dict, b: dict) -> bool:
        return all(a.get(p) == b.get(p) and a.get(CHG[p]) == b.get(CHG[p]) for p in PARTS)

    def record(self, store, now: float) -> bool:
        """Añade una muestra si algo ha cambiado o toca la periódica. True si se escribió."""
        s = sample_from(store, now)
        if s is None:
            return False
        last = self.samples[-1] if self.samples else None
        if last and self._same_levels(last, s) and now - last["ts"] < SAMPLE_EVERY_S:
            return False
        self.samples.append(s)
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with self.path.open("a") as fh:
                    fh.write(json.dumps(s) + "\n")
            except OSError as e:
                log.warning("no se pudo escribir %s: %s", self.path, e)
        return True

    def prune(self, now: float, keep_days: int = KEEP_DAYS) -> int:
        """Borra las muestras más antiguas que keep_days. Devuelve cuántas quitó."""
        cutoff = now - keep_days * 86400
        keep = [s for s in self.samples if s.get("ts", 0) >= cutoff]
        removed = len(self.samples) - len(keep)
        if removed:
            self.samples = keep
            if self.path:
                try:
                    atomic_write_text(self.path, "".join(json.dumps(s) + "\n" for s in keep))
                except OSError as e:
                    log.warning("no se pudo reescribir %s: %s", self.path, e)
        return removed

    def since(self, ts: float) -> list[dict]:
        return [s for s in self.samples if s.get("ts", 0) >= ts]


def series(samples: list[dict], part: str, start: float, end: float, buckets: int) -> list[int | None]:
    """Nivel medio de `part` en `buckets` intervalos iguales entre start y end (None = sin datos)."""
    width = (end - start) / buckets
    sums, counts = [0] * buckets, [0] * buckets
    for s in samples:
        v = s.get(part)
        if v is None or not start <= s["ts"] < end:
            continue
        i = min(buckets - 1, int((s["ts"] - start) / width))
        sums[i] += v
        counts[i] += 1
    return [round(sums[i] / counts[i]) if counts[i] else None for i in range(buckets)]


def discharge_run(samples: list[dict], part: str) -> list[tuple[float, int]]:
    """Últimas muestras seguidas en descarga de `part`, de la más antigua a la más reciente.
    Se corta al cargar, al subir el nivel o con un hueco largo sin datos."""
    run: list[tuple[float, int]] = []
    for s in reversed(samples):
        v = s.get(part)
        if v is None:
            continue
        if s.get(CHG[part]):
            break
        if run and (v < run[-1][1] or run[-1][0] - s["ts"] > MAX_GAP_S):
            break   # al ir hacia atrás el nivel debe subir o mantenerse
        run.append((s["ts"], v))
    run.reverse()
    return run


def estimate_minutes(samples: list[dict], part: str, now: float) -> int | None:
    """Minutos de batería restantes al ritmo de la descarga actual; None si no hay base."""
    run = discharge_run(samples, part)
    if len(run) < 2 or now - run[-1][0] > MAX_GAP_S:
        return None
    (t0, v0), (t1, v1) = run[0], run[-1]
    if t1 - t0 < MIN_SPAN_S or v0 - v1 < MIN_DROP:
        return None
    per_s = (v0 - v1) / (t1 - t0)
    left = v1 / per_s - (now - t1)
    return max(0, round(left / 60))


def summary(hist: BatteryHistory, now: float, hours: int = 24, buckets: int = 48) -> dict:
    """Lo que se publica en el estado del daemon: series para la gráfica y estimaciones."""
    start = now - hours * 3600
    recent = hist.since(start - 3600)
    return {
        "hours": hours,
        "buckets": buckets,   # en Luau un null deja huecos: el panel recorre 1..buckets
        "series": {p: series(recent, p, start, now, buckets) for p in PARTS},
        "remaining_min": {p: estimate_minutes(recent, p, now) for p in ("left", "right")},
    }
