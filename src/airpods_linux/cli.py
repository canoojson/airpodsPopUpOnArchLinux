"""airpodsctl: estado de los AirPods desde la terminal."""
import argparse
import json
import logging
import sys
import time

from . import keys as keys_mod
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore

SOURCES = {"ble-enc": "auricular", "ble-case": "caja", "ble-clear": "auricular, sin cifrar"}


def age(ts: float | None, now: float) -> str:
    if ts is None:
        return "nunca"
    s = max(0, int(now - ts))
    if s < 60:
        return f"hace {s} s"
    if s < 3600:
        return f"hace {s // 60} min"
    if s < 86400:
        return f"hace {s // 3600} h {s % 3600 // 60} min"
    return time.strftime("el %d/%m a las %H:%M", time.localtime(ts))


def fmt_battery(f: dict | None) -> str:
    if not f:
        return f"{'--':>5s}   "
    v = f["value"]
    return f"{v['level']:3d} %{'  ⚡' if v['charging'] else '   '}"


def render(store: StateStore, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if not store.fields:
        return "Sin datos todavía. Abre la caja cerca del PC o espera a un anuncio de la caja."
    v = store.value
    model = MODEL_NAMES.get(v("model"), "AirPods")
    lines = [f"{model} · visto {age(store.last_seen(), now)}"]

    def where(side):
        if v(f"{side}_in_ear"):
            return "en la oreja"
        if v(f"{side}_in_case"):
            return "en la caja"
        return "fuera" if v(f"{side}_in_case") is not None else ""

    def stale(f):  # marca los datos que no son de la última observación
        return f"  ({age(f['ts'], now)})" if f and now - f["ts"] > 90 else ""

    for side, name in (("left", "Izquierdo"), ("right", "Derecho")):
        f = store.get(side)
        lines.append(f"  {name:10s}{fmt_battery(f)}  {where(side):12s}{stale(f)}".rstrip())
    f = store.get("case")
    info = [{True: "tapa cerrada", False: "tapa abierta"}.get(v("lid_closed"), "")]
    if v("case_on_charger"):
        info.append("en el cargador")
    lines.append(f"  {'Caja':10s}{fmt_battery(f)}  {' · '.join(i for i in info if i):12s}{stale(f)}".rstrip())
    src = store.get("rssi")
    if src:
        lines.append(f"  Última fuente: {SOURCES.get(src['source'], src['source'])}, RSSI {src['value']} dBm")
    return "\n".join(lines)


def make_scanner(store, keys, **kw):
    try:
        from .scanner import BleScanner, Tracker
    except ImportError as e:
        sys.exit(f"Falta dbus-python o PyGObject: {e}")
    tracker = Tracker(store, keys, **kw)
    try:
        return BleScanner(tracker.handle, window=None), tracker
    except Exception as e:  # sin BlueZ o sin adaptador: seguimos con la caché
        logging.warning("Bluetooth no disponible: %s", e)
        return None, tracker


def cmd_status(args) -> int:
    store = StateStore(STATE_PATH).load()
    keys = keys_mod.load()
    if args.scan > 0:
        scanner, tracker = make_scanner(store, keys)
        if scanner:
            # Termina en cuanto las tres baterías se han observado en este escaneo.
            t0 = time.time()

            def on_own(_kind, _ts):
                if all((f := store.get(k)) and f["ts"] >= t0 for k in ("left", "right", "case")):
                    tracker.on_own = None
                    scanner.quit()
            tracker.on_own = on_own
            scanner.run(duration=args.scan)
    if args.json:
        print(json.dumps({"now": time.time(), "keys": keys is not None, **store.to_dict()}, indent=2))
    else:
        print(render(store))
        if keys is None:
            print("\nSin claves: batería al 10 % y sin datos con la caja cerrada. Ejecuta: airpodsctl keys fetch")
    return 0


def cmd_watch(args) -> int:
    store = StateStore(STATE_PATH).load()
    keys = keys_mod.load()

    def on_change(s):
        if args.json:
            print(json.dumps({"now": time.time(), **s.to_dict()}), flush=True)
        else:
            print(time.strftime("[%H:%M:%S]"), render(s), sep="\n", flush=True)

    scanner, _ = make_scanner(store, keys, on_change=on_change)
    if not scanner:
        return 1
    scanner.window = (args.on, args.off)
    scanner.run()
    return 0


def paired_airpods() -> str | None:
    """Dirección del primer dispositivo emparejado con modalias de Apple."""
    try:
        import dbus
        bus = dbus.SystemBus()
        om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        for ifaces in om.GetManagedObjects().values():
            d = ifaces.get("org.bluez.Device1")
            if d and d.get("Paired") and str(d.get("Modalias", "")).startswith("bluetooth:v004C"):
                return str(d["Address"])
    except Exception:
        pass
    return None


def cmd_keys(args) -> int:
    if args.action == "show":
        k = keys_mod.load()
        print(f"Claves para {k.address} en {keys_mod.KEYS_PATH}" if k else "No hay claves guardadas")
        return 0 if k else 1
    from .aap import AapError, fetch_keys
    address = args.address or paired_airpods()
    if not address:
        sys.exit("No encuentro AirPods emparejados; indica la dirección")
    try:
        k = fetch_keys(address)
    except AapError as e:
        sys.exit(f"Error: {e}")
    keys_mod.save(k)
    print(f"Claves de {address} guardadas en {keys_mod.KEYS_PATH} (0600)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsctl")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="estado actual o último conocido")
    p.add_argument("--json", action="store_true")
    p.add_argument("--scan", type=float, default=30,
                   help="segundos máximos escuchando (0 = solo caché). La caja cerrada anuncia cada 10-60 s")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("watch", help="escanea por ventanas y muestra cada cambio")
    p.add_argument("--json", action="store_true")
    p.add_argument("--on", type=float, default=4)
    p.add_argument("--off", type=float, default=8)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("keys", help="claves de proximidad (AAP)")
    p.add_argument("action", choices=["fetch", "show"])
    p.add_argument("address", nargs="?")
    p.set_defaults(func=cmd_keys)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
