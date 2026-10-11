from airpods_linux.handoff import (AUDIO_IDLE, AUDIO_MUSIC, CONNECT_COOLDOWN_S, IDLE_BEFORE_RETURN_S,
                                   NEARBY_S, HandoffLogic)


def test_pause_only_if_audio_was_on_airpods():
    h = HandoffLogic()
    h.note_default_sink(True)
    assert h.on_disconnected(0) is True
    assert h.on_disconnected(0) is False        # una sola vez
    h.note_default_sink(False)                 # sonaba por los altavoces
    assert h.on_disconnected(0) is False


def test_connect_when_playing_with_airpods_nearby_in_ear():
    h = HandoffLogic()
    assert h.should_connect(100, connected=False, seen_ts=95, in_ear=True)


def test_no_connect_when_not_applicable():
    h = HandoffLogic()
    assert not h.should_connect(100, connected=True, seen_ts=95, in_ear=True)    # ya conectados
    assert not h.should_connect(100, connected=None, seen_ts=95, in_ear=True)    # no emparejados
    assert not h.should_connect(100, connected=False, seen_ts=95, in_ear=False)  # en la caja
    assert not h.should_connect(100, connected=False, seen_ts=100 - NEARBY_S - 1, in_ear=True)  # lejos
    assert not h.should_connect(100, connected=False, seen_ts=None, in_ear=True)


def test_connect_cooldown():
    h = HandoffLogic()
    assert h.should_connect(100, False, 99, True)
    assert not h.should_connect(105, False, 104, True)
    assert h.should_connect(100 + CONNECT_COOLDOWN_S, False, 129, True)


def test_return_when_other_device_stops_and_pc_still_has_audio():
    h = HandoffLogic()
    h.note_default_sink(True)
    h.on_disconnected(100)                      # el iPhone se los lleva con la llamada en marcha
    h.note_audio_state(AUDIO_MUSIC, 110)
    assert not h.should_return(110, False, 110, True, pc_audio_active=True)   # el iPhone reproduce
    h.note_audio_state(AUDIO_IDLE, 120)
    assert not h.should_return(121, False, 121, True, True)                   # aún poco en reposo
    assert h.should_return(120 + IDLE_BEFORE_RETURN_S, False, 123, True, True)


def test_no_return_without_pc_audio_or_if_not_left_with_audio():
    h = HandoffLogic()
    h.note_default_sink(True)
    h.on_disconnected(100)
    h.note_audio_state(AUDIO_IDLE, 100)
    assert not h.should_return(110, False, 110, True, pc_audio_active=False)  # el PC ya no suena
    h2 = HandoffLogic()                                                       # sonaba por los altavoces
    h2.on_disconnected(100)
    h2.note_audio_state(AUDIO_IDLE, 100)
    assert not h2.should_return(110, False, 110, True, True)


def test_no_return_after_reconnecting():
    h = HandoffLogic()
    h.note_default_sink(True)
    h.on_disconnected(100)
    h.on_connected()
    h.note_audio_state(AUDIO_IDLE, 100)
    assert not h.should_return(110, False, 110, True, True)
