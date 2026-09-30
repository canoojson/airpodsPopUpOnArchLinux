import json
from pathlib import Path

import pytest

from airpods_linux import keys as keys_mod
from airpods_linux.crypto import aes_ecb_encrypt, make_rpa, resolves_rpa
from airpods_linux.proximity import (Battery, battery_from_byte, battery_from_nibble,
                                     decrypt_case, decrypt_pod, parse_pod_advert)

FIXTURES = Path(__file__).parent.parent / "fixtures"
TEST_KEY = bytes(range(16))
TEST_IRK = bytes(range(16, 32))

# Cabeceras en claro reales (docs/findings.md). Última parte: 16 bytes cifrados.
HDR_BOTH_IN_CASE_R = "071901272015aab8310004"   # derecho emite, ambos en caja, tapa abierta
HDR_BOTH_IN_CASE_L = "071901272075aab8310004"   # izquierdo emite
HDR_RIGHT_OUT_R = "071901272011aaa8110004"      # derecho fuera, emite el derecho
HDR_RIGHT_OUT_L = "071901272071aa98310004"      # derecho fuera, emite el izquierdo
HDR_BOTH_IN_EAR = "07190127200baa8f110004"
HDR_LID_CLOSED = "071901272075aab83a0004"
HDR_OUT_OF_EAR = "071901272001aa8f110004"


def long_adv(header: str, plain: str, key=TEST_KEY) -> bytes:
    return bytes.fromhex(header) + aes_ecb_encrypt(key, bytes.fromhex(plain.ljust(32, "0")))


def case_adv(plain: str, key=TEST_KEY) -> bytes:
    return bytes.fromhex("071106") + aes_ecb_encrypt(key, bytes.fromhex(plain.ljust(32, "0")))


# --- baterías ---------------------------------------------------------------

@pytest.mark.parametrize("b,expected", [
    (0x55, Battery(85, False)), (0xd5, Battery(85, True)), (0xe4, Battery(100, True)),
    (0x00, Battery(0, False)), (0x7f, None), (0xff, None), (0x65, None),
])
def test_battery_byte(b, expected):
    assert battery_from_byte(b) == expected


@pytest.mark.parametrize("n,expected", [(0, 0), (8, 80), (9, 90), (0xA, 100), (0xE, 100), (0xF, None)])
def test_battery_nibble(n, expected):
    assert battery_from_nibble(n) == expected


# --- anuncio largo en claro ---------------------------------------------------

def test_model_is_little_endian_pro3():
    adv = parse_pod_advert(long_adv(HDR_BOTH_IN_CASE_R, ""))
    assert adv.model == 0x2027 and adv.model_name == "AirPods Pro 3"


def test_case_nibble_is_low_and_flags_high():
    # b8: caja 80 % (iPhone 85 %), ambos auriculares cargando, caja no
    adv = parse_pod_advert(long_adv(HDR_BOTH_IN_CASE_R, ""))
    assert adv.case == Battery(80, False)
    assert adv.left == Battery(100, True) and adv.right == Battery(100, True)
    assert adv.both_in_case and adv.lid_closed is False and adv.lid_open_count == 1


@pytest.mark.parametrize("header", [HDR_RIGHT_OUT_R, HDR_RIGHT_OUT_L])
def test_right_out_charging_flip_by_primary(header):
    # Desde los dos emisores: el izquierdo sigue cargando y el derecho no.
    adv = parse_pod_advert(long_adv(header, ""))
    assert adv.left.charging and not adv.right.charging
    assert adv.one_in_case and not adv.both_in_case


def test_both_in_ear():
    adv = parse_pod_advert(long_adv(HDR_BOTH_IN_EAR, ""))
    assert adv.left_in_ear and adv.right_in_ear
    assert adv.case is None           # 0xF con los dos fuera
    assert adv.lid_closed is None     # sin auriculares en la caja no es fiable


def test_out_of_case_not_in_ear():
    adv = parse_pod_advert(long_adv(HDR_OUT_OF_EAR, ""))
    assert not adv.left_in_ear and not adv.right_in_ear and not adv.one_in_case


def test_lid_closed_bit():
    adv = parse_pod_advert(long_adv(HDR_LID_CLOSED, ""))
    assert adv.lid_closed is True and adv.lid_open_count == 2


@pytest.mark.parametrize("data", [
    b"", bytes.fromhex("0711060000"), bytes.fromhex("071900272015aab8310004") + bytes(16),
    bytes.fromhex("1005") + bytes(25),
])
def test_rejects_other_messages(data):
    assert parse_pod_advert(data) is None


# --- parte cifrada ------------------------------------------------------------

def test_decrypt_pod_right_primary():
    # Real (derecho fuera, emite el derecho): 04 64 e4 55 → R 100 %, L 100 % cargando, caja 85 %
    adv = parse_pod_advert(long_adv(HDR_RIGHT_OUT_R, "0464e455"))
    s = decrypt_pod(adv, TEST_KEY)
    assert s.left == Battery(100, True) and s.right == Battery(100, False) and s.case == Battery(85, False)


def test_decrypt_pod_left_primary():
    adv = parse_pod_advert(long_adv(HDR_RIGHT_OUT_L, "04e46455"))
    s = decrypt_pod(adv, TEST_KEY)
    assert s.left == Battery(100, True) and s.right == Battery(100, False)


def test_decrypt_case_closed():
    c = decrypt_case(case_adv("29200855e4e4000000000000"), TEST_KEY)
    assert c.case == Battery(85, False) and c.left == Battery(100, True)
    assert c.pods_in_case and c.lid_closed


def test_decrypt_case_empty_charging():
    c = decrypt_case(case_adv("292002d5ffff"), TEST_KEY)
    assert c.case == Battery(85, True) and not c.pods_in_case and not c.lid_closed


def test_decrypt_case_wrong_key_rejected():
    assert decrypt_case(case_adv("29200855e4e4"), TEST_KEY[::-1]) is None
    assert decrypt_case(case_adv("29200855e4e4", key=TEST_IRK), TEST_KEY) is None


# --- RPA ----------------------------------------------------------------------

def test_rpa_roundtrip():
    addr = make_rpa(TEST_IRK, bytes.fromhex("5e1ea0"))
    assert resolves_rpa(TEST_IRK, addr)
    assert not resolves_rpa(TEST_KEY, addr)


def test_rpa_rejects_static_address():
    assert not resolves_rpa(TEST_IRK, "C8:09:83:9B:F9:FD")


# --- capturas reales (solo con las claves del usuario, que no están en el repo) ---

real_keys = keys_mod.load()


@pytest.mark.skipif(real_keys is None, reason="sin ~/.config/airpods-linux/keys.json")
def test_real_fixtures_decrypt():
    pods, cases = 0, 0
    for line in (FIXTURES / "5_cerrada_tras_uso.jsonl").read_text().splitlines():
        r = json.loads(line)
        raw = bytes.fromhex(r["hex"])
        adv = parse_pod_advert(raw)
        if adv and resolves_rpa(real_keys.irk, r["addr"]):
            pods += 1
            case = decrypt_pod(adv, real_keys.enc_key).case
            # al principio de la captura aún estaban en la oreja: caja no disponible
            assert case is None if not adv.one_in_case else case.level == 85
        elif (c := decrypt_case(raw, real_keys.enc_key)):
            cases += 1
            assert c.case == Battery(85, False) and c.lid_closed
    assert pods and cases


@pytest.mark.parametrize("flags,closed,charger", [
    ("00", False, False), ("08", True, False), ("01", False, False), ("02", False, True),
    ("03", False, True), ("0a", True, True), ("0b", True, True),
])
def test_case_flags(flags, closed, charger):
    c = decrypt_case(case_adv(f"2920{flags}55e4e4"), TEST_KEY)
    assert (c.lid_closed, c.on_charger) == (closed, charger)


# --- selección de los AirPods emparejados ---------------------------------------

def test_select_airpods_ignores_other_apple_and_unpaired():
    from airpods_linux.bluez import select_airpods
    devices = [
        {"address": "A", "name": "iPhone", "paired": True, "modalias": "bluetooth:v004Cp1234d0001"},
        {"address": "B", "name": "Sony", "paired": True, "modalias": "usb:v054Cp0001"},
        {"address": "C", "name": "AirPods Pro", "paired": True, "modalias": "bluetooth:v004Cp2027d215C"},
        {"address": "D", "name": "AirPods ajenos", "paired": False, "modalias": "bluetooth:v004Cp2014d0001"},
    ]
    chosen, candidates = select_airpods(devices)
    assert chosen["address"] == "C" and len(candidates) == 1


def test_select_airpods_ambiguous():
    from airpods_linux.bluez import select_airpods
    devices = [
        {"address": "C", "name": "Pro 3", "paired": True, "modalias": "bluetooth:v004Cp2027d215C"},
        {"address": "E", "name": "Max", "paired": True, "modalias": "bluetooth:v004Cp201Fd0001"},
    ]
    chosen, candidates = select_airpods(devices)
    assert chosen is None and len(candidates) == 2
