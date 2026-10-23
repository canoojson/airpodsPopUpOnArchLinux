"""tools/btsnoop_adverts.py: lectura de capturas de btmon con un fichero sintético."""
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "btsnoop_adverts", Path(__file__).resolve().parent.parent / "tools" / "btsnoop_adverts.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

CASE = bytes.fromhex("0711") + bytes(range(17))   # anuncio corto de la caja (datos sin 4C 00)


def record(ts: float, pkt: bytes, opcode: int = bt.MONITOR_EVENT) -> bytes:
    us = int(ts * 1e6) + bt.EPOCH_DELTA_US
    return struct.pack(">IIIIq", len(pkt), len(pkt), opcode, 0, us) + pkt


def adv_event(addr: str, payload: bytes, rssi: int = -50) -> bytes:
    ad = bytes([len(payload) + 3, 0xFF, 0x4C, 0x00]) + payload
    body = bytes([1, 0x00, 0x01]) + bytes(reversed(bytes.fromhex(addr.replace(":", "")))) + bytes([len(ad)]) + ad
    body += struct.pack("b", rssi)
    return bytes([bt.LE_META, len(body) + 1, bt.ADV_REPORT]) + body


def snoop(*recs: bytes) -> bytes:
    return bt.BTSNOOP_MAGIC + struct.pack(">II", 1, 2001) + b"".join(recs)


def test_lee_anuncios_y_mide_intervalos():
    data = snoop(record(1000.0, adv_event("CB:C9:60:F3:4E:2C", CASE)),
                 record(1001.0, b"\x01\x02\x03", opcode=2),          # comando: se ignora
                 record(1030.0, adv_event("CB:C9:60:F3:4E:2C", CASE, -60)),
                 record(1100.0, adv_event("CB:C9:60:F3:4E:2C", CASE)))
    found = list(bt.adverts(data))
    assert [(round(t), a, r) for t, a, r, _p in found] == [(1000, "CB:C9:60:F3:4E:2C", -50),
                                                             (1030, "CB:C9:60:F3:4E:2C", -60),
                                                             (1100, "CB:C9:60:F3:4E:2C", -50)]
    assert found[0][3] == CASE
    assert bt.intervals([t for t, *_ in found]) == {"count": 3, "median_s": 50.0, "max_s": 70.0, "gaps_over_60s": 1}


def test_rechaza_lo_que_no_es_btsnoop():
    try:
        list(bt.adverts(b"no soy una captura"))
    except ValueError:
        return
    raise AssertionError("debería rechazarlo")
