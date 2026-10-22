"""Oreja: pausa al quitarse un auricular y audio que sigue a la oreja.

Fuentes de la oreja (ver ear.py): anuncios BLE, la conexión AAP propia y airpods-helper.
"""
import logging
import time

import dbus

from ..audio import airpods_sink_prefix
from ..ear import PAUSE, RESUME, EarPauseLogic

log = logging.getLogger("airpodsd")

HELPER_BUS = "org.costa.AirPods"   # airpods-helper: detección en oreja al instante (AAP)
HELPER_PATH = "/org/costa/AirPods"


def players(paths) -> str:
    return ", ".join(p.rsplit(".", 1)[-1] for p in paths)


class EarController:
    def __init__(self, daemon):
        self.d = daemon
        self.logic = EarPauseLogic()
        self._helper_ear = {"left": None, "right": None}

    @property
    def count(self) -> int:
        return self.logic.count

    def helper_active(self) -> bool:
        try:
            return bool(self.d.session_bus.name_has_owner(HELPER_BUS))
        except dbus.DBusException:
            return False

    def source(self) -> str:
        if self.d.aap.connected:
            return "aap"
        return "airpods-helper" if self.helper_active() else "ble"

    def watch_helper(self) -> None:
        bus = self.d.session_bus

        def changed(iface, props, _inv):
            if iface != HELPER_BUS:
                return
            if "EarLeft" in props:
                self._helper_ear["left"] = bool(props["EarLeft"])
            if "EarRight" in props:
                self._helper_ear["right"] = bool(props["EarRight"])
            if "EarLeft" in props or "EarRight" in props:
                self.changed(self._helper_ear["left"], self._helper_ear["right"], "airpods-helper")
        bus.add_signal_receiver(changed, "PropertiesChanged", "org.freedesktop.DBus.Properties",
                                HELPER_BUS, HELPER_PATH)
        # airpods-helper es activable por D-Bus: get_object() lo arrancaría aunque el usuario
        # lo haya parado, y entonces ocuparía el canal AAP. Solo se consulta si ya está en marcha.
        if not self.helper_active():
            log.info("detección en oreja: anuncios BLE y AAP propio (airpods-helper no está en marcha)")
            return
        try:
            obj = bus.get_object(HELPER_BUS, HELPER_PATH, introspect=False)
            props = obj.GetAll(HELPER_BUS, dbus_interface="org.freedesktop.DBus.Properties")
            self._helper_ear = {"left": bool(props.get("EarLeft")), "right": bool(props.get("EarRight"))}
            self.logic.update("airpods-helper", self._helper_ear["left"], self._helper_ear["right"],
                              self.d.connected(), time.time())
            log.info("detección en oreja: airpods-helper (instantánea) + anuncios BLE")
        except dbus.DBusException:
            log.info("detección en oreja: anuncios BLE (airpods-helper no está en marcha)")

    def changed(self, left, right, source: str, left_case=None, right_case=None) -> None:
        d = self.d
        prev_count = self.logic.count
        connected = d.connected()
        action = self.logic.update(source, left, right, connected, time.time(), left_case, right_case)
        if connected and d.audio and d.config.get("audio_follow_ear", True):
            d.audio.on_ear_count(prev_count, self.logic.count)
        if action == PAUSE and d.config.get("ear_pause", True):
            paused = d.media.pause_playing()
            log.info("auricular fuera de la oreja (%s): %s", source,
                     f"pausado {players(paused)}" if paused else "nada sonando")
            if not d.config.get("ear_resume", True):
                d.media.forget()
        elif action == RESUME and d.config.get("ear_resume", True) and d.media.paused_by_us:
            resumed = d.media.resume()
            log.info("auricular de vuelta en la oreja o guardado en la caja (%s): reanudado %s", source,
                     players(resumed) or "nada")
        elif action == RESUME:
            d.media.forget()

    def on_ble(self) -> None:
        # Los anuncios BLE cuentan para la pausa: con un auricular en la caja airpods-helper
        # deja de informar de la oreja, y sin AAP son la única fuente. Con nuestra conexión
        # AAP la oreja del estado la escribe AAP: no se pasa como si fuera de BLE.
        if self.d.tracker.aap_active:
            return
        v = self.d.store.value
        self.changed(v("left_in_ear"), v("right_in_ear"), "BLE", v("left_in_case"), v("right_in_case"))

    def forget_ble(self) -> None:
        """Lo último que vio la fuente BLE ya no vale (mientras tanto el estado lo escribía AAP)."""
        self.logic.source_counts.pop("BLE", None)

    def audio_tick(self) -> bool:
        """Cada 2 s con los AirPods conectados: al conectarse en la caja, no robar el audio."""
        d = self.d
        if not d.audio or not d.config.get("audio_follow_ear", True):
            return True
        address = d.airpods_address()
        if not address or d.connected(address) is not True:
            d.audio.disconnected()
            return True
        d.audio.prefix = airpods_sink_prefix(address)
        d.audio.tick(time.time(), self.logic.count)
        return True
