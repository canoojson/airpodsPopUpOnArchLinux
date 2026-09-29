"""Último estado conocido: cada campo guarda valor, timestamp y fuente.

Un valor "no disponible" nunca borra el último conocido: así, con la caja vacía,
la batería de la caja sigue mostrándose con su antigüedad en lugar de desaparecer.
"""
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from .proximity import Battery, CaseAdvert, PodAdvert, PodSecret

SRC_ENC = "ble-enc"      # anuncio largo descifrado (1 %)
SRC_CASE = "ble-case"    # anuncio de la caja descifrado (1 %)
SRC_CLEAR = "ble-clear"  # anuncio largo en claro (10 %), solo sin claves

FIELDS = ("model", "left", "right", "case", "left_in_ear", "right_in_ear",
          "left_in_case", "right_in_case", "lid_closed", "case_on_charger", "rssi")


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "airpods-linux"


STATE_PATH = state_dir() / "state.json"


class StateStore:
    def __init__(self, path: Path | None = STATE_PATH):
        self.path = path
        self.fields: dict[str, dict] = {}

    def update(self, field: str, value, source: str, ts: float | None = None) -> bool:
        """Guarda `value` si no es None y no es más antiguo que lo guardado.
        Devuelve True si el valor visible ha cambiado."""
        if value is None:
            return False
        if isinstance(value, Battery):
            value = asdict(value)
        ts = time.time() if ts is None else ts
        old = self.fields.get(field)
        if old and old["ts"] > ts:
            return False
        self.fields[field] = {"value": value, "ts": ts, "source": source}
        return not old or old["value"] != value

    def get(self, field: str) -> dict | None:
        return self.fields.get(field)

    def value(self, field: str):
        f = self.fields.get(field)
        return f["value"] if f else None

    def last_seen(self) -> float | None:
        return max((f["ts"] for f in self.fields.values()), default=None)

    def to_dict(self) -> dict:
        return {"last_seen": self.last_seen(), "fields": self.fields}

    def load(self) -> "StateStore":
        if self.path and self.path.exists():
            try:
                self.fields = json.loads(self.path.read_text()).get("fields", {})
            except (OSError, ValueError):
                self.fields = {}
        return self

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.replace(tmp, self.path)


def apply_pod(store: StateStore, adv: PodAdvert, secret: PodSecret | None,
              rssi: int | None = None, ts: float | None = None) -> bool:
    """Vuelca un anuncio largo en el estado. Con `secret` usa la batería al 1 %."""
    ts = time.time() if ts is None else ts
    changed = False
    src = SRC_ENC if secret else SRC_CLEAR
    bat = secret or adv
    for field in ("left", "right", "case"):
        changed |= store.update(field, getattr(bat, field), src, ts)
    changed |= store.update("model", adv.model, src, ts)
    changed |= store.update("left_in_ear", adv.left_in_ear, src, ts)
    changed |= store.update("right_in_ear", adv.right_in_ear, src, ts)
    if adv.both_in_case:
        l_case = r_case = True
    elif adv.one_in_case:
        this_left = adv.primary_left
        l_case = adv.this_in_case if this_left else not adv.this_in_case
        r_case = not l_case
    else:
        l_case = r_case = False
    changed |= store.update("left_in_case", l_case, src, ts)
    changed |= store.update("right_in_case", r_case, src, ts)
    changed |= store.update("lid_closed", adv.lid_closed, src, ts)
    store.update("rssi", rssi, src, ts)
    return changed


def apply_case(store: StateStore, case: CaseAdvert, rssi: int | None = None,
               ts: float | None = None) -> bool:
    ts = time.time() if ts is None else ts
    changed = store.update("case", case.case, SRC_CASE, ts)
    changed |= store.update("left", case.left, SRC_CASE, ts)
    changed |= store.update("right", case.right, SRC_CASE, ts)
    # Los auriculares cuentan como "en la caja" si la caja informa de su batería.
    changed |= store.update("left_in_case", case.left is not None, SRC_CASE, ts)
    changed |= store.update("right_in_case", case.right is not None, SRC_CASE, ts)
    if case.pods_in_case:
        changed |= store.update("left_in_ear", False, SRC_CASE, ts)
        changed |= store.update("right_in_ear", False, SRC_CASE, ts)
    changed |= store.update("lid_closed", case.lid_closed, SRC_CASE, ts)
    changed |= store.update("case_on_charger", case.on_charger, SRC_CASE, ts)
    store.update("rssi", rssi, SRC_CASE, ts)
    return changed
