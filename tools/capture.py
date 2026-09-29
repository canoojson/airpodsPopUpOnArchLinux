#!/usr/bin/env python3
"""Fase 0: captura pasiva de anuncios Apple Proximity Pairing (0x004C, tipo 0x07).

Usa la API D-Bus de BlueZ (sin root). Cada anuncio visto se guarda como una
línea JSON en fixtures/<label>.jsonl con timestamp, dirección, RSSI y bytes en
bruto. BlueZ entrega ManufacturerData sin el prefijo 4C 00, así que el byte 0
es el tipo (0x07).

BlueZ solo emite ManufacturerData cuando cambia; con DuplicateData=True sí
emite RSSI en cada anuncio, que usamos para medir intervalos. Para la verdad
absoluta a nivel HCI: `sudo btmon -w captura.btsnoop` en paralelo.

Uso: capture.py --label caja_cerrada --duration 180
"""
import argparse
import json
import sys
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

APPLE = 0x004C
PROXIMITY = 0x07
BATT = lambda n: None if n == 0xF else min(n, 10) * 10


def decode(b: bytes) -> dict:
    """Decodificación tentativa según la tabla de la spec (offsets sin 4C 00)."""
    if len(b) < 11:
        return {}
    status = b[5]
    primary_left = bool(status & 0x20)
    hi, lo = b[6] >> 4, b[6] & 0x0F
    left, right = (lo, hi) if primary_left else (hi, lo)
    return {
        "model": f"0x{b[3]:02x}{b[4]:02x}",
        "status": f"{status:08b}",
        "L": BATT(left), "R": BATT(right), "case": BATT(b[7] >> 4),
        "chg": f"{b[7] & 0x0F:04b}",
        "lid": f"{b[8]:08b}",
        "b9": b[9], "b10": b[10],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--min-rssi", type=int, default=-90)
    ap.add_argument("--all-apple", action="store_true", help="registrar todos los tipos Apple, no solo 0x07")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "fixtures"))
    args = ap.parse_args()

    out = Path(args.out) / f"{args.label}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    adapter_path = next(p for p, i in om.GetManagedObjects().items() if "org.bluez.Adapter1" in i)
    adapter = dbus.Interface(bus.get_object("org.bluez", adapter_path), "org.bluez.Adapter1")

    cache = {}  # path -> {"addr", "mfg", "rssi"}
    t0 = time.time()
    stats = {"events": 0}

    def emit(path, kind):
        d = cache.get(path)
        if not d or d.get("mfg") is None or d.get("rssi") is None:
            return
        raw = d["mfg"]
        if not raw or (raw[0] != PROXIMITY and not args.all_apple) or d["rssi"] < args.min_rssi:
            return
        rec = {
            "t": round(time.time(), 3), "dt": round(time.time() - t0, 3),
            "label": args.label, "addr": d["addr"], "rssi": d["rssi"],
            "event": kind, "hex": raw.hex(),
        }
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        stats["events"] += 1
        dec = decode(raw)
        print(f"{rec['dt']:7.2f}s {d['addr']} {d['rssi']:4d} {kind:4s} {raw.hex()}  "
              f"L={dec.get('L')} R={dec.get('R')} C={dec.get('case')} "
              f"st={dec.get('status')} lid={dec.get('lid')} model={dec.get('model')}", flush=True)

    def update(path, props, kind):
        d = cache.setdefault(path, {"addr": None, "mfg": None, "rssi": None})
        if "Address" in props:
            d["addr"] = str(props["Address"])
        if "RSSI" in props:
            d["rssi"] = int(props["RSSI"])
        if "ManufacturerData" in props:
            md = props["ManufacturerData"]
            if APPLE in md:
                d["mfg"] = bytes(md[APPLE])
                kind = "mfg"
        if d["addr"] is None:
            try:
                d["addr"] = str(bus.get_object("org.bluez", path).Get(
                    "org.bluez.Device1", "Address", dbus_interface="org.freedesktop.DBus.Properties"))
            except dbus.DBusException:
                return
        if "RSSI" in props or "ManufacturerData" in props:
            emit(path, kind)

    def on_added(path, ifaces):
        if "org.bluez.Device1" in ifaces:
            update(str(path), ifaces["org.bluez.Device1"], "new")

    def on_changed(iface, changed, invalidated, path=None):
        if iface == "org.bluez.Device1":
            update(str(path), changed, "rssi")

    for p, i in om.GetManagedObjects().items():
        if "org.bluez.Device1" in i:
            d = i["org.bluez.Device1"]
            cache[str(p)] = {"addr": str(d.get("Address")), "rssi": None,
                             "mfg": bytes(d["ManufacturerData"][APPLE]) if APPLE in d.get("ManufacturerData", {}) else None}

    bus.add_signal_receiver(on_added, "InterfacesAdded", "org.freedesktop.DBus.ObjectManager", "org.bluez")
    bus.add_signal_receiver(on_changed, "PropertiesChanged", "org.freedesktop.DBus.Properties",
                            "org.bluez", path_keyword="path")

    adapter.SetDiscoveryFilter({"Transport": "le", "DuplicateData": dbus.Boolean(True)})
    try:
        adapter.StartDiscovery()
    except dbus.DBusException as e:
        print(f"StartDiscovery: {e}", file=sys.stderr)

    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(args.duration, loop.quit)
    print(f"# capturando '{args.label}' {args.duration}s -> {out}", flush=True)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            adapter.StopDiscovery()
        except dbus.DBusException:
            pass
        fh.close()
        print(f"# fin: {stats['events']} eventos", flush=True)


if __name__ == "__main__":
    main()
