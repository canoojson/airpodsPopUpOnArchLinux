"""spawn() lanza procesos sin depender de GLib.spawn_async (roto con GLib 2.90 + PyGObject 3.58)."""
import logging
import time

import pytest

pytest.importorskip("dbus")
pytest.importorskip("gi")
from airpods_linux.daemon import spawn  # noqa: E402


def test_spawn_lanza_el_proceso(tmp_path):
    marker = tmp_path / "ok"
    spawn(["sh", "-c", f"echo hecho > {marker}"])
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text().strip() == "hecho"


def test_spawn_de_un_programa_inexistente_solo_avisa(caplog):
    with caplog.at_level(logging.WARNING):
        spawn(["programa-que-no-existe-airpods"])
    assert "no se pudo lanzar" in caplog.text
