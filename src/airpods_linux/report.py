"""airpodsctl report: informe anonimizado para abrir issues de compatibilidad.

Recoge lo que hace falta para dar soporte a otro modelo o depurar un fallo, sin datos
que identifiquen a nadie: ni direcciones MAC, ni nombres de dispositivos, ni rutas del
usuario, ni la parte cifrada de los anuncios (con las claves se podría seguir a alguien).
"""
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .proximity import MODEL_NAMES, PROXIMITY_TYPE

ISSUES_URL = "https://github.com/canoojson/airpodsPopUpOnArchLinux/issues/new"
# También la forma de las rutas de BlueZ (dev_70_AE_...), donde \b no separa del "_".
MAC_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}([:_-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
MAC_MASK = "XX:XX:XX:XX:XX:XX"
# Claves del estado que identifican al usuario o a su equipo.
PRIVATE_KEYS = {"address", "name", "title", "ctl"}
ENCRYPTED_LEN = 16       # los dos anuncios terminan con 16 bytes cifrados
NEAR_RSSI = -65          # solo anuncios de muy cerca: lo normal es que sean los tuyos


def anonymize(obj, home: str | None = None):
    """Copia sin MAC, nombres ni rutas del usuario (recorre dicts y listas)."""
    home = home if home is not None else str(Path.home())
    if isinstance(obj, dict):
        return {k: anonymize(v, home) for k, v in obj.items() if k not in PRIVATE_KEYS}
    if isinstance(obj, list):
        return [anonymize(v, home) for v in obj]
    if isinstance(obj, str):
        s = MAC_RE.sub(MAC_MASK, obj)
        return s.replace(home, "~") if home and home != "/" else s
    return obj


def clear_part(data: bytes) -> str | None:
    """Bytes en claro de un anuncio de proximidad (sin los 16 cifrados), en hex."""
    if len(data) <= ENCRYPTED_LEN + 2 or data[0] != PROXIMITY_TYPE:
        return None
    return data[:-ENCRYPTED_LEN].hex(" ")


def apple_devices(devices: list[dict]) -> list[dict]:
    """Dispositivos Apple emparejados: producto, modelo y versión del modalias (sin MAC ni nombre)."""
    out = []
    for d in devices:
        m = re.match(r"bluetooth:v004Cp([0-9A-Fa-f]{4})d([0-9A-Fa-f]{4})", d.get("modalias") or "")
        if m:
            product = int(m.group(1), 16)
            out.append({"product": f"0x{product:04x}", "model": MODEL_NAMES.get(product, "desconocido"),
                        "version": f"0x{m.group(2).lower()}", "paired": bool(d.get("paired"))})
    return out


def _run(argv: list[str]) -> str | None:
    if not shutil.which(argv[0]):
        return None
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() or None


def _os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.system()


def system_info() -> dict:
    pactl = _run(["pactl", "info"]) or ""
    server = next((line.split(":", 1)[1].strip() for line in pactl.splitlines()
                   if line.startswith(("Server Name", "Nombre del servidor"))), None)
    return {
        "os": _os_name(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "bluez": (_run(["bluetoothctl", "--version"]) or "").removeprefix("bluetoothctl:").strip() or None,
        "audio_server": server,
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
        "session": os.environ.get("XDG_SESSION_TYPE"),
        "noctalia": shutil.which("noctalia") is not None,
    }


def build(state: dict | None, devices: list[dict], adverts: list[dict], system: dict,
          version: str, install: str) -> dict:
    return anonymize({
        "airpods_linux": {"version": version, "install": install},
        "system": system,
        "paired_apple_devices": apple_devices(devices),
        # El historial no aporta nada para la compatibilidad y ocupa mucho.
        "daemon": {k: v for k, v in state.items() if k != "history"} if state else None,
        "adverts": adverts,
    })


def _yes_no(v) -> str:
    return {True: "sí", False: "no"}.get(v, "no emparejados")


def render(report: dict) -> str:
    """Markdown listo para pegar en un issue."""
    sysinfo = report["system"]
    devs = report["paired_apple_devices"]
    st = report.get("daemon") or {}
    lines = [
        "## Informe de airpods-linux",
        "",
        f"- **airpods-linux** {report['airpods_linux']['version']} ({report['airpods_linux']['install']})",
        f"- **Sistema:** {sysinfo['os']}, kernel {sysinfo['kernel']}, Python {sysinfo['python']}",
        f"- **BlueZ:** {sysinfo['bluez'] or '?'} · **Audio:** {sysinfo['audio_server'] or '?'}",
        f"- **Escritorio:** {sysinfo['desktop'] or '?'} ({sysinfo['session'] or '?'})"
        + (" · Noctalia" if sysinfo["noctalia"] else ""),
    ]
    if devs:
        lines.append("- **AirPods emparejados:** " + ", ".join(
            f"{d['model']} ({d['product']}, versión {d['version']})" for d in devs))
    else:
        lines.append("- **AirPods emparejados:** ninguno reconocido")
    if st:
        aap = st.get("aap") or {}
        lines.append(f"- **airpodsd:** claves {'sí' if st.get('keys') else 'no'}, "
                     f"conectados {_yes_no(st.get('connected'))}, AAP {aap.get('owner') or 'sin conexión'}, "
                     f"oreja por {(st.get('ear') or {}).get('source', '?')}")
    else:
        lines.append("- **airpodsd:** no está en marcha")
    if report["adverts"]:
        n = len(report["adverts"])
        lines.append(f"- **Anuncios capturados:** {n} {'distinto' if n == 1 else 'distintos'} (solo bytes en claro)")
    lines += ["", "<details><summary>Datos completos (anonimizados)</summary>", "",
              "```json", json.dumps(report, indent=2, ensure_ascii=False), "```", "", "</details>"]
    return "\n".join(lines)
