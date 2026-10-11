"""airpodsd: daemon de usuario. Vigila los anuncios, guarda el estado, lo expone
por D-Bus (bus de sesión) y muestra un popup al abrir la caja con los auriculares dentro.

D-Bus: io.github.AirpodsLinux  /io/github/AirpodsLinux  io.github.AirpodsLinux1
  GetState() -> s (JSON)      StateChanged(s)   CaseOpened(s)   CaseClosed()
  SetSetting(s nombre, s valor)   FetchKeys() -> b   (con la conexión AAP propia)

Con los AirPods conectados y sin airpods-helper, airpodsd abre su propia conexión AAP:
batería al 1 % y oreja al instante, modos de escucha y demás ajustes, y las claves de
proximidad sin tener que ejecutar airpodsctl keys fetch.
"""
import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import Gio, GLib

from . import aap
from . import keys as keys_mod
from . import config as config_mod
from . import history as history_mod
from . import update as update_mod
from .alerts import LowBatteryAlerts, message as alert_message
from .fsutil import atomic_write_text
from .audio import RESTORE_FROM, AudioRouter, CallGuard, PactlSinks, VolumeDucker, airpods_sink_prefix
from .bluez import get_alias, paired_devices, select_airpods
from .ear import PAUSE, RESUME, EarPauseLogic
from .handoff import AUDIO_STATE_NAMES, HandoffLogic
from .media import PLAYER_IFACE, MediaController
from .events import CLOSED, OPENED, CaseEventDetector
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore, runtime_status_path

SRC_AAP = "aap"

log = logging.getLogger("airpodsd")

BUS_NAME = "io.github.AirpodsLinux"
OBJ_PATH = "/io/github/AirpodsLinux"
IFACE = "io.github.AirpodsLinux1"
NOCTALIA_PLUGIN = "canoojson/airpods"
POPUP_PANEL = NOCTALIA_PLUGIN + ":popup"
UPDATE_INTERVAL_S = 24 * 3600
HELPER_BUS = "org.costa.AirPods"   # airpods-helper: detección en oreja al instante (AAP)
HELPER_PATH = "/org/costa/AirPods"
AAP_RETRY_S = 30


class Service(dbus.service.Object):
    def __init__(self, bus, daemon):
        super().__init__(dbus.service.BusName(BUS_NAME, bus), OBJ_PATH)
        self._daemon = daemon

    @dbus.service.method(IFACE, out_signature="s")
    def GetState(self):
        return json.dumps(self._daemon.state())

    @dbus.service.method(IFACE)
    def Reload(self):
        """Relee config.json y el nombre del dispositivo (lo llama airpodsctl config/rename)."""
        self._daemon.reload()

    @dbus.service.method(IFACE)
    def CheckUpdates(self):
        """Busca una versión nueva ya; el resultado aparece en el estado ('update')."""
        self._daemon.check_updates(manual=True)

    @dbus.service.method(IFACE, in_signature="ss")
    def SetSetting(self, name, value):
        """Cambia un ajuste de los AirPods por AAP (ver aap.SETTINGS)."""
        err = self._daemon.set_setting(str(name), str(value))
        if err:
            raise dbus.exceptions.DBusException(err, name=IFACE + ".Error")

    @dbus.service.method(IFACE, out_signature="b")
    def FetchKeys(self):
        """Pide las claves de proximidad por la conexión AAP; se guardan al llegar."""
        return self._daemon.aap is not None and self._daemon.aap.request_keys()

    @dbus.service.signal(IFACE, signature="s")
    def StateChanged(self, state_json):
        pass

    @dbus.service.signal(IFACE, signature="s")
    def CaseOpened(self, state_json):
        pass

    @dbus.service.signal(IFACE)
    def CaseClosed(self):
        pass


def noctalia_running() -> bool:
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as fh:
                    if fh.read().strip() == "noctalia":
                        return True
            except OSError:
                pass
    return False


GRAPHICAL_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP",
                  "DBUS_SESSION_BUS_ADDRESS")


def systemd_user_environment() -> dict[str, str]:
    """Entorno actual del gestor systemd de usuario (la sesión gráfica lo rellena al arrancar)."""
    try:
        mgr = dbus.SessionBus().get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
        env = mgr.Get("org.freedesktop.systemd1.Manager", "Environment",
                      dbus_interface="org.freedesktop.DBus.Properties")
        return dict(str(e).split("=", 1) for e in env if "=" in str(e))
    except dbus.DBusException:
        return {}


def graphical_env(base: dict[str, str] | None = None, manager_env: dict[str, str] | None = None,
                  runtime_dir: str | None = None) -> dict[str, str]:
    """Entorno para lanzar clientes gráficos (noctalia msg, notify-send).

    airpodsd puede arrancar antes que la sesión gráfica (default.target), así que su
    propio entorno no tiene WAYLAND_DISPLAY. Se completa en el momento de lanzar:
    primero con el entorno de systemd, y si no, con el socket de Wayland del runtime dir.
    """
    env = dict(os.environ if base is None else base)
    if not env.get("WAYLAND_DISPLAY"):
        mgr = systemd_user_environment() if manager_env is None else manager_env
        for k in GRAPHICAL_VARS:
            if mgr.get(k) and not env.get(k):
                env[k] = mgr[k]
    if not env.get("WAYLAND_DISPLAY"):
        rt = Path(runtime_dir or env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        sockets = sorted(p.name for p in rt.glob("wayland-*") if not p.name.endswith(".lock") and p.is_socket())
        if sockets:
            env["WAYLAND_DISPLAY"] = sockets[0]
    return env


def spawn(argv: list[str]) -> None:
    env = graphical_env()
    if not env.get("WAYLAND_DISPLAY"):
        log.warning("sin sesión Wayland: no se puede mostrar el popup")
    # GLib.spawn_async con STDOUT_TO_DEV_NULL lanza AssertionError desde GLib 2.90 + PyGObject 3.58.
    # Gio.SubprocessLauncher hace lo mismo y además recoge el proceso hijo al terminar.
    launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    launcher.set_environ([f"{k}={v}" for k, v in env.items()])
    try:
        launcher.spawnv(argv)
    except GLib.Error as e:
        log.warning("no se pudo lanzar %s: %s", argv[0], e.message)


class Popup:
    """Muestra el popup en Noctalia; sin Noctalia, una notificación de escritorio."""

    def __init__(self, mode: str, panel_id: str = POPUP_PANEL):
        self.mode = mode
        self.panel_id = panel_id
        self.open = False
        self._last = None

    def show(self, payload: dict) -> None:
        if self.mode == "none":
            return
        if self.mode in ("auto", "noctalia") and shutil.which("noctalia") and noctalia_running():
            spawn(["noctalia", "msg", "panel-open", self.panel_id, json.dumps(payload)])
            self.open = True
            self._last = self._key(payload)
        elif self.mode in ("auto", "notify") and shutil.which("notify-send"):
            spawn(["notify-send", "-a", "AirPods", "-i", "audio-headphones", "-t", "8000",
                   payload["title"], payload["summary"]])

    @staticmethod
    def _key(payload: dict) -> str:
        # Lo que se ve en el popup, sin timestamps: solo se reenvía si cambia.
        return json.dumps([payload.get("connected"),
                           {k: v["value"] for k, v in payload.get("fields", {}).items() if k != "rssi"}],
                          sort_keys=True)

    def update(self, payload: dict) -> None:
        if self.open and (key := self._key(payload)) != self._last:
            self._last = key
            spawn(["noctalia", "msg", "plugin", self.panel_id, "all", "state", json.dumps(payload)])

    def close(self) -> None:
        if self.open:
            spawn(["noctalia", "msg", "panel-close", self.panel_id])
            self.open = False


def pct(field: dict | None) -> str:
    return f"{field['value']['level']} %" if field else "--"


class Daemon:
    def __init__(self, args):
        self.args = args
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.store = StateStore(STATE_PATH).load()
        self.keys = keys_mod.load()
        if not self.keys:
            log.warning("sin claves de proximidad: batería al 10 %% y sin datos con la caja cerrada "
                        "(airpodsctl keys fetch)")
        self.detector = CaseEventDetector()
        self.popup = Popup(args.popup, args.popup_panel)
        self.popup_timeout = args.popup_timeout
        self._popup_timer = None
        self._refresh_timer = None
        self._last_connected = None
        self.config = config_mod.load()
        self.update_info = {"checked": None, "latest": None, "available": False, "error": None}
        self._checking = False
        self._alias = None
        self.service = Service(dbus.SessionBus(), self)
        self.session_bus = dbus.SessionBus()
        self.ear = EarPauseLogic()
        self.media = MediaController(self.session_bus)
        sinks = PactlSinks()
        self.audio = AudioRouter(sinks) if sinks.available() else None
        self.ducker = VolumeDucker(sinks) if sinks.available() else None
        self.sinks = sinks
        if not self.audio:
            log.warning("pactl no está instalado: el audio no seguirá a la oreja")
        self.alerts = LowBatteryAlerts()
        self.history = history_mod.BatteryHistory().load()
        self.history.prune(time.time())
        # Conexión AAP propia (aap_client); se abre en _manage_aap.
        self.aap = None
        self._aap_next_try = 0.0
        self.aap_settings: dict = {}
        self.aap_primary_left: bool | None = None
        self.conversation: int | None = None
        self.in_call = False
        self.keys_received: float | None = None   # última respuesta de claves por AAP
        pref = self.config.get("conversation_pref")
        suspended = bool(self.config.get("conversation_suspended"))
        # Antes solo se guardaba "suspended": si estaba suspendida, el usuario la tenía activada.
        self.call_guard = CallGuard(suspended=suspended, pref=True if pref is None and suspended else pref)
        self._helper_ear = {"left": None, "right": None}
        self.system_bus = dbus.SystemBus()

        from .scanner import BleScanner, Tracker
        self.tracker = Tracker(self.store, self.keys, on_change=self._on_ble_change, on_own=self._on_own)
        self.scanner = BleScanner(self.tracker.handle, window=(args.on, args.off), passive=not args.no_passive)
        log.info("modo de escaneo: %s", "pasivo (AdvertisementMonitor)" if self.scanner.passive
                 else f"ventanas {args.on}/{args.off} s")
        self._watch_helper()
        self.handoff = HandoffLogic()
        # Conexión y desconexión al instante (el sondeo de _poll_connection va cada 5 s).
        self.system_bus.add_signal_receiver(self._on_bluez_props, "PropertiesChanged",
                                            "org.freedesktop.DBus.Properties", "org.bluez", path_keyword="path")
        # Algo empieza a sonar en este equipo (MPRIS).
        self.session_bus.add_signal_receiver(self._on_mpris_props, "PropertiesChanged",
                                             "org.freedesktop.DBus.Properties", None, "/org/mpris/MediaPlayer2")

    def airpods_address(self) -> str | None:
        """MAC de los AirPods emparejados: la de las claves o, sin claves, la que encuentre BlueZ."""
        if self.keys:
            return self.keys.address
        try:
            chosen, _ = select_airpods(paired_devices())
        except dbus.DBusException:
            return None
        return chosen["address"] if chosen else None

    def connected(self, address: str | None = None) -> bool | None:
        """True/False si los AirPods están emparejados con este equipo; None si no lo están."""
        address = address or self.airpods_address()
        if not address:
            return None
        path = f"{self.scanner.adapter_path}/dev_{address.replace(':', '_')}"
        try:
            return bool(self.system_bus.get_object("org.bluez", path).Get(
                "org.bluez.Device1", "Connected", dbus_interface="org.freedesktop.DBus.Properties"))
        except dbus.DBusException:
            return None

    def state(self) -> dict:
        v = self.store.value
        address = self.airpods_address()
        return {
            "now": time.time(),
            "keys": self.keys is not None,
            "model_name": MODEL_NAMES.get(v("model"), "AirPods"),
            "address": address,
            # None = los AirPods no están emparejados con este equipo (no se pueden conectar)
            "connected": self.connected(address),
            "name": self._device_name(address),
            "version": update_mod.current_version(),
            # Ruta absoluta para que los widgets puedan llamar a airpodsctl sin depender del PATH.
            "ctl": str(Path(sys.argv[0]).resolve().with_name("airpodsctl")),
            "audio": {"follow_ear": bool(self.config.get("audio_follow_ear", True)),
                      "available": self.audio is not None},
            "ear": {"pause": bool(self.config.get("ear_pause", True)),
                    "resume": bool(self.config.get("ear_resume", True)),
                    "source": self._ear_source()},
            "alerts": {"low_battery": bool(self.config.get("low_battery_alert", True))},
            "aap": {"enabled": bool(self.config.get("aap", True)),
                    "connected": bool(self.aap and self.aap.connected),
                    # Quién tiene el canal AAP: nosotros, airpods-helper o nadie.
                    "owner": "airpodsd" if self.aap and self.aap.connected
                    else ("airpods-helper" if self._helper_active() else None),
                    "settings": self.aap_settings,
                    "modes": aap.listening_modes(v("model")),
                    "conversation": self.conversation,
                    "conversation_duck": bool(self.config.get("conversation_duck", True)),
                    "in_call": self.in_call,
                    "keys_received": self.keys_received},
            "history": history_mod.summary(self.history, time.time()),
            "update": {**self.update_info, "enabled": bool(self.config.get("update_check")),
                       "managed": update_mod.managed_install(), "install": update_mod.install_kind()},
            **self.store.to_dict(),
        }

    def _ear_source(self) -> str:
        if self.aap and self.aap.connected:
            return "aap"
        return "airpods-helper" if self._helper_active() else "ble"

    def popup_payload(self) -> dict:
        st = self.state()
        st.pop("history", None)   # el popup no la usa y va por la línea de órdenes de noctalia
        g = self.store.get
        st["title"] = st["name"] or st["model_name"]
        st["summary"] = f"Izquierdo {pct(g('left'))} · Derecho {pct(g('right'))} · Caja {pct(g('case'))}"
        return st

    def write_status(self) -> str:
        data = json.dumps(self.state())
        path = runtime_status_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_text(path, data, mode=0o644)
        except OSError as e:
            log.warning("no se pudo escribir %s: %s", path, e)
        return data

    # --- pausa automática al quitarse un auricular -----------------------------

    def _helper_active(self) -> bool:
        try:
            return bool(self.session_bus.name_has_owner(HELPER_BUS))
        except dbus.DBusException:
            return False

    def _watch_helper(self) -> None:
        def changed(iface, props, _inv):
            if iface != HELPER_BUS:
                return
            if "EarLeft" in props:
                self._helper_ear["left"] = bool(props["EarLeft"])
            if "EarRight" in props:
                self._helper_ear["right"] = bool(props["EarRight"])
            if "EarLeft" in props or "EarRight" in props:
                self._ear_changed(self._helper_ear["left"], self._helper_ear["right"], "airpods-helper")
        self.session_bus.add_signal_receiver(changed, "PropertiesChanged", "org.freedesktop.DBus.Properties",
                                             HELPER_BUS, HELPER_PATH)
        # airpods-helper es activable por D-Bus: get_object() lo arrancaría aunque el usuario
        # lo haya parado, y entonces ocuparía el canal AAP. Solo se consulta si ya está en marcha.
        if not self._helper_active():
            log.info("detección en oreja: anuncios BLE y AAP propio (airpods-helper no está en marcha)")
            return
        try:
            obj = self.session_bus.get_object(HELPER_BUS, HELPER_PATH, introspect=False)
            props = obj.GetAll(HELPER_BUS, dbus_interface="org.freedesktop.DBus.Properties")
            self._helper_ear = {"left": bool(props.get("EarLeft")), "right": bool(props.get("EarRight"))}
            self.ear.update("airpods-helper", self._helper_ear["left"], self._helper_ear["right"],
                            self.connected(), time.time())
            log.info("detección en oreja: airpods-helper (instantánea) + anuncios BLE")
        except dbus.DBusException:
            log.info("detección en oreja: anuncios BLE (airpods-helper no está en marcha)")

    def _ear_changed(self, left, right, source: str, left_case=None, right_case=None) -> None:
        prev_count = self.ear.count
        connected = self.connected()
        action = self.ear.update(source, left, right, connected, time.time(), left_case, right_case)
        if connected and self.audio and self.config.get("audio_follow_ear", True):
            self.audio.on_ear_count(prev_count, self.ear.count)
        if action == PAUSE and self.config.get("ear_pause", True):
            paused = self.media.pause_playing()
            log.info("auricular fuera de la oreja (%s): %s", source,
                     f"pausado {', '.join(p.rsplit('.', 1)[-1] for p in paused)}" if paused else "nada sonando")
            if not self.config.get("ear_resume", True):
                self.media.forget()
        elif action == RESUME and self.config.get("ear_resume", True) and self.media.paused_by_us:
            resumed = self.media.resume()
            log.info("auricular de vuelta en la oreja o guardado en la caja (%s): reanudado %s", source,
                     ", ".join(p.rsplit('.', 1)[-1] for p in resumed) or "nada")
        elif action == RESUME:
            self.media.forget()

    def _on_ble_change(self, _store) -> None:
        state = self.store.value("audio_state")
        if state != getattr(self, "_last_audio_state", None):
            self._last_audio_state = state
            log.info("AirPods (BLE): audio %s (0x%02x)", AUDIO_STATE_NAMES.get(state, "desconocido"), state or 0)
        # Los anuncios BLE cuentan para la pausa: con un auricular en la caja airpods-helper
        # deja de informar de la oreja, y sin AAP son la única fuente. Con nuestra conexión
        # AAP la oreja del estado la escribe AAP: no se pasa como si fuera de BLE.
        if not self.tracker.aap_active:
            self._ear_changed(self.store.value("left_in_ear"), self.store.value("right_in_ear"), "BLE",
                              self.store.value("left_in_case"), self.store.value("right_in_case"))
        self._on_change(self.store)

    def _on_change(self, _store) -> None:
        self._battery_tick()
        self.service.StateChanged(self.write_status())
        self.popup.update(self.popup_payload())

    # --- historial y aviso de batería baja --------------------------------------

    def _battery_tick(self) -> None:
        now = time.time()
        self.history.record(self.store, now)
        alerts = self.alerts.check(self.store, now, self.connected())
        if alerts and self.config.get("low_battery_alert", True):
            title, body, urgent = alert_message(alerts)
            log.info("batería baja: %s", body)
            if shutil.which("notify-send"):
                spawn(["notify-send", "-a", "AirPods", "-i", "battery-caution" if urgent else "battery-low",
                       "-u", "critical" if urgent else "normal", title, body])

    def _audio_tick(self) -> bool:
        """Cada 2 s con los AirPods conectados: al conectarse en la caja, no robar el audio."""
        if not self.audio or not self.config.get("audio_follow_ear", True):
            return True
        address = self.airpods_address()
        if not address or self.connected(address) is not True:
            self.audio.disconnected()
            return True
        self.audio.prefix = airpods_sink_prefix(address)
        self.audio.tick(time.time(), self.ear.count)
        return True

    # --- cambio entre el iPhone y este equipo (handoff.py) ------------------------

    def _handoff_tick(self) -> bool:
        """Cada 2 s: ¿sale el audio de este equipo por los AirPods? Y, si se los llevó otro
        dispositivo con una llamada en marcha aquí, ¿toca devolverlos?"""
        address = self.airpods_address()
        if not address:
            return True
        connected = self.connected(address)
        if connected is True:
            default = self.sinks.default() or ""
            self.handoff.note_default_sink(default.startswith(airpods_sink_prefix(address)))
            return True
        now = time.time()
        f_state = self.store.get("audio_state")
        self.handoff.note_audio_state(f_state["value"] if f_state and now - f_state["ts"] < 60 else None, now)
        f_left, f_right = self.store.get("left_in_ear"), self.store.get("right_in_ear")
        seen = max((f["ts"] for f in (f_left, f_right) if f), default=None)
        in_ear = bool((f_left and f_left["value"]) or (f_right and f_right["value"]))
        if self.handoff.should_return(now, connected, seen, in_ear, self.sinks.audio_active()):
            log.info("el otro dispositivo ha dejado de reproducir y aquí sigue sonando algo: vuelvo a conectar los AirPods")
            self._connect_airpods(address, "al dejar de usarlos el otro dispositivo")
        return True

    def _connect_airpods(self, address: str, why: str) -> None:
        path = f"{self.scanner.adapter_path}/dev_{address.upper().replace(':', '_')}"
        self.system_bus.get_object("org.bluez", path).Connect(
            dbus_interface="org.bluez.Device1", timeout=20,
            reply_handler=lambda: log.info("AirPods conectados a este equipo (%s)", why),
            error_handler=lambda e: log.warning("no se pudo conectar los AirPods: %s", e.get_dbus_message()))

    def _on_bluez_props(self, iface, changed, _invalidated, path=None) -> None:
        address = self.airpods_address()
        if (iface != "org.bluez.Device1" or "Connected" not in changed or not address
                or not str(path).endswith("dev_" + address.upper().replace(":", "_"))):
            return
        if bool(changed["Connected"]):
            log.info("AirPods conectados a este equipo")
            self.handoff.on_connected()
            return
        if self.handoff.on_disconnected(time.time()):
            paused = self.media.pause_playing()
            self.media.forget()   # no se reanuda solo: como en iOS, al volver le das a play
            log.info("AirPods desconectados (¿se los ha llevado otro dispositivo?): %s",
                     f"pausado {', '.join(p.rsplit('.', 1)[-1] for p in paused)}" if paused else "nada sonando")

    def _on_mpris_props(self, iface, changed, _invalidated) -> None:
        if iface != PLAYER_IFACE or str(changed.get("PlaybackStatus", "")) != "Playing":
            return
        f_left, f_right = self.store.get("left_in_ear"), self.store.get("right_in_ear")
        seen = max((f["ts"] for f in (f_left, f_right) if f), default=None)
        in_ear = bool((f_left and f_left["value"]) or (f_right and f_right["value"]))
        address = self.airpods_address()
        if address and self.handoff.should_connect(time.time(), self.connected(address), seen, in_ear):
            log.info("empieza a sonar algo en este equipo con los AirPods puestos: los conecto aquí")
            self._connect_airpods(address, "por reproducción")

    def _poll_connection(self) -> bool:
        # "Conectado a este equipo" no llega por BLE: se consulta a BlueZ periódicamente.
        connected = self.connected()
        if connected != self._last_connected:
            self._last_connected = connected
            self._on_change(self.store)
        self._manage_aap(connected)
        return True

    # --- conexión AAP propia ----------------------------------------------------

    def _manage_aap(self, connected: bool | None) -> None:
        address = self.airpods_address()
        want = (bool(self.config.get("aap", True)) and connected is True and address is not None
                and not self._helper_active())
        if not want:
            if self.aap:
                self.aap.stop()
                self.aap = None
            return
        if self.aap and self.aap.address != address:
            self.aap.stop()
            self.aap = None
        if self.aap is None:
            from .aap_client import AapClient
            self.aap = AapClient(address, self._on_aap_packet, self._on_aap_state)
        if not self.aap.connected and not self.aap.connecting and time.time() >= self._aap_next_try:
            self._aap_next_try = time.time() + AAP_RETRY_S
            self.aap.start()

    def _on_aap_state(self, connected: bool) -> None:
        self.tracker.aap_active = connected
        self.call_guard.connection_reset()
        # Lo último que vio la fuente BLE ya no vale (mientras tanto el estado lo escribía AAP).
        self.ear.source_counts.pop("BLE", None)
        if not connected:
            self.aap_settings = {}
            self.conversation = None
            if self.ducker:
                self.ducker.restore()
        self._on_change(self.store)

    def _on_aap_packet(self, pkt: bytes) -> None:
        now = time.time()
        if (bat := aap.parse_battery(pkt)):
            log.debug("AAP: batería %s", bat)
            if bat.primary_left is not None:
                self.aap_primary_left = bat.primary_left
            changed = False
            for field in ("left", "right", "case"):
                changed |= self.store.update(field, getattr(bat, field), SRC_AAP, now)
            if changed:
                self.store.save()
                self._on_change(self.store)
        elif (ear := aap.parse_ear(pkt)):
            log.debug("AAP: oreja %s", ear)
            self._on_aap_ear(ear)
        elif (setting := aap.parse_setting(pkt)):
            name, value = setting
            if name == "listening_mode":
                self.call_guard.note_mode(self.aap_settings.get(name), value,
                                          self.aap_settings.get("conversational_awareness"), now)
            if self.aap_settings.get(name) != value:
                self.aap_settings[name] = value
                log.info("AAP: %s = %s", name, value)
                self._on_change(self.store)
        elif (level := aap.parse_conversation(pkt)) is not None:
            self._on_conversation(level)
        elif (found := aap.parse_key_response(pkt)) and aap.KEY_IRK in found and aap.KEY_ENC in found:
            self._on_aap_keys(found)
        else:
            log.debug("AAP: paquete sin interpretar %s", pkt.hex())

    def _on_aap_ear(self, ear) -> None:
        # La oreja por AAP es una fuente propia para la pausa (ver ear.py) y además se
        # escribe en el estado para el panel. Mientras dura la conexión AAP los anuncios BLE
        # no tocan la oreja ni cuentan como fuente "BLE" (ver _on_ble_change).
        sides = aap.ear_sides(ear, self.aap_primary_left)
        if sides:
            left, right = sides
            values = {"left_in_ear": left == aap.EAR_IN, "right_in_ear": right == aap.EAR_IN,
                      "left_in_case": left == aap.EAR_CASE, "right_in_case": right == aap.EAR_CASE}
            self._ear_changed(values["left_in_ear"], values["right_in_ear"], "AAP",
                              values["left_in_case"], values["right_in_case"])
            # Para el panel: con AAP la oreja va al instante (los anuncios BLE no la tocan).
            now = time.time()
            if any([self.store.update(k, v, SRC_AAP, now) for k, v in values.items()]):
                self.store.save()
                self._on_change(self.store)
        else:
            # Sin saber qué lado es el primario, a la lógica de pausa le basta el número.
            count = aap.ear_count(ear)
            self._ear_changed(count >= 1, count >= 2, "AAP")

    def _call_tick(self) -> bool:
        """Cada 2 s con la conexión AAP: en llamada, la detección de conversación se apaga."""
        if not (self.aap and self.aap.connected):
            return True
        in_call = bool(self.sinks.mic_in_use())
        if in_call != self.in_call:
            self.in_call = in_call
            log.info("micrófono %s", "en uso: modo llamada" if in_call else "libre: fin del modo llamada")
            if in_call and self.ducker:
                self.ducker.restore()
            self._on_change(self.store)
        self._guard_conversation(active=False)
        return True

    def _guard_conversation(self, active: bool) -> None:
        """Aplica CallGuard: en llamada la detección de conversación siempre desactivada."""
        send = self.call_guard.tick(self.in_call, self.aap_settings.get("conversational_awareness"), active)
        if send is not None and self._send_setting("conversational_awareness", send):
            log.info("detección de conversación %s", "como la tenías, al colgar" if send else
                     "desactivada: estás en una llamada")
            mode = self.call_guard.mode_to_restore(self.aap_settings.get("listening_mode"), time.time())
            if send is False and mode and self._send_setting("listening_mode", mode):
                log.info("la detección había pasado a sonido ambiente: el modo vuelve a %s", mode)
        saved = (bool(self.config.get("conversation_suspended")), self.config.get("conversation_pref"))
        if saved != (self.call_guard.suspended, self.call_guard.pref):
            self.config["conversation_suspended"] = self.call_guard.suspended
            self.config["conversation_pref"] = self.call_guard.pref
            config_mod.save(self.config)

    def _on_conversation(self, level: int) -> None:
        self.conversation = level
        if self.in_call:
            # Un aviso de conversación en llamada: está activa aunque digan lo contrario.
            if level < RESTORE_FROM:
                self._guard_conversation(active=True)
            return
        if not (self.ducker and self.config.get("conversation_duck", True)):
            return
        address = self.airpods_address()
        prefix = address and airpods_sink_prefix(address)
        sink = next((n for n in self.sinks.names() if prefix and n.startswith(prefix)), None)
        if sink and sink == self.sinks.default():
            self.ducker.on_level(sink, level)
        elif level >= RESTORE_FROM:
            self.ducker.restore()

    def _on_aap_keys(self, found: dict) -> None:
        new = keys_mod.ProximityKeys(self.aap.address, found[aap.KEY_IRK], found[aap.KEY_ENC])
        self.keys_received = time.time()
        if new == self.keys:
            log.debug("AAP: claves de proximidad recibidas, sin cambios")
            self._on_change(self.store)
            return
        keys_mod.save(new)
        self.keys = self.tracker.keys = new
        self.tracker.reset_cache()
        log.info("AAP: claves de proximidad guardadas para %s", new.address)
        self._on_change(self.store)

    def set_setting(self, name: str, raw: str) -> str | None:
        """Devuelve un mensaje de error, o None si se envió."""
        setting = aap.SETTINGS.get(name)
        if setting is None:
            return f"ajuste desconocido: {name} (disponibles: {', '.join(aap.SETTINGS)})"
        if not (self.aap and self.aap.connected):
            if self._helper_active():
                return "airpods-helper tiene la conexión AAP: usa airpods-cli o páralo"
            return "sin conexión AAP con los AirPods (¿están conectados a este equipo?)"
        try:
            value = setting.parse(raw)
            aap.setting_packet(name, value)
        except ValueError as e:
            return f"{name}: {e}"
        if name == "conversational_awareness" and self.in_call:
            self.call_guard.set_pref(value)
            self._guard_conversation(active=False)
            return ("durante una llamada la detección de conversación está desactivada; "
                    f"al colgar quedará {'activada' if value else 'desactivada'}")
        if not self._send_setting(name, value):
            return "no se pudo enviar el ajuste"
        return None

    def _send_setting(self, name: str, value) -> bool:
        # Algunos ajustes (p. ej. la detección de conversación) los aplican los AirPods sin
        # devolverlos: se da por bueno el valor enviado, y si lo devuelven, manda el suyo.
        if not self.aap.send(aap.setting_packet(name, value)):
            return False
        if self.aap_settings.get(name) != value:
            self.aap_settings[name] = value
            self._on_change(self.store)
        return True

    def _on_own(self, _kind: str, ts: float) -> None:
        event = self.detector.observe(self.store, ts)
        if event == OPENED:
            log.info("caja abierta con auriculares dentro")
            payload = self.popup_payload()
            log.info("popup: %s", "noctalia" if self.popup.mode != "none" else "desactivado")
            self.service.CaseOpened(json.dumps(payload))
            self.popup.show(payload)
            self._arm_popup_timeout()
        elif event == CLOSED:
            log.info("caja cerrada")
            self.service.CaseClosed()
            self.popup.close()

    def _arm_popup_timeout(self) -> None:
        if self._popup_timer:
            GLib.source_remove(self._popup_timer)
        # Red de seguridad: el panel se cierra solo, pero por si se queda abierto.
        self._popup_timer = GLib.timeout_add_seconds(self.popup_timeout + 2, self._popup_expired)
        if not self._refresh_timer:
            self._refresh_timer = GLib.timeout_add_seconds(1, self._refresh_popup)

    def _refresh_popup(self) -> bool:
        # Refresca también lo que no llega por BLE (p. ej. conectado a este equipo).
        if not self.popup.open:
            self._refresh_timer = None
            return False
        self.popup.update(self.popup_payload())
        return True

    def _popup_expired(self) -> bool:
        self._popup_timer = None
        self.popup.close()
        return False

    def _device_name(self, address: str | None) -> str | None:
        if address and self._alias is None:
            self._alias = get_alias(address) or ""
        return self._alias or None

    def reload(self) -> None:
        was_enabled = self.config.get("update_check")
        self.config = config_mod.load()
        self._alias = None
        log.info("configuración recargada (comprobar actualizaciones: %s)",
                 "sí" if self.config.get("update_check") else "no")
        if self.config.get("update_check") and not was_enabled:
            self.check_updates()
        self._on_change(self.store)

    # --- actualizaciones -------------------------------------------------------

    def _periodic_update_check(self) -> bool:
        if self.config.get("update_check"):
            self.check_updates()
        return True

    def check_updates(self, manual: bool = False) -> None:
        """Consulta GitHub en un hilo (no bloquea el bucle BLE) y avisa una vez por versión."""
        if self._checking:
            return
        self._checking = True

        def worker():
            info = update_mod.check()
            GLib.idle_add(self._update_checked, info, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _update_checked(self, info: dict, manual: bool) -> bool:
        self._checking = False
        self.update_info = {"checked": time.time(), "latest": info["latest"],
                            "available": info["available"], "error": info["error"]}
        if info["error"]:
            log.warning("no se pudo comprobar si hay actualizaciones: %s", info["error"])
        elif info["available"]:
            log.info("versión nueva disponible: %s (instalada %s)", info["latest"], info["current"])
            if not manual and self.config.get("notified_version") != info["latest"]:
                self.config["notified_version"] = info["latest"]
                config_mod.save(self.config)
                if shutil.which("notify-send"):
                    spawn(["notify-send", "-a", "AirPods", "-i", "software-update-available",
                           f"AirPods Linux {info['latest']} disponible",
                           "Actualiza con: airpodsctl update (o desde el ⚙ del panel)"])
        self._on_change(self.store)
        return False

    def _quit(self) -> bool:
        if self.ducker:
            self.ducker.restore()
        if self.aap:
            self.aap.stop()
        self.scanner.quit()
        return False

    def run(self) -> None:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit)
        GLib.timeout_add_seconds(86400, lambda: (self.history.prune(time.time()), True)[1])
        self.write_status()
        GLib.timeout_add_seconds(5, self._poll_connection)
        GLib.timeout_add_seconds(2, self._audio_tick)
        GLib.timeout_add_seconds(2, self._call_tick)
        GLib.timeout_add_seconds(2, self._handoff_tick)
        # Primera comprobación al minuto de arrancar (con la red ya lista) y luego cada día.
        GLib.timeout_add_seconds(60, lambda: (self._periodic_update_check(), False)[1])
        GLib.timeout_add_seconds(UPDATE_INTERVAL_S, self._periodic_update_check)
        self.scanner.run(scan=not self.args.no_ble)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsd")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--popup", choices=["auto", "noctalia", "notify", "none"], default="auto")
    ap.add_argument("--popup-timeout", type=int, default=10)
    ap.add_argument("--popup-panel", default=POPUP_PANEL, help="id del panel de Noctalia para el popup")
    ap.add_argument("--no-passive", action="store_true", help="no usar AdvertisementMonitor")
    ap.add_argument("--no-ble", action="store_true", help="no escanear anuncios BLE (diagnóstico)")
    ap.add_argument("--on", type=float, default=4, help="ventana de escaneo activa (s), sin modo pasivo")
    ap.add_argument("--off", type=float, default=8, help="pausa entre ventanas (s), sin modo pasivo")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        Daemon(args).run()
    except dbus.exceptions.NameExistsException:
        log.error("ya hay otro airpodsd en ejecución")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
