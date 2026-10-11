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


# --- detección de conversación -------------------------------------------------

class FakeVolume:
    def __init__(self, vol):
        self.vol, self.calls = vol, []

    def volume(self, _name):
        return self.vol

    def set_volume(self, _name, pct):
        self.calls.append(pct)
        self.vol = pct
        return True


def test_duck_while_speaking_and_restore():
    from airpods_linux.audio import VolumeDucker
    v = FakeVolume(80)
    d = VolumeDucker(v)
    assert d.on_level(AP, 1) == 24          # 30 % del original
    assert d.on_level(AP, 2) is None        # mismo nivel: nada
    assert d.on_level(AP, 3) == 48          # dejando de hablar
    assert d.on_level(AP, 8) == 80          # normal: vuelve al original
    assert d.on_level(AP, 9) is None
    assert v.calls == [24, 48, 80]


def test_duck_does_not_restore_if_user_changed_volume():
    from airpods_linux.audio import VolumeDucker
    v = FakeVolume(50)
    d = VolumeDucker(v)
    d.on_level(AP, 1)
    v.vol = 70                              # el usuario lo sube a mano
    assert d.on_level(AP, 8) is None and v.vol == 70


def test_duck_without_sink_or_unknown_level():
    from airpods_linux.audio import VolumeDucker
    v = FakeVolume(50)
    d = VolumeDucker(v)
    assert d.on_level(None, 1) is None and d.on_level(AP, 4) is None and v.calls == []
    assert d.restore() is None


# --- llamadas -------------------------------------------------------------------

def test_recording_mic_ignores_monitors_and_corked():
    from airpods_linux.audio import is_recording_mic
    sources = [{"index": 474, "name": "bluez_output.X.monitor", "properties": {"device.class": "monitor"}},
               {"index": 298, "name": "easyeffects_source", "properties": {}}]
    spectrum = {"source": 474, "corked": False}          # visualizador de Noctalia
    discord = {"source": 298, "corked": False}
    assert not is_recording_mic([spectrum], sources)
    assert is_recording_mic([spectrum, discord], sources)
    assert not is_recording_mic([{**discord, "corked": True}], sources)


def test_call_guard_suspends_and_restores():
    from airpods_linux.audio import CallGuard
    g = CallGuard()
    assert g.tick(False, True) is None
    assert g.tick(True, True) is False          # empieza la llamada: desactivar
    assert g.tick(True, False) is None          # ya está desactivada
    assert g.tick(False, False) is True         # cuelga: reactivar
    assert g.tick(False, True) is None and not g.suspended


def test_call_guard_respects_manual_changes_and_unknown_state():
    from airpods_linux.audio import CallGuard
    assert CallGuard().tick(True, False) is None            # estaba desactivada: no tocar
    g = CallGuard()
    g.tick(True, True)
    assert g.tick(False, True) is None and not g.suspended  # la activó el usuario durante la llamada
    g = CallGuard(suspended=True)                           # tras reiniciar airpodsd en una llamada
    assert g.tick(False, None) is None and g.suspended      # aún sin conexión AAP: esperar
    assert g.tick(False, False) is True


def test_call_guard_restores_mode_changed_by_conversation():
    from airpods_linux.audio import CallGuard
    g = CallGuard()
    g.note_mode("noise", "transparency", True, 100)        # hablando: la detección pasa a ambiente
    assert g.tick(True, True) is False
    assert g.mode_to_restore("transparency", 101) == "noise"
    assert g.mode_to_restore("transparency", 101) is None  # solo una vez


def test_call_guard_keeps_manual_transparency():
    from airpods_linux.audio import CallGuard
    g = CallGuard()
    g.note_mode("noise", "transparency", False, 100)       # sin detección: lo elegiste tú
    assert g.mode_to_restore("transparency", 101) is None
    g.note_mode("noise", "transparency", True, 100)
    assert g.mode_to_restore("transparency", 100 + 600) is None   # hace mucho: a mano
    g.note_mode("noise", "transparency", True, 100)
    g.note_mode("transparency", "noise", True, 110)        # ya volvió solo
    assert g.mode_to_restore("noise", 111) is None


def test_call_guard_waits_for_conversation_to_end():
    from airpods_linux.audio import CallGuard
    g = CallGuard()
    assert g.tick(True, True, talking=True) is None      # hablando: no se toca aún
    assert not g.suspended
    assert g.tick(True, True, talking=False) is False    # terminó la conversación: ahora sí
