import pytest

from airpods_linux.aap import (EAR_CASE, EAR_IN, EAR_OUT, LISTENING_MODES, SETTINGS, AapEar, ear_count,
                               ear_sides, opcode, parse_battery, parse_conversation, parse_ear,
                               parse_key_response, parse_setting, setting_packet)
from airpods_linux.proximity import Battery

H = "04000400"


def pkt(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr.replace(" ", ""))


def test_opcode_rejects_other_packets():
    assert opcode(pkt(H + "0400")) == 0x04
    assert opcode(pkt("00000400010002")) is None and opcode(b"\x04") is None


def test_battery_three_parts():
    # derecho 100 % descargando, izquierdo 100 % descargando, caja 52 % cargando
    b = parse_battery(pkt(H + "0400 03 0201640201 0401640201 0801340101"))
    assert b.right == Battery(100, False) and b.left == Battery(100, False)
    assert b.case == Battery(52, True)
    assert b.primary_left is False      # el primero del paquete es el derecho


def test_battery_disconnected_and_truncated():
    b = parse_battery(pkt(H + "0400 02 0401330101 0801000401"))
    assert b.left == Battery(51, True) and b.case is None and b.right is None and b.primary_left is True
    # anuncia 3 componentes pero solo llega 1: no se lee fuera del paquete
    assert parse_battery(pkt(H + "0400 03 0401330101")).left == Battery(51, True)
    assert parse_battery(pkt(H + "0400 00")) is None


def test_ear_and_sides():
    e = parse_ear(pkt(H + "0600 00 01"))
    assert e == AapEar(EAR_IN, EAR_OUT) and ear_count(e) == 1
    assert ear_sides(e, primary_left=True) == (EAR_IN, EAR_OUT)
    assert ear_sides(e, primary_left=False) == (EAR_OUT, EAR_IN)
    assert ear_sides(e, None) is None                       # sin saber el lado, no se adivina
    assert ear_sides(AapEar(EAR_CASE, EAR_CASE), None) == (EAR_CASE, EAR_CASE)


@pytest.mark.parametrize("name,value,byte", [
    ("listening_mode", "noise", 0x02), ("listening_mode", "adaptive", 0x04),
    ("conversational_awareness", True, 0x01), ("conversational_awareness", False, 0x02),
    ("adaptive_noise_level", 35, 35), ("mic_mode", "left", 0x02),
])
def test_setting_roundtrip(name, value, byte):
    p = setting_packet(name, value)
    assert p == pkt(H + "0900") + bytes([SETTINGS[name].ident, byte, 0, 0, 0])
    assert parse_setting(p) == (name, value)


def test_setting_validation():
    with pytest.raises(ValueError):
        setting_packet("listening_mode", "loud")
    with pytest.raises(ValueError):
        setting_packet("adaptive_noise_level", 101)
    assert SETTINGS["one_bud_anc"].parse("on") is True
    assert SETTINGS["chime_volume"].parse("40") == 40
    assert set(LISTENING_MODES) == {"off", "noise", "transparency", "adaptive"}


def test_unknown_setting_ignored():
    assert parse_setting(pkt(H + "0900 7f 01 000000")) is None
    assert parse_setting(pkt(H + "0900 0d 09 000000")) is None   # modo desconocido


def test_conversation_level():
    assert parse_conversation(pkt(H + "4b00 0200 01 02")) == 2
    assert parse_conversation(pkt(H + "4b00 02")) is None


def test_key_response():
    irk, enc = bytes(range(16)), bytes(range(16, 32))
    p = pkt(H + "3100 02") + bytes([0x01, 0, 16, 0]) + irk + bytes([0x04, 0, 16, 0]) + enc
    assert parse_key_response(p) == {0x01: irk, 0x04: enc}


def test_listening_modes_by_model():
    from airpods_linux.aap import listening_modes
    assert listening_modes(0x2027) == ["off", "transparency", "adaptive", "noise"]
    assert "adaptive" not in listening_modes(0x200E)
    assert listening_modes(0x2002) == [] and listening_modes(None) == []
