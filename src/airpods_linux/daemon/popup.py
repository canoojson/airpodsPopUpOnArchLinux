"""Popup al abrir la caja: detecta apertura y cierre en los anuncios propios y lo muestra."""
import json
import logging

from gi.repository import GLib

from ..desktop import Popup
from ..events import CLOSED, OPENED, CaseEventDetector

log = logging.getLogger("airpodsd")


def pct(field: dict | None) -> str:
    return f"{field['value']['level']} %" if field else "--"


class CasePopup:
    def __init__(self, daemon, mode: str, panel_id: str, timeout_s: int):
        self.d = daemon
        self.detector = CaseEventDetector()
        self.popup = Popup(mode, panel_id)
        self.timeout_s = timeout_s
        self._timer = None
        self._refresh_timer = None

    def payload(self) -> dict:
        st = self.d.state()
        st.pop("history", None)   # el popup no la usa y va por la línea de órdenes de noctalia
        g = self.d.store.get
        st["title"] = st["name"] or st["model_name"]
        st["summary"] = f"Izquierdo {pct(g('left'))} · Derecho {pct(g('right'))} · Caja {pct(g('case'))}"
        return st

    def refresh(self) -> None:
        """Reenvía el estado al popup abierto si ha cambiado lo que se ve."""
        self.popup.update(self.payload())

    def on_own(self, _kind: str, ts: float) -> None:
        event = self.detector.observe(self.d.store, ts)
        if event == OPENED:
            log.info("caja abierta con auriculares dentro")
            payload = self.payload()
            log.info("popup: %s", "noctalia" if self.popup.mode != "none" else "desactivado")
            self.d.service.CaseOpened(json.dumps(payload))
            self.popup.show(payload)
            self._arm_timeout()
        elif event == CLOSED:
            log.info("caja cerrada")
            self.d.service.CaseClosed()
            self.popup.close()

    def _arm_timeout(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
        # Red de seguridad: el panel se cierra solo, pero por si se queda abierto.
        self._timer = GLib.timeout_add_seconds(self.timeout_s + 2, self._expired)
        if not self._refresh_timer:
            self._refresh_timer = GLib.timeout_add_seconds(1, self._refresh_tick)

    def _refresh_tick(self) -> bool:
        # Refresca también lo que no llega por BLE (p. ej. conectado a este equipo).
        if not self.popup.open:
            self._refresh_timer = None
            return False
        self.refresh()
        return True

    def _expired(self) -> bool:
        self._timer = None
        self.popup.close()
        return False
