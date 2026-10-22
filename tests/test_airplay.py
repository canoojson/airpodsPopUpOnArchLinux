"""El iPhone por AirPlay (UxPlay) a la vez que el PC."""
from airpods_linux import airplay

UX = {"index": 42, "corked": False,
      "properties": {"application.name": "GStreamer", "application.process.binary": "uxplay"},
      "volume": {"front-left": {"value_percent": "70%"}, "front-right": {"value_percent": "70%"}}}
SPOTIFY = {"index": 7, "corked": False, "properties": {"application.name": "Spotify"},
           "volume": {"aux0": {"value_percent": "55%"}}}


def test_reconoce_el_flujo_de_uxplay():
    assert airplay.is_uxplay_stream(UX)
    assert not airplay.is_uxplay_stream(SPOTIFY)
    assert airplay.stream_volume(UX) == 70


def test_estado_sonando_con_metadatos():
    mpris = {"PlaybackStatus": "Playing",
             "Metadata": {"xesam:title": "Canción", "xesam:artist": ["Artista"], "uxplay:mode": "audio"}}
    st = airplay.status(True, mpris, [SPOTIFY, UX])
    assert st == {"running": True, "playing": True, "title": "Canción", "artist": "Artista",
                  "mode": "audio", "volume": 70, "stream": 42}


def test_parado_y_sin_titulo_generico():
    mpris = {"PlaybackStatus": "Stopped", "Metadata": {"xesam:title": "AirPlay", "uxplay:mode": "none"}}
    st = airplay.status(True, mpris, [SPOTIFY])
    assert st["playing"] is False and st["title"] is None and st["volume"] is None


def test_sin_uxplay():
    st = airplay.status(False, None, None)
    assert st["running"] is False and st["playing"] is False


def test_nombre_del_receptor(tmp_path):
    rc = tmp_path / "uxplayrc"
    rc.write_text('# opciones\nnh\nn "PC de prueba"\ns 1920x1080\n')
    assert airplay.receiver_name([tmp_path / "no-existe", rc]) == "PC de prueba"
    assert airplay.receiver_name([tmp_path / "no-existe"]) is None


def test_aviso_una_vez_al_dia():
    h = airplay.HintPolicy()
    assert not h.should_hint(0, uxplay_running=False, pc_was_playing=True)
    assert not h.should_hint(0, uxplay_running=True, pc_was_playing=False)
    assert h.should_hint(100, True, True)
    assert not h.should_hint(100 + 3600, True, True)
    assert h.should_hint(100 + airplay.HINT_EVERY_S, True, True)
