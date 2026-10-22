"""El iPhone y el PC sonando a la vez en los AirPods, a través de UxPlay.

Los AirPods solo reciben audio de un dispositivo. Para oír los dos a la vez, el iPhone
manda su audio por AirPlay al PC (UxPlay como receptor) y el PC lo mezcla con el suyo.
Aquí se lee el estado de UxPlay (MPRIS), se localiza su flujo en PipeWire para ajustar
su volumen aparte del resto, y se decide cuándo recordar que existe esa opción.
"""
from dataclasses import dataclass
from pathlib import Path

UXPLAY_BUS = "org.mpris.MediaPlayer2.uxplay"
HINT_EVERY_S = 24 * 3600


def is_uxplay_stream(stream: dict) -> bool:
    """¿Es de UxPlay este flujo de `pactl -f json list sink-inputs`?"""
    props = stream.get("properties") or {}
    return "uxplay" in " ".join(str(props.get(k, "")) for k in
                                ("application.process.binary", "application.name", "media.name")).lower()


def stream_volume(stream: dict) -> int | None:
    """Volumen (%) del primer canal de un flujo de pactl."""
    for ch in (stream.get("volume") or {}).values():
        try:
            return int(str(ch.get("value_percent", "")).rstrip("%"))
        except ValueError:
            return None
    return None


def receiver_name(rc_paths: list[Path] | None = None) -> str | None:
    """Nombre con el que UxPlay se anuncia en AirPlay (opción `n` de su uxplayrc)."""
    paths = rc_paths if rc_paths is not None else [Path.home() / ".config" / "uxplayrc", Path.home() / ".uxplayrc"]
    for path in paths:
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] in ("n", "-n"):
                return parts[1].strip().strip('"')
    return None


def status(running: bool, mpris: dict | None, streams: list[dict] | None) -> dict:
    """Estado para el panel: UxPlay en marcha, si suena, qué y a qué volumen."""
    mpris = mpris or {}
    meta = mpris.get("Metadata") or {}
    mine = [s for s in streams or [] if is_uxplay_stream(s)]
    artist = meta.get("xesam:artist")
    if isinstance(artist, (list, tuple)):
        artist = ", ".join(str(a) for a in artist) or None
    title = meta.get("xesam:title")
    return {
        "running": running,
        "playing": running and (str(mpris.get("PlaybackStatus")) == "Playing"
                                or any(not s.get("corked") for s in mine)),
        "title": str(title) if title and str(title) != "AirPlay" else None,
        "artist": str(artist) if artist else None,
        "mode": str(meta["uxplay:mode"]) if "uxplay:mode" in meta else None,
        "volume": stream_volume(mine[0]) if mine else None,
        "stream": mine[0].get("index") if mine else None,
    }


@dataclass
class HintPolicy:
    """Recordar lo de AirPlay cuando el iPhone se lleva los AirPods con el PC sonando,
    como mucho una vez al día (que no se convierta en spam)."""
    last: float | None = None

    def should_hint(self, now: float, uxplay_running: bool, pc_was_playing: bool) -> bool:
        if not (uxplay_running and pc_was_playing):
            return False
        if self.last is not None and now - self.last < HINT_EVERY_S:
            return False
        self.last = now
        return True
