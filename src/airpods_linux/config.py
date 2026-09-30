"""Preferencias del usuario en ~/.config/airpods-linux/config.json."""
import json
import os
from pathlib import Path

from .keys import config_dir

CONFIG_PATH = config_dir() / "config.json"
DEFAULTS = {
    "update_check": False,       # comprobar a diario si hay versión nueva (consulta api.github.com)
    "notified_version": None,    # última versión de la que ya se avisó
    "ear_pause": True,           # pausar al quitarse un auricular
    "ear_resume": True,          # reanudar al volver a ponérselo
    "audio_follow_ear": True,    # el audio pasa a los AirPods solo al ponérselos
}
BOOL_KEYS = {"update_check", "ear_pause", "ear_resume", "audio_follow_ear"}


def load(path: Path = CONFIG_PATH) -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(path.read_text()))
    except (OSError, ValueError):
        pass
    return cfg


def exists(path: Path = CONFIG_PATH) -> bool:
    return path.exists()


def save(cfg: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, path)


def parse_value(key: str, raw: str):
    if key in BOOL_KEYS:
        low = raw.strip().lower()
        if low in ("1", "true", "on", "yes", "si", "sí"):
            return True
        if low in ("0", "false", "off", "no"):
            return False
        raise ValueError(f"{key} espera true/false")
    return raw


def set_value(key: str, raw: str, path: Path = CONFIG_PATH) -> dict:
    if key not in DEFAULTS:
        raise KeyError(f"opción desconocida: {key} (disponibles: {', '.join(sorted(BOOL_KEYS))})")
    cfg = load(path)
    cfg[key] = parse_value(key, raw)
    save(cfg, path)
    return cfg
