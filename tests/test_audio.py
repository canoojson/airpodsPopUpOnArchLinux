from airpods_linux.audio import CONNECT_WAIT_S, AudioRouter, airpods_sink_prefix

AP = "bluez_output.70_AE_2A_E2_8F_60.1"
SPK = "alsa_output.usb-speakers"


class FakeSinks:
    def __init__(self, names, default):
        self.names_, self.default_, self.calls = list(names), default, []

    def names(self):
        return list(self.names_)

    def default(self):
        return self.default_

    def set_default(self, name):
        self.calls.append(name)
        self.default_ = name
        return True


def router(sinks):
    return AudioRouter(sinks, prefix=airpods_sink_prefix("70:ae:2a:e2:8f:60"))


def test_connect_in_case_keeps_previous_output():
    s = FakeSinks([SPK], SPK)
    r = router(s)
    assert r.tick(0, None) is None                  # antes de conectar: recuerda los altavoces
    s.names_.append(AP)
    s.default_ = AP                                 # PipeWire pone los AirPods por defecto
    assert r.tick(1, None) is None                  # aún no se sabe si hay alguno puesto
    assert r.tick(2, 0) == SPK                      # ninguno puesto: vuelve a los altavoces
    assert s.default_ == SPK and s.calls == [SPK]
    assert r.tick(3, 0) is None                     # solo una vez


def test_connect_with_bud_already_in_ear_keeps_airpods():
    s = FakeSinks([SPK], SPK)
    r = router(s)
    r.tick(0, None)
    s.names_.append(AP)
    s.default_ = AP
    assert r.tick(1, 1) is None and s.default_ == AP


def test_putting_a_bud_on_switches_and_removing_last_returns():
    s = FakeSinks([SPK, AP], SPK)
    r = router(s)
    assert r.on_ear_count(0, 1) == AP and s.default_ == AP
    assert r.on_ear_count(1, 2) is None             # el segundo no cambia nada
    assert r.on_ear_count(2, 1) is None             # quitarse uno: sigue en los AirPods
    assert r.on_ear_count(1, 0) == SPK and s.default_ == SPK


def test_manual_choice_is_respected_between_transitions():
    s = FakeSinks([SPK, AP, "hdmi"], SPK)
    r = router(s)
    r.on_ear_count(0, 1)
    s.default_ = "hdmi"                             # el usuario elige HDMI a mano
    assert r.on_ear_count(1, 2) is None and s.default_ == "hdmi"
    assert r.on_ear_count(2, 0) is None             # la salida no son los AirPods: no se toca


def test_unknown_ear_state_times_out_without_switching():
    s = FakeSinks([SPK], SPK)
    r = router(s)
    r.tick(0, None)
    s.names_.append(AP)
    s.default_ = AP
    r.tick(1, None)
    assert r.tick(1 + CONNECT_WAIT_S + 1, None) is None and s.default_ == AP


def test_no_previous_output_known_does_nothing():
    s = FakeSinks([AP], AP)
    r = router(s)
    r.tick(0, None)
    assert r.tick(1, 0) is None and s.calls == []
