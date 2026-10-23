"""Ecualizador: proceso `pipewire -c` con el filtro delante de la salida de los AirPods (ver ..eq)."""
import ctypes
import json
import logging
import shutil
import signal
import subprocess

from .. import eq
from ..audio import airpods_sink_prefix
from ..fsutil import atomic_write_text
from ..state import runtime_status_path

log = logging.getLogger("airpodsd")

PR_SET_PDEATHSIG = 1


def _die_with_parent() -> None:
    """En el hijo: si airpodsd muere de golpe, el kernel termina también el filtro."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


class EqController:
    def __init__(self, daemon):
        self.d = daemon
        self.proc: subprocess.Popen | None = None
        self.target: str | None = None      # salida de los AirPods a la que va el filtro
        self.applied: list[float] | None = None
        self._node_id: int | None = None
        self.available = shutil.which("pipewire") is not None and shutil.which("pw-cli") is not None
        self.conf_path = runtime_status_path().parent / "eq.conf"

    def gains(self) -> list[float]:
        c = self.d.config
        return eq.gains_for(c.get("eq_preset") or "flat", c.get("eq_gains"))

    def state(self) -> dict:
        c = self.d.config
        return {"available": self.available,
                "enabled": bool(c.get("eq_enabled")),
                "active": self.running,
                "preset": c.get("eq_preset") or "flat",
                "gains": self.gains(),
                "bands": [f for _k, f, _q in eq.BANDS],
                "presets": [[k, label] for k, (label, _g) in eq.PRESETS.items()],
                "range": [eq.GAIN_MIN, eq.GAIN_MAX]}

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _wanted_target(self) -> str | None:
        d = self.d
        if not (self.available and d.config.get("eq_enabled") and d.audio):
            return None
        address = d.airpods_address()
        if not address or d.connected(address) is not True:
            return None
        prefix = airpods_sink_prefix(address)
        return next((n for n in d.sinks.names() if n.startswith(prefix)), None)

    def tick(self) -> bool:
        """Cada 2 s: el filtro solo existe con los AirPods conectados y el ecualizador activado."""
        target = self._wanted_target()
        if self.proc is not None and self.proc.poll() is not None:
            log.warning("el proceso del ecualizador ha terminado (código %s)", self.proc.returncode)
            self.proc = None
            self.target = None
            self.d.changed()
        if target != self.target:
            self.stop()
            if target:
                self._start(target)
        elif self.running and self.gains() != self.applied:
            self._apply_live()
        return True

    def reload(self) -> None:
        """La configuración ha cambiado (airpodsctl eq / panel): aplicar ya."""
        self.tick()

    def _start(self, target: str) -> None:
        gains = self.gains()
        try:
            self.conf_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_text(self.conf_path, eq.render_conf(target, gains))
            self.proc = subprocess.Popen(["pipewire", "-c", str(self.conf_path)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         preexec_fn=_die_with_parent)
        except OSError as e:
            log.warning("no se pudo lanzar el ecualizador: %s", e)
            self.proc = None
            return
        self.target, self.applied, self._node_id = target, gains, None
        log.info("ecualizador activado en %s (%s)", target, self.d.config.get("eq_preset") or "flat")
        self.d.changed()

    def _apply_live(self) -> None:
        gains = self.gains()
        if self._node_id is None:
            try:
                dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout)
                self._node_id = eq.find_node_id(dump)
            except (OSError, ValueError, subprocess.SubprocessError):
                self._node_id = None
        ok = False
        if self._node_id is not None:
            try:
                ok = subprocess.run(["pw-cli", "set-param", str(self._node_id), "Props", eq.props_param(gains)],
                                    capture_output=True, timeout=5).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        if ok:
            self.applied = gains
            log.info("ecualizador: %s", self.d.config.get("eq_preset") or "flat")
        else:
            # Sin el nodo (p. ej. aún arrancando) se relanza con la configuración nueva.
            target = self.target
            self.stop()
            if target:
                self._start(target)
        self.d.changed()

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log.info("ecualizador desactivado")
        was = self.target
        self.proc, self.target, self.applied, self._node_id = None, None, None, None
        if was:
            self.d.changed()
