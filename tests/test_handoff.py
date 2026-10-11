from airpods_linux.handoff import CONNECT_COOLDOWN_S, NEARBY_S, HandoffLogic


def test_pause_only_if_audio_was_on_airpods():
    h = HandoffLogic()
    h.note_default_sink(True)
    assert h.on_disconnected() is True
    assert h.on_disconnected() is False        # una sola vez
    h.note_default_sink(False)                 # sonaba por los altavoces
    assert h.on_disconnected() is False


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
