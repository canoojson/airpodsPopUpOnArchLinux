from airpods_linux.alerts import Alert, LowBatteryAlerts, message
from airpods_linux.proximity import Battery
from airpods_linux.state import StateStore


def store_with(ts=100.0, **fields):
    s = StateStore(path=None)
    for k, v in fields.items():
        s.update(k, v, "test", ts)
    return s


def test_alerts_once_per_threshold():
    a = LowBatteryAlerts()
    s = store_with(left=Battery(19, False), left_in_case=False)
    assert a.check(s, 100, True) == [Alert("left", 19, 20)]
    s.update("left", Battery(18, False), "test", 160)
    assert a.check(s, 160, True) == []
    s.update("left", Battery(9, False), "test", 200)
    assert a.check(s, 200, True) == [Alert("left", 9, 10)]
    s.update("left", Battery(8, False), "test", 260)
    assert a.check(s, 260, True) == []


def test_jumping_below_both_thresholds_alerts_once():
    a = LowBatteryAlerts()
    s = store_with(right=Battery(7, False), right_in_case=False)
    assert a.check(s, 100, True) == [Alert("right", 7, 10)]
    assert a.check(s, 101, True) == []


def test_pods_only_when_connected_and_out_of_case():
    a = LowBatteryAlerts()
    s = store_with(left=Battery(15, False), left_in_case=False)
    assert a.check(s, 100, False) == [] and a.check(s, 100, None) == []
    s.update("left_in_case", True, "test", 100)
    assert a.check(s, 100, True) == []


def test_charging_rearms():
    a = LowBatteryAlerts()
    s = store_with(left=Battery(15, False), left_in_case=False)
    assert a.check(s, 100, True)
    s.update("left", Battery(15, True), "test", 110)
    assert a.check(s, 110, True) == []           # cargando: no avisa y se rearma
    s.update("left", Battery(14, False), "test", 120)
    assert a.check(s, 120, True) == [Alert("left", 14, 20)]


def test_rearms_after_recovering_margin():
    a = LowBatteryAlerts()
    s = store_with(case=Battery(20, False))
    assert a.check(s, 100, None) == [Alert("case", 20, 20)]
    s.update("case", Battery(26, False), "test", 110)
    assert a.check(s, 110, None) == []
    s.update("case", Battery(19, False), "test", 120)
    assert a.check(s, 120, None) == [Alert("case", 19, 20)]


def test_stale_data_never_alerts():
    a = LowBatteryAlerts()
    s = store_with(ts=0, case=Battery(5, False))
    assert a.check(s, 1000, True) == []


def test_case_does_not_need_connection_but_not_when_charging():
    a = LowBatteryAlerts()
    assert a.check(store_with(case=Battery(9, True)), 100, None) == []
    assert a.check(store_with(case=Battery(9, False)), 100, None) == [Alert("case", 9, 10)]


def test_message():
    title, body, urgent = message([Alert("left", 18, 20), Alert("right", 9, 10)])
    assert title == "AirPods con batería baja" and body == "Izquierdo 18 % · Derecho 9 %" and urgent
    title, _, urgent = message([Alert("case", 19, 20)])
    assert title.startswith("Caja") and not urgent
    assert message([Alert("left", 18, 20), Alert("case", 19, 20)])[0] == "AirPods y caja con batería baja"
