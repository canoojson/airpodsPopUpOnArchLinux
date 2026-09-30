"""Comprobación de versiones nuevas en GitHub Releases y actualización en el sitio."""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from importlib import metadata
from pathlib import Path

REPO = "canoojson/airpodsPopUpOnArchLinux"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER = f"https://github.com/{REPO}/releases/latest/download/install.sh"


def current_version() -> str:
    try:
        return metadata.version("airpods-linux")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


def latest_release(timeout: float = 10) -> dict:
    """{'version': '0.1.3', 'url': ...}. Lanza OSError si no hay red o GitHub falla."""
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"airpods-linux/{current_version()}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return {"version": data["tag_name"].lstrip("v"), "url": data["html_url"]}


def check(timeout: float = 10) -> dict:
    cur = current_version()
    try:
        rel = latest_release(timeout)
    except (OSError, ValueError, KeyError) as e:
        return {"current": cur, "latest": None, "available": False, "error": str(e)}
    return {"current": cur, "latest": rel["version"], "url": rel["url"],
            "available": is_newer(rel["version"], cur), "error": None}


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "airpods-linux"


def managed_install() -> bool:
    """¿Instalado por install.sh (venv en ~/.local/share/airpods-linux)? Si no, es de desarrollo."""
    try:
        return Path(sys.prefix).resolve() == (data_dir() / "venv").resolve()
    except OSError:
        return False


def run_installer() -> int:
    """Descarga el install.sh de la última release y lo ejecuta en modo actualización."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "install.sh"
        req = urllib.request.Request(INSTALLER, headers={"User-Agent": f"airpods-linux/{current_version()}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            script.write_bytes(resp.read())
        return subprocess.call(["bash", str(script), "--update"])
