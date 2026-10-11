"""Salida para barras de estado (Waybar, Polybar, i3blocks, yambar...).

Trabaja sobre el estado que publica airpodsd (status.json o GetState), o en su defecto
sobre el estado guardado, con los mismos campos ("fields", "last_seen", ...).

Marcadores de --format:
  {left} {right} {case}   nivel de cada parte ("--" si no se sabe)
  {left_chg} ...          "⚡" si está cargando
  {min}                   el auricular más bajo de los puestos (o de los dos)
  {name}                  nombre del dispositivo o modelo
  {mode}                  modo de escucha (con conexión AAP), si no ""
  {ago}                   antigüedad del dato ("ahora", "5 min", ...)
"""
import string
import time

DEFAULT_FORMAT = "{min}%"
LOW = 20
STALE_S = 600
MODE_NAMES = {"off": "Desactivado", "noise": "Cancelación de ruido", "transparency": "Sonido ambiente",
              "adaptive": "Adaptativo"}


def _value(status: dict, name: str):
    f = (status.get("fields") or {}).get(name)
    return f["value"] if f else None


def _level(status: dict, name: str) -> int | None:
    v = _value(status, name)
    return v["level"] if v else None


def lowest_pod(status: dict) -> int | None:
    """Batería más baja de los auriculares puestos; si no hay ninguno puesto, de los dos."""
    for only_in_ear in (True, False):
        levels = [lvl for side in ("left", "right")
                  if (lvl := _level(status, side)) is not None
                  and (not only_in_ear or _value(status, f"{side}_in_ear"))]
        if levels:
            return min(levels)
    return None


def short_age(ts: float | None, now: float) -> str:
    if ts is None:
        return "nunca"
    s = max(0, int(now - ts))
    if s < 60:
        return "ahora"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} d"


def fields(status: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    out = {}
    for part in ("left", "right", "case"):
        v = _value(status, part)
        out[part] = str(v["level"]) if v else "--"
        out[f"{part}_chg"] = "⚡" if v and v["charging"] else ""
    low = lowest_pod(status)
    out["min"] = "--" if low is None else str(low)
    out["name"] = status.get("name") or status.get("model_name") or "AirPods"
    mode = ((status.get("aap") or {}).get("settings") or {}).get("listening_mode")
    out["mode"] = MODE_NAMES.get(mode, "")
    out["ago"] = short_age(status.get("last_seen"), now)
    return out


class _Missing(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def format_text(fmt: str, status: dict, now: float | None = None) -> str:
    # Los marcadores desconocidos se dejan tal cual en lugar de fallar.
    return string.Formatter().vformat(fmt, (), _Missing(fields(status, now)))


def tooltip(status: dict, now: float | None = None) -> str:
    f = fields(status, now)
    lines = [f"{f['name']} · visto {'ahora' if f['ago'] == 'ahora' else 'hace ' + f['ago']}"]
    for part, label in (("left", "Izquierdo"), ("right", "Derecho"), ("case", "Caja")):
        lines.append(f"{label}: {f[part]}%{' ' + f[part + '_chg'] if f[part + '_chg'] else ''}"
                     if f[part] != "--" else f"{label}: --")
    if f["mode"]:
        lines.append(f"Modo: {f['mode']}")
    return "\n".join(lines)


def waybar(status: dict | None, fmt: str = DEFAULT_FORMAT, now: float | None = None) -> dict:
    """Objeto JSON para un módulo custom de Waybar con return-type = json."""
    now = time.time() if now is None else now
    if not status or not status.get("fields"):
        return {"text": "", "tooltip": "AirPods: sin datos", "class": ["empty"], "alt": "empty"}
    low = lowest_pod(status)
    classes = []
    if low is not None and low <= LOW:
        classes.append("low")
    if any(_value(status, p) and _value(status, p)["charging"] for p in ("left", "right")):
        classes.append("charging")
    stale = status.get("last_seen") is None or now - status["last_seen"] > STALE_S
    if stale:
        classes.append("stale")
    if status.get("connected"):
        classes.append("connected")
    out = {"text": format_text(fmt, status, now), "tooltip": tooltip(status, now), "class": classes,
           "alt": "connected" if status.get("connected") else ("stale" if stale else "nearby")}
    if low is not None:
        out["percentage"] = low
    return out
