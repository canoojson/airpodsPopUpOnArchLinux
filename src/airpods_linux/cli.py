"""airpodsctl: estado de los AirPods desde la terminal."""
import argparse
import json
import logging
import re
import sys
import time

from . import keys as keys_mod
from .bluez import modalias_product, paired_devices, select_airpods
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore, runtime_status_path

BUS_NAME, OBJ_PATH, IFACE = "io.github.AirpodsLinux", "/io/github/AirpodsLinux", "io.github.AirpodsLinux1"

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


def daemon_proxy():
    import dbus
    return dbus.Interface(dbus.SessionBus().get_object(BUS_NAME, OBJ_PATH), IFACE)


def daemon_state() -> dict | None:
    """Estado en vivo de airpodsd (D-Bus, o el status.json que publica); None si no está."""
    try:
        return json.loads(str(daemon_proxy().GetState()))
    except Exception:
        pass
    try:
        return json.loads(runtime_status_path().read_text())
    except (OSError, ValueError):
        return None


def bar_state() -> dict:
    """Para las barras: el estado de airpodsd o, si no está en marcha, el guardado."""
    st = daemon_state()
    if st is None:
        st = {"now": time.time(), "keys": keys_mod.load() is not None, **StateStore(STATE_PATH).load().to_dict()}
    return st


def bar_line(args) -> str:
    from . import bar
    st = bar_state()
    if args.waybar:
        return json.dumps(bar.waybar(st, args.format or bar.DEFAULT_FORMAT), ensure_ascii=False)
    return bar.format_text(args.format, st) if st.get("fields") else ""


def cmd_status(args) -> int:
    if args.format or args.waybar:
        if args.scan is None:
            print(bar_line(args))
            return 0
    store = StateStore(STATE_PATH).load()
    keys = keys_mod.load()
    if args.scan is None:
        args.scan = 30
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
    if args.format or args.waybar:
        print(bar_line(args))
    elif args.json:
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


def cmd_monitor(args) -> int:
    """Una línea por cada cambio de estado de airpodsd (para barras con exec continuo)."""
    try:
        import dbus
        import dbus.mainloop.glib
        from gi.repository import GLib
    except ImportError as e:
        sys.exit(f"Falta dbus-python o PyGObject: {e}")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    last = [None]

    def emit(*_a):
        line = bar_line(args)
        if line != last[0]:   # no repetir líneas idénticas
            last[0] = line
            print(line, flush=True)
        return True

    bus.add_signal_receiver(emit, "StateChanged", IFACE, None, OBJ_PATH)
    bus.add_signal_receiver(emit, "NameOwnerChanged", "org.freedesktop.DBus", arg0=BUS_NAME)
    GLib.timeout_add_seconds(30, emit)   # la antigüedad ("stale") cambia aunque no lleguen datos
    emit()
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    return 0


# --- ajustes de los AirPods por AAP ----------------------------------------------

def _aap_info() -> tuple[dict | None, dict]:
    st = daemon_state()
    return st, (st or {}).get("aap") or {}


def _set_setting(name: str, raw: str) -> int:
    from .aap import SETTINGS
    st, info = _aap_info()
    if st is None:
        sys.exit("airpodsd no está en marcha: systemctl --user start airpodsd")
    if info.get("owner") == "airpods-helper":
        if name == "listening_mode":
            import subprocess
            return subprocess.call(["airpods-cli", "anc", raw])
        sys.exit("airpods-helper tiene la conexión AAP: cambia este ajuste con airpods-cli")
    try:
        daemon_proxy().SetSetting(name, raw)
    except Exception as e:
        msg = getattr(e, "get_dbus_message", lambda: str(e))()
        sys.exit(f"No se pudo cambiar: {msg}")
    expected = SETTINGS[name].parse(raw)
    # Los AirPods devuelven el ajuste al aplicarlo; se espera la confirmación un momento.
    for _ in range(15):
        time.sleep(0.2)
        _, info = _aap_info()
        if (info.get("settings") or {}).get(name) == expected:
            print(f"{name} = {_show(expected)}")
            return 0
    print(f"{name}: enviado, sin confirmar (algunos ajustes necesitan un auricular puesto)")
    return 0


def _show(v) -> str:
    return {True: "on", False: "off"}.get(v, str(v)) if isinstance(v, bool) else str(v)


def cmd_mode(args) -> int:
    from .aap import LISTENING_MODES
    if args.mode:
        if args.mode not in LISTENING_MODES:
            sys.exit(f"Modo desconocido; posibles: {', '.join(LISTENING_MODES)}")
        return _set_setting("listening_mode", args.mode)
    st, info = _aap_info()
    mode = (info.get("settings") or {}).get("listening_mode")
    if mode is None:
        if info.get("owner") == "airpods-helper":
            import subprocess
            return subprocess.call(["airpods-cli", "anc"])
        print("Desconocido (sin conexión AAP con los AirPods)")
        return 1
    print(mode)
    return 0


def cmd_feature(args) -> int:
    from .aap import SETTINGS
    if args.name and args.name not in SETTINGS:
        sys.exit(f"Ajuste desconocido; posibles: {', '.join(SETTINGS)}")
    if args.name and args.value is not None:
        return _set_setting(args.name, args.value)
    st, info = _aap_info()
    current = info.get("settings") or {}
    if args.json:
        print(json.dumps(current if not args.name else current.get(args.name)))
        return 0
    if not info.get("connected"):
        owner = info.get("owner")
        print("Sin conexión AAP propia" + (" (la tiene airpods-helper: usa airpods-cli)" if owner else
                                           " (conecta los AirPods a este equipo)"))
    for name, s in SETTINGS.items():
        if args.name and name != args.name:
            continue
        val = _show(current[name]) if name in current else "?"
        values = "/".join(s.values) if s.kind == "enum" else ("on/off" if s.kind == "bool" else "0-100")
        print(f"  {name:26s} {val:13s} {s.label} [{values}]")
    return 0


def cmd_history(args) -> int:
    from . import history
    h = history.BatteryHistory().load()
    now = time.time()
    width = args.width
    start = now - args.hours * 3600
    data = {p: history.series(h.since(start), p, start, now, width) for p in history.PARTS}
    est = {p: history.estimate_minutes(h.since(now - 86400), p, now) for p in ("left", "right")}
    if args.json:
        print(json.dumps({"hours": args.hours, "series": data, "remaining_min": est}))
        return 0
    if not h.samples:
        print("Sin historial todavía: airpodsd lo va guardando mientras recibe datos.")
        return 0
    blocks = "▁▂▃▄▅▆▇█"
    print(f"Últimas {args.hours} h (cada columna ≈ {args.hours * 60 // width} min)")
    for part, label in (("left", "Izquierdo"), ("right", "Derecho"), ("case", "Caja")):
        line = "".join(" " if v is None else blocks[min(7, v * 8 // 101)] for v in data[part])
        last = next((v for v in reversed(data[part]) if v is not None), None)
        print(f"  {label:10s} {line} {'' if last is None else f'{last} %'}")
    for side, label in (("left", "izquierdo"), ("right", "derecho")):
        if est[side] is not None:
            print(f"  Al ritmo actual, al {label} le quedan unas {est[side] // 60} h {est[side] % 60:02d} min")
    return 0


def _fetch_keys_via_daemon() -> bool:
    """Si airpodsd tiene la conexión AAP, le pide las claves (el canal no se puede compartir)."""
    _, info = _aap_info()
    if not info.get("connected"):
        return False
    before = keys_mod.load()
    t0 = time.time()
    try:
        if not daemon_proxy().FetchKeys():
            return False
    except Exception:
        return False
    for _ in range(40):
        time.sleep(0.25)
        if (_aap_info()[1].get("keys_received") or 0) >= t0:
            break
    else:
        print("airpodsd pidió las claves pero los AirPods no respondieron; reintenta con ellos puestos")
        return True
    k = keys_mod.load()
    if k and k == before:
        print(f"Las claves de {k.address} ya estaban guardadas y coinciden con las de los AirPods")
    elif k:
        print(f"Claves de {k.address} guardadas en {keys_mod.KEYS_PATH} (0600), vía airpodsd")
    return True


def cmd_keys(args) -> int:
    if args.action == "show":
        k = keys_mod.load()
        print(f"Claves para {k.address} en {keys_mod.KEYS_PATH}" if k else "No hay claves guardadas")
        return 0 if k else 1
    if not args.address and _fetch_keys_via_daemon():
        return 0
    from .aap import AapError, fetch_keys
    address = args.address
    if not address:
        try:
            chosen, candidates = select_airpods(paired_devices())
        except Exception as e:
            sys.exit(f"No se pudo consultar BlueZ: {e}")
        if not candidates:
            sys.exit("No encuentro AirPods emparejados. Emparéjalos primero o indica su dirección: "
                     "airpodsctl keys fetch AA:BB:CC:DD:EE:FF")
        if chosen is None:
            lines = "\n".join(f"  {c['address']}  {c['name']} "
                              f"({MODEL_NAMES[modalias_product(c['modalias'])]})" for c in candidates)
            sys.exit(f"Hay varios AirPods emparejados; elige uno:\n{lines}\n"
                     "  airpodsctl keys fetch <dirección>")
        address = chosen["address"]
        print(f"AirPods: {chosen['name']} ({address})")
    try:
        k = fetch_keys(address)
    except AapError as e:
        sys.exit(f"Error: {e}")
    keys_mod.save(k)
    print(f"Claves de {address} guardadas en {keys_mod.KEYS_PATH} (0600)")
    return 0


def cmd_report(args) -> int:
    from . import report, update
    adverts: list[dict] = []
    if args.scan > 0:
        print(f"Escuchando {args.scan:g} s: abre la caja de los AirPods cerca del equipo…", file=sys.stderr)
        seen: dict[str, dict] = {}

        def on_advert(_addr, rssi, data, _ts):
            clear = report.clear_part(data)
            if clear and rssi >= report.NEAR_RSSI:
                seen.setdefault(clear, {"bytes": clear, "len": len(data), "count": 0})["count"] += 1
        try:
            from .scanner import BleScanner
            # Pasivo, como airpodsd: un discovery activo continuo corta el audio de los AirPods.
            BleScanner(on_advert, window=(4, 8), passive=True).run(duration=args.scan)
        except Exception as e:   # sin BlueZ o sin adaptador: el informe sale igual
            print(f"No se pudo escanear: {e}", file=sys.stderr)
        adverts = list(seen.values())
    try:
        devices = paired_devices()
    except Exception:
        devices = []
    data = report.build(daemon_state(), devices, adverts, report.system_info(),
                        update.current_version(), update.install_kind())
    text = report.render(data)
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(text + "\n")
        print(f"Informe guardado en {args.output}", file=sys.stderr)
    else:
        print(text, flush=True)
    print(f"\nRevísalo y pégalo en {report.ISSUES_URL}", file=sys.stderr)
    return 0


def cmd_airplay(args) -> int:
    """Volumen del iPhone por AirPlay (UxPlay), aparte del resto del audio del PC."""
    from .airplay import is_uxplay_stream, receiver_name, stream_volume
    from .audio import PactlSinks
    sinks = PactlSinks()
    if not sinks.available():
        sys.exit("Hace falta pactl (paquete libpulse)")
    streams = [s for s in sinks.sink_inputs() if is_uxplay_stream(s)]
    if args.volume is None:
        if not streams:
            name = receiver_name()
            print("UxPlay no está sonando" + (f" (en el iPhone, AirPlay a «{name}»)" if name else ""))
            return 1
        print(f"AirPlay (UxPlay): volumen {stream_volume(streams[0])} %")
        return 0
    if not 0 <= args.volume <= 150:
        sys.exit("Volumen de 0 a 150")
    if not streams:
        sys.exit("UxPlay no está sonando: no hay volumen que cambiar")
    ok = all(sinks.set_input_volume(s["index"], args.volume) for s in streams)
    if not ok:
        sys.exit("No se pudo cambiar el volumen")
    print(f"AirPlay (UxPlay): volumen {args.volume} %")
    return 0


def notify_daemon() -> None:
    """Pide a airpodsd que relea la configuración (si está en marcha)."""
    try:
        import dbus
        dbus.SessionBus().get_object("io.github.AirpodsLinux", "/io/github/AirpodsLinux").Reload(
            dbus_interface="io.github.AirpodsLinux1")
    except Exception:
        pass


def cmd_update(args) -> int:
    from . import update
    info = update.check()
    if args.json:
        print(json.dumps({**info, "managed": update.managed_install(), "install": update.install_kind()}))
        return 0 if info["error"] is None else 1
    if info["error"]:
        print(f"No se pudo consultar GitHub: {info['error']}", file=sys.stderr)
        return 1
    if not info["available"]:
        print(f"Tienes la última versión ({info['current']}).")
        return 0
    print(f"Nueva versión disponible: {info['latest']} (tienes {info['current']})\n  {info['url']}")
    if args.check:
        return 0
    if not update.managed_install():
        print(update.UPDATE_HINTS[update.install_kind()])
        return 1
    if not args.yes and sys.stdin.isatty():
        if input("¿Actualizar ahora? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return 0
    return update.run_installer()


def cmd_config(args) -> int:
    from . import config
    if args.action == "get":
        cfg = config.load()
        print(json.dumps(cfg if args.key is None else cfg.get(args.key), indent=2))
        return 0
    if args.key is None or args.value is None:
        sys.exit("uso: airpodsctl config set <opción> <valor>")
    try:
        config.set_value(args.key, args.value)
    except (KeyError, ValueError) as e:
        sys.exit(str(e))
    notify_daemon()
    print(f"{args.key} = {config.load()[args.key]}")
    return 0


def cmd_rename(args) -> int:
    k = keys_mod.load()
    address = k.address if k else None
    if not address:
        chosen, _ = select_airpods(paired_devices())
        address = chosen and chosen["address"]
    if not address:
        sys.exit("No encuentro los AirPods emparejados")
    from .bluez import get_alias, set_alias
    try:
        set_alias(address, args.name.strip())
    except Exception as e:
        sys.exit(f"No se pudo cambiar el nombre: {e}")
    notify_daemon()
    print(f"Nombre en este equipo: {get_alias(address)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsctl")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="estado actual o último conocido")
    p.add_argument("--json", action="store_true")
    p.add_argument("--scan", type=float, default=None,
                   help="segundos máximos escuchando (0 = solo caché; por defecto 30, o 0 con "
                        "--format/--waybar). La caja cerrada anuncia cada 10-60 s")
    p.add_argument("--format", help="una línea con marcadores: {left} {right} {case} {min} {left_chg} "
                                    "{name} {mode} {ago}  (p. ej. '{left}%% {right}%%')")
    p.add_argument("--waybar", action="store_true", help="JSON para un módulo custom de Waybar")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("monitor", help="una línea por cada cambio (barras de estado con exec continuo)")
    p.add_argument("--format", default="{min}%")
    p.add_argument("--waybar", action="store_true")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("mode", help="modo de escucha: off, noise, transparency, adaptive")
    p.add_argument("mode", nargs="?")
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("feature", help="ajustes de los AirPods por AAP (sin argumentos: lista)")
    p.add_argument("name", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_feature)

    p = sub.add_parser("history", help="historial de batería y tiempo restante estimado")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--width", type=int, default=48, help="columnas de la gráfica")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("watch", help="escanea por ventanas y muestra cada cambio")
    p.add_argument("--json", action="store_true")
    p.add_argument("--on", type=float, default=4)
    p.add_argument("--off", type=float, default=8)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("keys", help="claves de proximidad (AAP)")
    p.add_argument("action", choices=["fetch", "show"])
    p.add_argument("address", nargs="?")
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("update", help="busca una versión nueva y actualiza")
    p.add_argument("--check", action="store_true", help="solo comprobar")
    p.add_argument("--json", action="store_true")
    p.add_argument("-y", "--yes", action="store_true", help="no preguntar")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("config", help="preferencias de airpodsd (sin argumentos tras get: todas)")
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("rename", help="cambia el nombre de los AirPods en este equipo ('' = original)")
    p.add_argument("name")
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("airplay", help="volumen del iPhone por AirPlay (UxPlay), aparte del resto")
    p.add_argument("volume", nargs="?", type=int, help="0-150 (sin argumento: el actual)")
    p.set_defaults(func=cmd_airplay)

    p = sub.add_parser("report", help="informe anonimizado para abrir un issue (modelos nuevos, fallos)")
    p.add_argument("--scan", type=float, default=20, help="segundos capturando anuncios (0 = no escanear)")
    p.add_argument("-o", "--output", help="guardar en un fichero en vez de mostrarlo")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
