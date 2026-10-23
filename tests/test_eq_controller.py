"""EqController: el filtro se crea una vez por conexión y todo lo demás va en vivo
(crearlo o quitarlo mueve el audio de las aplicaciones y corta el sonido)."""
import pytest

pytest.importorskip("gi")
from airpods_linux.daemon import eq as eqd  # noqa: E402


class FakeProc:
    started = 0

    def __init__(self, *_a, **_k):
        FakeProc.started += 1
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


class Sinks:
    present = True

    def names(self):
        return ["bluez_output.AA_BB.1"] if self.present else []


class Daemon:
    def __init__(self):
        self.config = {"eq_enabled": True, "eq_preset": "flat"}
        self.audio = True
        self.sinks = Sinks()

    def airpods_address(self):
        return "AA:BB"

    def connected(self, _a=None):
        return True

    def changed(self):
        pass


@pytest.fixture
def ctl(monkeypatch, tmp_path):
    FakeProc.started = 0
    applied = []
    monkeypatch.setattr(eqd.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(eqd, "airpods_sink_prefix", lambda _a: "bluez_output.AA_BB")
    c = eqd.EqController(Daemon())
    c.available = True
    c.conf_path = tmp_path / "eq.conf"
    monkeypatch.setattr(c, "_apply_live", lambda: (applied.append(c._effective()),
                                                    setattr(c, "applied", c._effective())))
    return c, applied


def test_desactivar_y_cambiar_no_relanzan(ctl):
    c, applied = ctl
    c.tick()
    assert FakeProc.started == 1
    c.d.config.update(eq_preset="bass_boost")
    c.reload()
    c.d.config.update(eq_enabled=False)
    c.reload()
    c.d.config.update(eq_enabled=True)
    c.reload()
    assert FakeProc.started == 1                     # siempre el mismo filtro
    assert applied[1] == [0.0] * 10                  # desactivado = plano en vivo
    assert applied[0] == applied[2] and applied[0][0] == 6


def test_sin_activar_no_se_crea_y_se_quita_al_desconectar(ctl):
    c, _ = ctl
    c.d.config["eq_enabled"] = False
    c.tick()
    assert FakeProc.started == 0
    c.d.config["eq_enabled"] = True
    c.tick()
    assert c.running
    c.d.sinks.present = False
    c.tick()
    assert not c.running
