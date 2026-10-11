from airpods_linux.bar import fields, format_text, lowest_pod, waybar


def bat(level, charging=False, ts=100.0):
    return {"value": {"level": level, "charging": charging}, "ts": ts, "source": "test"}


def flag(v, ts=100.0):
    return {"value": v, "ts": ts, "source": "test"}


STATUS = {
    "name": "AirPods de Ana", "connected": True, "last_seen": 100.0,
    "aap": {"settings": {"listening_mode": "noise"}},
    "fields": {"left": bat(80), "right": bat(15), "case": bat(60, True),
               "left_in_ear": flag(True), "right_in_ear": flag(False)},
}


def test_lowest_pod_prefers_pods_in_ear():
    assert lowest_pod(STATUS) == 80
    both_out = {"fields": {**STATUS["fields"], "left_in_ear": flag(False)}}
    assert lowest_pod(both_out) == 15
    assert lowest_pod({"fields": {}}) is None


def test_format_placeholders():
    assert format_text("{left}/{right} · {case}{case_chg} {mode}", STATUS, 100) == "80/15 · 60⚡ Cancelación de ruido"
    assert format_text("{name}: {min}% {nope}", STATUS, 100) == "AirPods de Ana: 80% {nope}"
    assert fields({"fields": {}}, 0)["left"] == "--"


def test_waybar_classes_and_percentage():
    out = waybar(STATUS, now=130)
    assert out["text"] == "80%" and out["percentage"] == 80 and out["alt"] == "connected"
    assert "charging" not in out["class"] and "connected" in out["class"]
    assert "Izquierdo: 80%" in out["tooltip"] and "Caja: 60% ⚡" in out["tooltip"]
    low = {**STATUS, "connected": False, "fields": {**STATUS["fields"], "left_in_ear": flag(False)}}
    out = waybar(low, now=100 + 3600)
    assert out["class"] == ["low", "stale"] and out["alt"] == "stale"


def test_waybar_empty():
    assert waybar(None)["class"] == ["empty"]
    assert waybar({"fields": {}})["text"] == ""
