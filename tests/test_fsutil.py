"""Escrituras atómicas concurrentes: daemon y CLI guardan el mismo fichero a la vez."""
import json
import threading

from airpods_linux.fsutil import atomic_write_text
from airpods_linux.state import StateStore


def test_escrituras_simultaneas_no_fallan(tmp_path):
    path = tmp_path / "state.json"
    errors = []

    def writer(n):
        try:
            for i in range(200):
                atomic_write_text(path, json.dumps({"writer": n, "i": i}))
        except Exception as e:  # pragma: no cover - es lo que el test vigila
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert json.loads(path.read_text())["i"] == 199
    assert list(tmp_path.glob("*.tmp")) == []


def test_permisos_privados(tmp_path):
    path = tmp_path / "keys.json"
    atomic_write_text(path, "{}")
    assert path.stat().st_mode & 0o777 == 0o600


def test_statestore_guarda(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save()
    assert json.loads((tmp_path / "state.json").read_text())["fields"] == {}
