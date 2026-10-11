"""La salida de audio sigue a la oreja, como en iOS.

Al abrir la caja los AirPods se conectan solos al último dispositivo, y PipeWire los
pone como salida por defecto aunque sigan en la caja. Aquí:

1. Si se conectan con ningún auricular puesto, se vuelve a la salida que se usaba.
2. Al ponerse el primer auricular, el audio pasa a los AirPods.
3. Al quitarse el último (o guardarlo en la caja), vuelve a la salida anterior.

Solo se actúa en esas transiciones, para no pisar lo que el usuario elija a mano.
Las aplicaciones siguen a la salida por defecto (WirePlumber, linking.follow-default-target).
"""
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

CONNECT_WAIT_S = 15   # tiempo máximo esperando a saber si hay auriculares puestos al conectar


class PactlSinks:
    """Salidas de audio vía pactl (pipewire-pulse)."""

    def available(self) -> bool:
        return shutil.which("pactl") is not None

    def _run(self, *args: str) -> str | None:
        try:
            out = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    def default(self) -> str | None:
        return self._run("get-default-sink") or None

    def names(self) -> list[str]:
        out = self._run("list", "short", "sinks") or ""
        return [line.split("\t")[1] for line in out.splitlines() if "\t" in line]

    def set_default(self, name: str) -> bool:
        return self._run("set-default-sink", name) is not None

    def volume(self, name: str) -> int | None:
        """Volumen (%) del primer canal: 'Volume: front-left: 26214 /  40% / ...'."""
        m = re.search(r"(\d+)%", self._run("get-sink-volume", name) or "")
        return int(m.group(1)) if m else None

    def set_volume(self, name: str, pct: int) -> bool:
        return self._run("set-sink-volume", name, f"{pct}%") is not None

    def _json(self, *args: str):
        try:
            return json.loads(self._run("-f", "json", *args) or "null")
        except ValueError:
            return None

    def mic_in_use(self) -> bool | None:
        """¿Alguna aplicación graba de un micrófono? (llamada, OBS, notas de voz...).
        Las grabaciones de un .monitor (visualizadores, medidores) no cuentan.
        None si pactl no da JSON (pipewire-pulse antiguo)."""
        outputs, sources = self._json("list", "source-outputs"), self._json("list", "sources")
        if not isinstance(outputs, list) or not isinstance(sources, list):
            return None
        return is_recording_mic(outputs, sources)


def is_recording_mic(outputs: list[dict], sources: list[dict]) -> bool:
    monitors = {s.get("index") for s in sources
                if str(s.get("name", "")).endswith(".monitor")
                or (s.get("properties") or {}).get("device.class") == "monitor"}
    return any(not o.get("corked") and o.get("source") not in monitors for o in outputs)


def airpods_sink_prefix(address: str) -> str:
    return "bluez_output." + address.upper().replace(":", "_")


@dataclass
class AudioRouter:
    sinks: object
    prefix: str | None = None          # "bluez_output.70_AE_..." de los AirPods
    last_other: str | None = None      # última salida por defecto que no eran los AirPods
    present: bool = False              # ¿existe la salida de los AirPods?
    pending_since: float | None = None # se acaban de conectar: falta saber si hay alguno puesto

    def _airpods_sink(self, names: list[str]) -> str | None:
        if not self.prefix:
            return None
        return next((n for n in names if n.startswith(self.prefix)), None)

    def _is_airpods(self, name: str | None) -> bool:
        return bool(name and self.prefix and name.startswith(self.prefix))

    def tick(self, now: float, in_ear: int | None) -> str | None:
        """Llamar periódicamente con los AirPods conectados. Devuelve la salida puesta, si cambia algo."""
        names = self.sinks.names()
        default = self.sinks.default()
        if default and not self._is_airpods(default):
            self.last_other = default
        ap = self._airpods_sink(names)
        if ap and not self.present:
            self.pending_since = now          # la salida de los AirPods acaba de aparecer
        self.present = ap is not None
        if self.pending_since is None:
            return None
        if in_ear is None and now - self.pending_since < CONNECT_WAIT_S:
            return None                       # aún no se sabe si hay alguno puesto
        self.pending_since = None
        if in_ear == 0 and self._is_airpods(default) and self.last_other in names:
            self.sinks.set_default(self.last_other)
            log.info("AirPods conectados en la caja: el audio sigue por %s", self.last_other)
            return self.last_other
        return None

    def on_ear_count(self, prev: int | None, new: int | None) -> str | None:
        """Transición del número de auriculares puestos (con los AirPods conectados)."""
        if prev is None or new is None or prev == new:
            return None
        names = self.sinks.names()
        ap = self._airpods_sink(names)
        default = self.sinks.default()
        if default and not self._is_airpods(default):
            self.last_other = default
        if prev == 0 and new >= 1 and ap and default != ap:
            self.pending_since = None
            self.sinks.set_default(ap)
            log.info("auricular puesto: el audio pasa a los AirPods")
            return ap
        if prev >= 1 and new == 0 and self._is_airpods(default) and self.last_other in names:
            self.sinks.set_default(self.last_other)
            log.info("sin auriculares puestos: el audio vuelve a %s", self.last_other)
            return self.last_other
        return None

    def disconnected(self) -> None:
        self.present = False
        self.pending_since = None


CONVERSATION_SWITCH_S = 120   # un cambio a ambiente más antiguo se considera hecho a mano


@dataclass
class CallGuard:
    """En una llamada la detección de conversación salta cada vez que hablas: los AirPods
    pasan a sonido ambiente y bajaría el volumen de la propia llamada. iOS la desactiva
    durante las llamadas; aquí igual, con "micrófono en uso" como señal de llamada.

    Solo se reactiva si la desactivamos nosotros y sigue desactivada al colgar: si el
    usuario la cambia a mano durante la llamada, manda él.
    """
    suspended: bool = False   # la desactivamos nosotros y falta reactivarla
    # Modo anterior si la detección acaba de pasar a sonido ambiente (estabas hablando):
    # al apagarla a mitad de conversación los AirPods se quedan en ambiente.
    switched_from: str | None = None
    switched_at: float | None = None

    def note_mode(self, old: str | None, new: str | None, ca_enabled: bool | None, now: float) -> None:
        if new == "transparency" and old not in (None, "transparency") and ca_enabled:
            self.switched_from, self.switched_at = old, now
        elif new != "transparency":
            self.switched_from = self.switched_at = None

    def mode_to_restore(self, current: str | None, now: float) -> str | None:
        """Al empezar la llamada: modo al que volver si la conversación lo cambió hace poco."""
        prev, at = self.switched_from, self.switched_at
        self.switched_from = self.switched_at = None
        if current == "transparency" and prev and at is not None and now - at <= CONVERSATION_SWITCH_S:
            return prev
        return None

    def tick(self, in_call: bool, ca_enabled: bool | None, talking: bool = False) -> bool | None:
        """Valor a enviar a conversational_awareness, o None si no hay que hacer nada.

        `talking`: los AirPods están en plena conversación. Apagar la detección entonces
        los deja atascados en ese estado (sonido de llamada) hasta reconectarlos: se
        espera a que ellos mismos den la conversación por terminada."""
        if in_call:
            if ca_enabled is True and not self.suspended and not talking:
                self.suspended = True
                return False
            return None
        if self.suspended and ca_enabled is not None:   # sin saber el valor actual, esperar
            self.suspended = False
            return True if ca_enabled is False else None
        return None


# Nivel de conversación (AAP) -> fracción del volumen original. 1-2: hablando,
# 3: dejando de hablar, 6-9: normal (se restaura).
DUCK_LEVELS = {1: 0.3, 2: 0.3, 3: 0.6}
RESTORE_FROM = 6


@dataclass
class VolumeDucker:
    """Baja el volumen de los AirPods mientras hablas, como iOS con "Detección de conversación".

    Los AirPods ya bajan el ANC y suben el ambiente ellos solos; el volumen lo tiene que
    bajar el equipo. Solo se restaura si seguimos en el volumen que pusimos nosotros:
    si el usuario lo cambia a mano mientras tanto, se respeta.
    """
    sinks: object
    original: int | None = None
    sink: str | None = None
    applied: int | None = None

    def on_level(self, sink: str | None, level: int) -> int | None:
        """Devuelve el volumen puesto, si cambia algo."""
        if level >= RESTORE_FROM:
            return self.restore()
        factor = DUCK_LEVELS.get(level)
        if factor is None or not sink:
            return None
        if self.original is None or self.sink != sink:
            current = self.sinks.volume(sink)
            if current is None:
                return None
            self.original, self.sink = current, sink
        target = max(1, round(self.original * factor))
        if target == self.applied:
            return None
        if self.sinks.set_volume(sink, target):
            self.applied = target
            log.info("conversación (nivel %d): volumen %d%% -> %d%%", level, self.original, target)
            return target
        return None

    def restore(self) -> int | None:
        if self.original is None:
            return None
        sink, original, applied = self.sink, self.original, self.applied
        self.original = self.sink = self.applied = None
        if self.sinks.volume(sink) != applied:
            log.info("conversación terminada: el volumen se cambió a mano, no se restaura")
            return None
        if self.sinks.set_volume(sink, original):
            log.info("conversación terminada: volumen restaurado a %d%%", original)
            return original
        return None
