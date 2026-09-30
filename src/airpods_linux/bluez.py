"""Consultas a BlueZ sobre los AirPods emparejados (sin depender de las claves)."""
import re

from .proximity import MODEL_NAMES


def modalias_product(modalias: str) -> int | None:
    """bluetooth:v004Cp2027d215C -> 0x2027 (solo dispositivos Apple)."""
    m = re.match(r"bluetooth:v004Cp([0-9A-Fa-f]{4})", modalias or "")
    return int(m.group(1), 16) if m else None


def select_airpods(devices: list[dict]) -> tuple[dict | None, list[dict]]:
    """De los dispositivos emparejados, los que son AirPods conocidos.
    Devuelve (elegido, candidatos); elegido es None si no hay ninguno o hay varios."""
    candidates = [d for d in devices if d.get("paired") and modalias_product(d.get("modalias")) in MODEL_NAMES]
    return (candidates[0] if len(candidates) == 1 else None), candidates


def paired_devices() -> list[dict]:
    import dbus
    bus = dbus.SystemBus()
    om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    out = []
    for ifaces in om.GetManagedObjects().values():
        d = ifaces.get("org.bluez.Device1")
        if d:
            out.append({"address": str(d["Address"]), "name": str(d.get("Alias", d.get("Name", ""))),
                        "paired": bool(d.get("Paired")), "modalias": str(d.get("Modalias", ""))})
    return out
