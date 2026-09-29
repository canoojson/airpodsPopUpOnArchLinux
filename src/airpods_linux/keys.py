"""Claves de proximidad (IRK + ENC_KEY) obtenidas por AAP. Nunca van al repo."""
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "airpods-linux"


KEYS_PATH = config_dir() / "keys.json"


@dataclass(frozen=True)
class ProximityKeys:
    address: str
    irk: bytes
    enc_key: bytes


def load(path: Path = KEYS_PATH) -> ProximityKeys | None:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("No se pudo leer %s: %s", path, e)
        return None
    if path.stat().st_mode & 0o077:
        log.warning("%s es legible por otros usuarios; ejecuta chmod 600", path)
    return ProximityKeys(raw["address"], bytes.fromhex(raw["irk"]), bytes.fromhex(raw["enc_key"]))


def save(keys: ProximityKeys, path: Path = KEYS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"address": keys.address, "obtained": time.time(),
                   "irk": keys.irk.hex(), "enc_key": keys.enc_key.hex()}, fh, indent=2)
