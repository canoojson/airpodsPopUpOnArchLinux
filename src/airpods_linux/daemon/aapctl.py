"""Conexión AAP propia: batería y oreja al instante, ajustes, conversación y claves.

Se abre con los AirPods conectados a este equipo y sin airpods-helper (que ocuparía el canal).
"""
import logging
import time
from collections import Counter

from .. import aap
from .. import config as config_mod
from .. import keys as keys_mod
from ..audio import RESTORE_FROM, CallGuard, airpods_sink_prefix
from ..i18n import _

log = logging.getLogger("airpodsd")

SRC_AAP = "aap"
RETRY_S = 30


class AapController:
    def __init__(self, daemon):
        self.d = daemon
        self.client = None   # aap_client.AapClient; se crea en manage()
        self._next_try = 0.0
        self.settings: dict = {}
        self.primary_left: bool | None = None
        self.conversation: int | None = None
        self.in_call = False
        self.keys_received: float | None = None   # última respuesta de claves por AAP
        # Paquetes sin interpretar por código de operación (para airpodsctl report).
        self.unknown: Counter[str] = Counter()
        pref = daemon.config.get("conversation_pref")
        suspended = bool(daemon.config.get("conversation_suspended"))
        # Antes solo se guardaba "suspended": si estaba suspendida, el usuario la tenía activada.
        self.call_guard = CallGuard(suspended=suspended, pref=True if pref is None and suspended else pref)

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.connected)

    def state(self, model) -> dict:
        d = self.d
        return {"enabled": bool(d.config.get("aap", True)),
                "connected": self.connected,
                # Quién tiene el canal AAP: nosotros, airpods-helper o nadie.
                "owner": "airpodsd" if self.connected
                else ("airpods-helper" if d.ears.helper_active() else None),
                "settings": self.settings,
                "modes": aap.listening_modes(model),
                "conversation": self.conversation,
                "conversation_duck": bool(d.config.get("conversation_duck", True)),
                "in_call": self.in_call,
                "keys_received": self.keys_received,
                "unknown_ops": dict(self.unknown)}

    def request_keys(self) -> bool:
        return self.client is not None and self.client.request_keys()

    def stop(self) -> None:
        if self.client:
            self.client.stop()
            self.client = None

    def manage(self, connected: bool | None) -> None:
        d = self.d
        address = d.airpods_address()
        want = (bool(d.config.get("aap", True)) and connected is True and address is not None
                and not d.ears.helper_active())
        if not want:
            self.stop()
            return
        if self.client and self.client.address != address:
            self.stop()
        if self.client is None:
            from ..aap_client import AapClient
            self.client = AapClient(address, self._on_packet, self._on_state)
        if not self.client.connected and not self.client.connecting and time.time() >= self._next_try:
            self._next_try = time.time() + RETRY_S
            self.client.start()

    def _on_state(self, connected: bool) -> None:
        d = self.d
        d.tracker.aap_active = connected
        self.call_guard.connection_reset()
        d.ears.forget_ble()
        if not connected:
            self.settings = {}
            self.conversation = None
            if d.ducker:
                d.ducker.restore()
        d.changed()

    def _on_packet(self, pkt: bytes) -> None:
        d = self.d
        now = time.time()
        if (bat := aap.parse_battery(pkt)):
            log.debug("AAP: batería %s", bat)
            if bat.primary_left is not None:
                self.primary_left = bat.primary_left
            changed = False
            for field in ("left", "right", "case"):
                changed |= d.store.update(field, getattr(bat, field), SRC_AAP, now)
            if changed:
                d.store.save()
                d.changed()
        elif (ear := aap.parse_ear(pkt)):
            log.debug("AAP: oreja %s", ear)
            self._on_ear(ear)
        elif (setting := aap.parse_setting(pkt)):
            name, value = setting
            if name == "listening_mode":
                self.call_guard.note_mode(self.settings.get(name), value,
                                          self.settings.get("conversational_awareness"), now)
            if self.settings.get(name) != value:
                self.settings[name] = value
                log.info("AAP: %s = %s", name, value)
                d.changed()
        elif (level := aap.parse_conversation(pkt)) is not None:
            self._on_conversation(level)
        elif (found := aap.parse_key_response(pkt)) and aap.KEY_IRK in found and aap.KEY_ENC in found:
            self._on_keys(found)
        else:
            log.debug("AAP: paquete sin interpretar %s", pkt.hex())
            # Solo el código: el contenido puede llevar el número de serie o el nombre.
            if pkt.startswith(aap.HEADER) and len(pkt) >= 6:
                self.unknown[f"0x{pkt[4] | pkt[5] << 8:04x}"] += 1

    def _on_ear(self, ear) -> None:
        # La oreja por AAP es una fuente propia para la pausa (ver ear.py) y además se
        # escribe en el estado para el panel. Mientras dura la conexión AAP los anuncios BLE
        # no tocan la oreja ni cuentan como fuente "BLE" (ver EarController.on_ble).
        d = self.d
        sides = aap.ear_sides(ear, self.primary_left)
        if sides:
            left, right = sides
            values = {"left_in_ear": left == aap.EAR_IN, "right_in_ear": right == aap.EAR_IN,
                      "left_in_case": left == aap.EAR_CASE, "right_in_case": right == aap.EAR_CASE}
            d.ears.changed(values["left_in_ear"], values["right_in_ear"], "AAP",
                           values["left_in_case"], values["right_in_case"])
            # Para el panel: con AAP la oreja va al instante (los anuncios BLE no la tocan).
            now = time.time()
            if any([d.store.update(k, v, SRC_AAP, now) for k, v in values.items()]):
                d.store.save()
                d.changed()
        else:
            # Sin saber qué lado es el primario, a la lógica de pausa le basta el número.
            count = aap.ear_count(ear)
            d.ears.changed(count >= 1, count >= 2, "AAP")

    def call_tick(self) -> bool:
        """Cada 2 s con la conexión AAP: en llamada, la detección de conversación se apaga."""
        d = self.d
        if not self.connected:
            return True
        in_call = bool(d.sinks.mic_in_use())
        if in_call != self.in_call:
            self.in_call = in_call
            log.info("micrófono %s", "en uso: modo llamada" if in_call else "libre: fin del modo llamada")
            if in_call and d.ducker:
                d.ducker.restore()
            d.changed()
        self._guard_conversation(active=False)
        return True

    def _guard_conversation(self, active: bool) -> None:
        """Aplica CallGuard: en llamada la detección de conversación siempre desactivada."""
        config = self.d.config
        send = self.call_guard.tick(self.in_call, self.settings.get("conversational_awareness"), active)
        if send is not None and self._send_setting("conversational_awareness", send):
            log.info("detección de conversación %s", "como la tenías, al colgar" if send else
                     "desactivada: estás en una llamada")
            mode = self.call_guard.mode_to_restore(self.settings.get("listening_mode"), time.time())
            if send is False and mode and self._send_setting("listening_mode", mode):
                log.info("la detección había pasado a sonido ambiente: el modo vuelve a %s", mode)
        saved = (bool(config.get("conversation_suspended")), config.get("conversation_pref"))
        if saved != (self.call_guard.suspended, self.call_guard.pref):
            config["conversation_suspended"] = self.call_guard.suspended
            config["conversation_pref"] = self.call_guard.pref
            config_mod.save(config)

    def _on_conversation(self, level: int) -> None:
        d = self.d
        self.conversation = level
        if self.in_call:
            # Un aviso de conversación en llamada: está activa aunque digan lo contrario.
            if level < RESTORE_FROM:
                self._guard_conversation(active=True)
            return
        if not (d.ducker and d.config.get("conversation_duck", True)):
            return
        address = d.airpods_address()
        prefix = address and airpods_sink_prefix(address)
        sink = next((n for n in d.sinks.names() if prefix and n.startswith(prefix)), None)
        if sink and sink == d.sinks.default():
            d.ducker.on_level(sink, level)
        elif level >= RESTORE_FROM:
            d.ducker.restore()

    def _on_keys(self, found: dict) -> None:
        d = self.d
        new = keys_mod.ProximityKeys(self.client.address, found[aap.KEY_IRK], found[aap.KEY_ENC])
        self.keys_received = time.time()
        if new == d.keys:
            log.debug("AAP: claves de proximidad recibidas, sin cambios")
            d.changed()
            return
        keys_mod.save(new)
        d.keys = d.tracker.keys = new
        d.tracker.reset_cache()
        log.info("AAP: claves de proximidad guardadas para %s", new.address)
        d.changed()

    def set_setting(self, name: str, raw: str) -> str | None:
        """Devuelve un mensaje de error, o None si se envió."""
        setting = aap.SETTINGS.get(name)
        if setting is None:
            return _("ajuste desconocido: {name} (disponibles: {values})").format(name=name, values=", ".join(aap.SETTINGS))
        if not self.connected:
            if self.d.ears.helper_active():
                return _("airpods-helper tiene la conexión AAP: usa airpods-cli o páralo")
            return _("sin conexión AAP con los AirPods (¿están conectados a este equipo?)")
        try:
            value = setting.parse(raw)
            aap.setting_packet(name, value)
        except ValueError as e:
            return f"{name}: {e}"
        if name == "conversational_awareness" and self.in_call:
            self.call_guard.set_pref(value)
            self._guard_conversation(active=False)
            return (_("durante una llamada la detección de conversación está desactivada; al colgar quedará activada")
                    if value else
                    _("durante una llamada la detección de conversación está desactivada; al colgar quedará desactivada"))
        if not self._send_setting(name, value):
            return _("no se pudo enviar el ajuste")
        return None

    def _send_setting(self, name: str, value) -> bool:
        # Algunos ajustes (p. ej. la detección de conversación) los aplican los AirPods sin
        # devolverlos: se da por bueno el valor enviado, y si lo devuelven, manda el suyo.
        if not self.client.send(aap.setting_packet(name, value)):
            return False
        if self.settings.get(name) != value:
            self.settings[name] = value
            self.d.changed()
        return True
