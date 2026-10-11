import json

from airpods_linux.history import (BatteryHistory, SAMPLE_EVERY_S, discharge_run, estimate_minutes,
                                   sample_from, series, summary)
from airpods_linux.proximity import Battery
from airpods_linux.state import StateStore


def store_at(ts, **levels):
    s = StateStore(path=None)
    for k, v in levels.items():
        s.update(k, v if isinstance(v, Battery) else Battery(v, False), "test", ts)
    return s


def test_sample_only_fresh_fields():
    s = store_at(0, case=80)
    s.update("left", Battery(50, True), "test", 1000)
    assert sample_from(s, 1000) == {"ts": 1000, "left": 50, "lc": 1, "right": None, "case": None}
    assert sample_from(store_at(0, left=10), 1000) is None


def test_record_on_change_or_periodically(tmp_path):
    h = BatteryHistory(tmp_path / "h.jsonl")
    assert h.record(store_at(0, left=90), 0)
    assert not h.record(store_at(60, left=90), 60)           # igual y reciente
    assert h.record(store_at(120, left=89), 120)             # cambia
    assert h.record(store_at(120 + SAMPLE_EVERY_S, left=89), 120 + SAMPLE_EVERY_S)  # periódica
    lines = (tmp_path / "h.jsonl").read_text().splitlines()
    assert [json.loads(x)["left"] for x in lines] == [90, 89, 89]
    assert len(BatteryHistory(tmp_path / "h.jsonl").load().samples) == 3


def test_prune_rewrites_file(tmp_path):
    h = BatteryHistory(tmp_path / "h.jsonl")
    for day in range(40):
        h.record(store_at(day * 86400, left=50 + day % 2), day * 86400)
    assert h.prune(39 * 86400, keep_days=30) == 9
    assert len(BatteryHistory(tmp_path / "h.jsonl").load().samples) == 31


def test_load_skips_corrupt_lines(tmp_path):
    p = tmp_path / "h.jsonl"
    p.write_text('{"ts": 1, "left": 5}\nbasura\n{"ts": 2, "left": 4}\n')
    assert len(BatteryHistory(p).load().samples) == 2


def test_series_buckets():
    samples = [{"ts": 0, "left": 100}, {"ts": 10, "left": 90}, {"ts": 35, "left": 50}]
    assert series(samples, "left", 0, 40, 4) == [100, 90, None, 50]
    assert series(samples, "left", 0, 40, 8) == [100, None, 90, None, None, None, None, 50]


def test_discharge_run_stops_at_charge_and_rise():
    samples = [
        {"ts": 0, "left": 40, "lc": 1},
        {"ts": 100, "left": 100},
        {"ts": 200, "left": 98},
        {"ts": 300, "left": None},
        {"ts": 400, "left": 95},
    ]
    assert discharge_run(samples, "left") == [(100, 100), (200, 98), (400, 95)]
    samples.append({"ts": 500, "left": 97})   # sube: empieza otra sesión
    assert discharge_run(samples, "left") == [(500, 97)]


def test_estimate_minutes():
    # 1 % cada 3 min durante una hora: 80 % -> 240 min
    samples = [{"ts": i * 180, "left": 100 - i} for i in range(21)]
    now = samples[-1]["ts"]
    assert estimate_minutes(samples, "left", now) == 240
    assert estimate_minutes(samples, "left", now + 600) == 230
    assert estimate_minutes(samples, "left", now + 3 * 3600) is None   # datos viejos
    assert estimate_minutes(samples[:3], "left", samples[2]["ts"]) is None  # poca base


def test_summary_shape():
    h = BatteryHistory(None)
    for i in range(10):
        h.record(store_at(i * 700, left=100 - i, right=100 - i, case=80), i * 700)
    out = summary(h, 9 * 700 + 1, hours=2, buckets=12)
    assert out["hours"] == 2 and len(out["series"]["left"]) == 12
    assert set(out["remaining_min"]) == {"left", "right"}
