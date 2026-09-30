from airpods_linux.crypto import aes_ecb_encrypt
from airpods_linux.events import CLOSED, OPENED, CaseEventDetector
from airpods_linux.proximity import decrypt_case, decrypt_pod, parse_pod_advert
from airpods_linux.state import StateStore, apply_case, apply_pod

KEY = bytes(range(16))
BOTH_IN_OPEN = "071901272075aab8320004"    # los dos en la caja, tapa abierta
BOTH_IN_CLOSED = "071901272075aab83a0004"  # tapa cerrada
IN_EAR = "07190127200baa8f110004"


def pod(store, header, ts):
    a = parse_pod_advert(bytes.fromhex(header) + aes_ecb_encrypt(KEY, bytes.fromhex("04e4e455".ljust(32, "0"))))
    apply_pod(store, a, decrypt_pod(a, KEY), ts=ts)


def case(store, flags, pods, ts):
    raw = bytes.fromhex("071106") + aes_ecb_encrypt(KEY, bytes.fromhex(f"2920{flags}55{pods}".ljust(32, "0")))
    apply_case(store, decrypt_case(raw, KEY), ts=ts)


def run(steps):
    s, d, out = StateStore(path=None), CaseEventDetector(), []
    for fn, *args, ts in steps:
        fn(s, *args, ts)
        out.append(d.observe(s, ts))
    return out


def test_open_after_closed_fires_once():
    events = run([
        (case, "08", "e4e4", 0),            # cerrada con auriculares
        (pod, BOTH_IN_OPEN, 10),           # se abre
        (pod, BOTH_IN_OPEN, 11),           # sigue abierta: no repite
        (case, "00", "e4e4", 12),
    ])
    assert events == [None, OPENED, None, None]


def test_close_then_reopen():
    events = run([
        (pod, BOTH_IN_OPEN, 0),
        (pod, BOTH_IN_CLOSED, 5),
        (pod, BOTH_IN_OPEN, 8),
    ])
    assert events == [OPENED, CLOSED, OPENED]


def test_open_empty_case_does_not_fire():
    assert run([(case, "08", "e4e4", 0), (case, "01", "ffff", 5)]) == [None, None]


def test_in_ear_does_not_fire():
    assert run([(pod, IN_EAR, 0), (pod, IN_EAR, 1)]) == [None, None]


def test_long_silence_rearms():
    events = run([
        (pod, BOTH_IN_OPEN, 0),
        (pod, BOTH_IN_OPEN, 500),          # 8 min sin datos: nueva apertura no vista cerrada
    ])
    assert events == [OPENED, OPENED]


def test_stale_lid_value_is_ignored():
    # La tapa "cerrada" de la caja no debe reinterpretarse en una observación posterior sin tapa.
    events = run([(case, "08", "e4e4", 0), (pod, IN_EAR, 5)])
    assert events == [None, None]


# Uno en la caja (cerrada) y otro en la oreja: el de la oreja anuncia "tapa abierta"
# porque no está dentro; antes esto hacía parpadear el popup.
ONE_IN_EAR_OTHER_IN_CLOSED_CASE = "071901272019aa98110004"   # emisor en oreja, fuera de la caja


def test_bud_in_ear_does_not_report_lid():
    a = parse_pod_advert(bytes.fromhex(ONE_IN_EAR_OTHER_IN_CLOSED_CASE) + bytes(16))
    assert a.one_in_case and not a.this_in_case and a.lid_closed is None


def test_no_popup_flapping_with_one_bud_in_ear():
    events = run([
        (case, "08", "e4ff", 0),                        # caja cerrada con un auricular
        (pod, ONE_IN_EAR_OTHER_IN_CLOSED_CASE, 1),      # el de la oreja: no dice nada de la tapa
        (case, "08", "e4ff", 2),
        (pod, ONE_IN_EAR_OTHER_IN_CLOSED_CASE, 3),
    ])
    assert events == [None, None, None, None]
