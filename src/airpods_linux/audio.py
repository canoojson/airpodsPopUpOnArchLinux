"""La salida de audio sigue a la oreja, como en iOS.

Al abrir la caja los AirPods se conectan solos al último dispositivo, y PipeWire los
pone como salida por defecto aunque sigan en la caja. Aquí:

1. Si se conectan con ningún auricular puesto, se vuelve a la salida que se usaba.
2. Al ponerse el primer auricular, el audio pasa a los AirPods.
3. Al quitarse el último (o guardarlo en la caja), vuelve a la salida anterior.

Solo se actúa en esas transiciones, para no pisar lo que el usuario elija a mano.
Las aplicaciones siguen a la salida por defecto (WirePlumber, linking.follow-default-target).
"""
import logging
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
