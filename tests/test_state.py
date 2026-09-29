from airpods_linux.crypto import aes_ecb_encrypt
from airpods_linux.proximity import Battery, decrypt_case, decrypt_pod, parse_pod_advert
from airpods_linux.state import SRC_CASE, SRC_CLEAR, SRC_ENC, StateStore, apply_case, apply_pod

KEY = bytes(range(16))


def adv(header, plain=""):
    return parse_pod_advert(bytes.fromhex(header) + aes_ecb_encrypt(KEY, bytes.fromhex(plain.ljust(32, "0"))))


def case(plain):
    return decrypt_case(bytes.fromhex("071106") + aes_ecb_encrypt(KEY, bytes.fromhex(plain.ljust(32, "0"))), KEY)


def test_unavailable_never_overwrites_last_known():
    s = StateStore(path=None)
    apply_case(s, case("29200055e4e4"), ts=100)
    apply_case(s, case("29200155ffff"), ts=200)          # caja vacía: auriculares sin datos
    assert s.get("left") == {"value": {"level": 100, "charging": True}, "ts": 100, "source": SRC_CASE}
    assert s.value("left_in_case") is False


def test_older_observation_ignored():
    s = StateStore(path=None)
    s.update("case", Battery(94, True), SRC_CASE, ts=200)
    assert not s.update("case", Battery(85, False), SRC_CASE, ts=100)
    assert s.value("case")["level"] == 94


def test_pod_encrypted_preferred_source():
    s = StateStore(path=None)
    a = adv("071901272011aaa8110004", "0464e455")
    apply_pod(s, a, decrypt_pod(a, KEY), rssi=-50, ts=1)
    assert s.get("case")["source"] == SRC_ENC and s.value("case")["level"] == 85
    assert s.value("left_in_case") is True and s.value("right_in_case") is False


def test_pod_without_keys_uses_clear():
    s = StateStore(path=None)
    apply_pod(s, adv("071901272011aaa8110004"), None, ts=1)
    assert s.get("case")["source"] == SRC_CLEAR and s.value("case")["level"] == 80


def test_in_ear_and_case_unknown():
    s = StateStore(path=None)
    apply_case(s, case("29200855e4e4"), ts=1)               # caja cerrada: 85 %
    a = adv("07190127200baa8f110004", "046464ff")           # ambos en oreja, caja no disponible
    apply_pod(s, a, decrypt_pod(a, KEY), ts=2)
    assert s.value("left_in_ear") and s.value("right_in_ear")
    assert s.get("case")["ts"] == 1                          # se conserva la última conocida


def test_persistence_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = StateStore(p)
    apply_case(s, case("292002d5ffff"), rssi=-45, ts=5)
    s.save()
    assert (p.stat().st_mode & 0o777) == 0o600
    t = StateStore(p).load()
    assert t.value("case") == {"level": 85, "charging": True} and t.last_seen() == 5


def test_render_marks_stale_values():
    from airpods_linux.cli import render
    s = StateStore(path=None)
    apply_case(s, case("29200855e4e4"), rssi=-50, ts=1000)
    a = adv("07190127200baa8f110004", "046464ff")
    apply_pod(s, a, decrypt_pod(a, KEY), rssi=-40, ts=1600)
    out = render(s, now=1600)
    assert "visto hace 0 s" in out
    assert " 85 %" in out and "(hace 10 min)" in out      # caja: último valor conocido, marcado como antiguo
    assert out.count("en la oreja") == 2


def test_render_empty():
    from airpods_linux.cli import render
    assert "Sin datos" in render(StateStore(path=None))
