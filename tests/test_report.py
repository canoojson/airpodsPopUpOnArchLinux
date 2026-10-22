"""airpodsctl report: nada que identifique al usuario sale en el informe."""
import json

from airpods_linux import report

SYSTEM = {"os": "Arch Linux", "kernel": "7.2.9", "python": "3.14.7", "bluez": "5.87",
          "audio_server": "PulseAudio (on PipeWire 1.6.0)", "desktop": "Hyprland", "session": "wayland",
          "noctalia": True}
STATE = {
    "keys": True, "connected": True, "address": "70:AE:2A:E2:8F:60", "name": "AirPods Pro de Sergio",
    "ctl": "/home/sergio/.local/bin/airpodsctl", "model_name": "AirPods Pro 3",
    "ear": {"source": "aap"}, "aap": {"owner": "airpodsd", "unknown_ops": {"0x001d": 2}},
    "history": {"series": [1, 2, 3]},
    "fields": {"left": {"value": {"level": 80, "charging": False}, "source": "aap", "ts": 1.0}},
    "log": "visto dev_70_AE_2A_E2_8F_60 en /home/sergio/x",
}
DEVICES = [
    {"address": "70:AE:2A:E2:8F:60", "name": "AirPods Pro de Sergio", "paired": True,
     "modalias": "bluetooth:v004Cp2027d215C"},
    {"address": "11:22:33:44:55:66", "name": "Teclado", "paired": True, "modalias": "usb:v046Dp0000"},
]


def build():
    return report.build(STATE, DEVICES, [{"bytes": "07 19 01 27 20", "len": 27, "count": 3}],
                        SYSTEM, "0.2.0", "script")


def test_sin_mac_nombres_ni_rutas(monkeypatch):
    monkeypatch.setattr(report.Path, "home", lambda: report.Path("/home/sergio"))
    text = json.dumps(build())
    for secret in ("70:AE:2A", "70_AE_2A", "Sergio", "sergio", "11:22:33", "Teclado"):
        assert secret not in text
    assert "XX:XX:XX:XX:XX:XX" in text


def test_conserva_lo_util():
    r = build()
    assert r["paired_apple_devices"] == [{"product": "0x2027", "model": "AirPods Pro 3",
                                          "version": "0x215c", "paired": True}]
    assert r["daemon"]["aap"]["unknown_ops"] == {"0x001d": 2}
    assert "history" not in r["daemon"]
    assert r["daemon"]["fields"]["left"]["value"]["level"] == 80


def test_anuncio_sin_la_parte_cifrada():
    long_adv = bytes([0x07, 0x19]) + bytes(range(9)) + bytes([0xEE] * 16)
    assert report.clear_part(long_adv) == bytes([0x07, 0x19]).hex(" ") + " " + bytes(range(9)).hex(" ")
    assert "ee" not in report.clear_part(long_adv)
    assert report.clear_part(bytes([0x10]) + bytes(26)) is None   # no es de proximidad


def test_render_markdown_sin_daemon():
    r = report.build(None, [], [], SYSTEM, "0.2.0", "dev")
    text = report.render(r)
    assert text.startswith("## Informe de airpods-linux")
    assert "airpodsd:** no está en marcha" in text
    assert "ninguno reconocido" in text
    assert "```json" in text
