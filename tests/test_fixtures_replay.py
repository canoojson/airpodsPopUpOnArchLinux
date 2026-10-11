"""Reproduce las capturas reales de fixtures/ por el mismo camino que airpodsd
(Tracker -> StateStore -> CaseEventDetector), sin claves: así corre en CI.

Los valores esperados salen de docs/findings.md. Sin claves la batería va al 10 %
(nibbles en claro) y el anuncio cifrado de la caja se ignora.
"""
import json
from pathlib import Path

import pytest

from airpods_linux.events import CLOSED, OPENED, CaseEventDetector
from airpods_linux.tracker import Tracker
from airpods_linux.state import StateStore

FIXTURES = Path(__file__).parent.parent / "fixtures"


def replay(name: str, keys=None):
    store, detector, events = StateStore(path=None), CaseEventDetector(), []
    tracker = Tracker(store, keys, on_own=lambda _kind, ts: events.append(detector.observe(store, ts)))
    for line in (FIXTURES / name).read_text().splitlines():
        r = json.loads(line)
        if r.get("event") == "mfg":
            tracker.handle(r["addr"], r["rssi"], bytes.fromhex(r["hex"]), r["t"])
    return store, [e for e in events if e]


def level(store, field):
    v = store.value(field)
    return v and v["level"]


def test_all_fixtures_parse_without_errors():
    names = sorted(p.name for p in FIXTURES.glob("*.jsonl"))
    assert len(names) >= 10
    for name in names:
        replay(name)


def test_1_open_case_with_pods_inside():
    s, events = replay("1_caja_abierta_dentro.jsonl")
    assert s.value("model") == 0x2027
    assert (level(s, "left"), level(s, "right"), level(s, "case")) == (100, 100, 80)  # iPhone: caja 85 %
    assert s.value("left_in_case") and s.value("right_in_case")
    assert s.value("lid_closed") is False
    assert events == [OPENED]


def test_2_right_pod_out():
    s, events = replay("2_derecho_fuera.jsonl")
    assert s.value("left_in_case") is True and s.value("right_in_case") is False
    assert not s.value("left_in_ear") and not s.value("right_in_ear")
    assert events == []  # el detector ya no ve "ambos dentro" con la tapa leída


def test_3_both_in_ear():
    s, _ = replay("3_ambos_oreja_caja_abierta.jsonl")
    assert s.value("left_in_ear") and s.value("right_in_ear")
    assert s.value("left_in_case") is False and s.value("right_in_case") is False
    # Con los dos fuera la caja no está disponible (nibble 0xF): no se inventa.
    assert s.get("case") is None
    assert s.get("lid_closed") is None  # el bit de tapa de un auricular fuera no vale


@pytest.mark.parametrize("name", ["4_cerrada_reposo.jsonl", "4b_cerrada_otra_habitacion.jsonl"])
def test_4_closed_case_needs_keys(name):
    # Solo hay anuncios cortos de la caja: sin claves no se puede saber nada.
    s, events = replay(name)
    assert s.fields == {} and events == []


def test_5_closed_after_use():
    s, events = replay("5_cerrada_tras_uso.jsonl")
    assert s.value("left_in_case") and s.value("right_in_case")
    assert s.value("lid_closed") is True
    assert events == [OPENED, CLOSED]


def test_6_open_empty_case():
    s, events = replay("6_caja_abierta_vacia.jsonl")
    assert s.value("left_in_case") is False and s.value("right_in_case") is False
    assert s.get("case") is None
    assert events == []  # sin auriculares dentro no hay popup


def test_7_empty_case_plugged_in():
    s, events = replay("7_caja_vacia_enchufar.jsonl")
    assert not s.value("left_in_case") and not s.value("right_in_case")
    assert events == []


def test_8_pods_back_in_and_closed():
    s, events = replay("8_vacia_cargando_tapa_cerrada.jsonl")
    assert s.value("left_in_case") and s.value("right_in_case")
    assert s.value("lid_closed") is True and level(s, "case") == 90
    assert events == [OPENED, CLOSED]


def test_9_close_and_reopen_after_use():
    # Bit 0x20 del byte 8 a cero con los dos dentro (findings §13): la tapa se lee igual.
    s, events = replay("9_cerrar_abrir_tras_uso.jsonl")
    assert (level(s, "left"), level(s, "right"), level(s, "case")) == (60, 70, 90)
    assert s.value("lid_closed") is True
    assert events == [OPENED, CLOSED, OPENED, CLOSED]
