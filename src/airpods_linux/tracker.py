"""Filtrado de los anuncios propios y volcado en el estado. Sin D-Bus: se prueba con las capturas."""
from typing import Callable

from . import keys as keys_mod
from .crypto import resolves_rpa
from .proximity import MODEL_NAMES, decrypt_case, decrypt_pod, is_case_advert, parse_pod_advert
from .state import StateStore, apply_case, apply_pod

# Sin claves: heurística de modelo conocido + cercanía (hay AirPods ajenos alrededor).
NO_KEYS_MIN_RSSI = -65


class Tracker:
    """Filtra los anuncios propios y los vuelca en el StateStore."""

    def __init__(self, store: StateStore, keys: keys_mod.ProximityKeys | None,
                 on_change: Callable[[StateStore], None] | None = None,
                 on_own: Callable[[str, float], None] | None = None):
        self.store, self.keys = store, keys
        self.on_change, self.on_own = on_change, on_own
        # True mientras AAP da batería, oreja y caja: los anuncios solo aportan el resto.
        self.aap_active = False
        self._own_addrs: dict[str, bool] = {}

    def reset_cache(self) -> None:
        """Olvida qué direcciones eran nuestras (al cambiar de claves)."""
        self._own_addrs = {}

    def _is_own_pod(self, addr: str) -> bool:
        if addr not in self._own_addrs:
            self._own_addrs[addr] = resolves_rpa(self.keys.irk, addr)
        return self._own_addrs[addr]

    def handle(self, addr: str, rssi: int, data: bytes, ts: float) -> None:
        changed, kind = False, None
        adv = parse_pod_advert(data)
        if adv:
            if self.keys and self._is_own_pod(addr):
                changed = apply_pod(self.store, adv, decrypt_pod(adv, self.keys.enc_key), rssi, ts,
                                    live=not self.aap_active)
                kind = "pod"
            elif not self.keys and adv.model in MODEL_NAMES and rssi >= NO_KEYS_MIN_RSSI:
                changed = apply_pod(self.store, adv, None, rssi, ts, live=not self.aap_active)
                kind = "pod"
        elif self.keys and is_case_advert(data):
            case = decrypt_case(data, self.keys.enc_key)
            if case:
                changed = apply_case(self.store, case, rssi, ts, live=not self.aap_active)
                kind = "case"
        if kind:
            self.store.save()
            if self.on_own:
                self.on_own(kind, ts)
        if changed and self.on_change:
            self.on_change(self.store)
