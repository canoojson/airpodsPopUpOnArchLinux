"""airpodsctl: estado de los AirPods desde la terminal."""
import argparse
import json
import logging
import re
import sys
import time

from . import keys as keys_mod
from .i18n import _
from .bluez import modalias_product, paired_devices, select_airpods
from .proximity import MODEL_NAMES
from .state import STATE_PATH, StateStore, runtime_status_path

BUS_NAME, OBJ_PATH, IFACE = "io.github.AirpodsLinux", "/io/github/AirpodsLinux", "io.github.AirpodsLinux1"

SOURCES = {"ble-enc": "auricular", "ble-case": "caja", "ble-clear": "auricular, sin cifrar"}   # se traducen al mostrar


def age(ts: float | None, now: float) -> str:
    if ts is None:
        return _("nunca")
    s = max(0, int(now - ts))
    if s < 60:
        return _("hace {n} s").format(n=s)
    if s < 3600:
        return _("hace {n} min").format(n=s // 60)
    if s < 86400:
        return _("hace {h} h {m} min").format(h=s // 3600, m=s % 3600 // 60)
    return time.strftime(_("el %d/%m a las %H:%M"), time.localtime(ts))


def fmt_battery(f: dict | None) -> str:
    if not f:
        return f"{'--':>5s}   "
    v = f["value"]
    return f"{v['level']:3d} %{'  ⚡' if v['charging'] else '   '}"


def render(store: StateStore, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if not store.fields:
        return _("Sin datos todavía. Abre la caja cerca del PC o espera a un anuncio de la caja.")
    v = store.value
    model = MODEL_NAMES.get(v("model"), "AirPods")
    lines = [_("{model} · visto {ago}").format(model=model, ago=age(store.last_seen(), now))]

    def where(side):
        if v(f"{side}_in_ear"):
            return _("en la oreja")
        if v(f"{side}_in_case"):
            return _("en la caja")
        return _("fuera") if v(f"{side}_in_case") is not None else ""

    def stale(f):  # marca los datos que no son de la última observación
        return f"  ({age(f['ts'], now)})" if f and now - f["ts"] > 90 else ""

    for side, name in (("left", _("Izquierdo")), ("right", _("Derecho"))):
        f = store.get(side)
        lines.append(f"  {name:10s}{fmt_battery(f)}  {where(side):12s}{stale(f)}".rstrip())
    f = store.get("case")
    info = [{True: _("tapa cerrada"), False: _("tapa abierta")}.get(v("lid_closed"), "")]
    if v("case_on_charger"):
        info.append(_("en el cargador"))
    lines.append(f"  {_('Caja'):10s}{fmt_battery(f)}  {' · '.join(i for i in info if i):12s}{stale(f)}".rstrip())
    src = store.get("rssi")
    if src:
        lines.append("  " + _("Última fuente: {source}, RSSI {rssi} dBm").format(
            source=_(SOURCES[src["source"]]) if src["source"] in SOURCES else src["source"], rssi=src["value"]))
    return "\n".join(lines)


def make_scanner(store, keys, **kw):
    try:
        from .scanner import BleScanner, Tracker
    except ImportError as e:
        sys.exit(_("Falta dbus-python o PyGObject: {error}").format(error=e))
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
            print("\n" + _("Sin claves: batería al 10 % y sin datos con la caja cerrada. Ejecuta: airpodsctl keys fetch"))
    return 0


def cmd_watch(args) -> int:
    store = StateStore(STATE_PATH).load()
    keys = keys_mod.load()

    def on_change(s):
        if args.json:
            print(json.dumps({"now": time.time(), **s.to_dict()}), flush=True)
        else:
            print(time.strftime("[%H:%M:%S]"), render(s), sep="\n", flush=True)

    scanner, _tracker = make_scanner(store, keys, on_change=on_change)
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
        sys.exit(_("Falta dbus-python o PyGObject: {error}").format(error=e))
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
        sys.exit(_("airpodsd no está en marcha: systemctl --user start airpodsd"))
    if info.get("owner") == "airpods-helper":
        if name == "listening_mode":
            import subprocess
            return subprocess.call(["airpods-cli", "anc", raw])
        sys.exit(_("airpods-helper tiene la conexión AAP: cambia este ajuste con airpods-cli"))
    try:
        daemon_proxy().SetSetting(name, raw)
    except Exception as e:
        msg = getattr(e, "get_dbus_message", lambda: str(e))()
        sys.exit(_("No se pudo cambiar: {error}").format(error=msg))
    expected = SETTINGS[name].parse(raw)
    # Los AirPods devuelven el ajuste al aplicarlo; se espera la confirmación un momento.
    for _attempt in range(15):
        time.sleep(0.2)
        _st, info = _aap_info()
        if (info.get("settings") or {}).get(name) == expected:
            print(f"{name} = {_show(expected)}")
            return 0
    print(_("{name}: enviado, sin confirmar (algunos ajustes necesitan un auricular puesto)").format(name=name))
    return 0


def _show(v) -> str:
    return {True: "on", False: "off"}.get(v, str(v)) if isinstance(v, bool) else str(v)


def cmd_mode(args) -> int:
    from .aap import LISTENING_MODES
    if args.mode:
        if args.mode not in LISTENING_MODES:
            sys.exit(_("Modo desconocido; posibles: {values}").format(values=", ".join(LISTENING_MODES)))
        return _set_setting("listening_mode", args.mode)
    st, info = _aap_info()
    mode = (info.get("settings") or {}).get("listening_mode")
    if mode is None:
        if info.get("owner") == "airpods-helper":
            import subprocess
            return subprocess.call(["airpods-cli", "anc"])
        print(_("Desconocido (sin conexión AAP con los AirPods)"))
        return 1
    print(mode)
    return 0


def cmd_feature(args) -> int:
    from .aap import SETTINGS
    if args.name and args.name not in SETTINGS:
        sys.exit(_("Ajuste desconocido; posibles: {values}").format(values=", ".join(SETTINGS)))
    if args.name and args.value is not None:
        return _set_setting(args.name, args.value)
    st, info = _aap_info()
    current = info.get("settings") or {}
    if args.json:
        print(json.dumps(current if not args.name else current.get(args.name)))
        return 0
    if not info.get("connected"):
        owner = info.get("owner")
        print(_("Sin conexión AAP propia (la tiene airpods-helper: usa airpods-cli)") if owner else
              _("Sin conexión AAP propia (conecta los AirPods a este equipo)"))
    for name, s in SETTINGS.items():
        if args.name and name != args.name:
            continue
        val = _show(current[name]) if name in current else "?"
        values = "/".join(s.values) if s.kind == "enum" else ("on/off" if s.kind == "bool" else "0-100")
        print(f"  {name:26s} {val:13s} {_(s.label)} [{values}]")
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
        print(_("Sin historial todavía: airpodsd lo va guardando mientras recibe datos."))
        return 0
    blocks = "▁▂▃▄▅▆▇█"
    print(_("Últimas {hours} h (cada columna ≈ {minutes} min)").format(hours=args.hours, minutes=args.hours * 60 // width))
    for part, label in (("left", _("Izquierdo")), ("right", _("Derecho")), ("case", _("Caja"))):
        line = "".join(" " if v is None else blocks[min(7, v * 8 // 101)] for v in data[part])
        last = next((v for v in reversed(data[part]) if v is not None), None)
        print(f"  {label:10s} {line} {'' if last is None else f'{last} %'}")
    for side, text in (("left", _("Al ritmo actual, al izquierdo le quedan unas {h} h {m:02d} min")),
                       ("right", _("Al ritmo actual, al derecho le quedan unas {h} h {m:02d} min"))):
        if est[side] is not None:
            print("  " + text.format(h=est[side] // 60, m=est[side] % 60))
    return 0


def _fetch_keys_via_daemon() -> bool:
    """Si airpodsd tiene la conexión AAP, le pide las claves (el canal no se puede compartir)."""
    _st, info = _aap_info()
    if not info.get("connected"):
        return False
    before = keys_mod.load()
    t0 = time.time()
    try:
        if not daemon_proxy().FetchKeys():
            return False
    except Exception:
        return False
    for _attempt in range(40):
        time.sleep(0.25)
        if (_aap_info()[1].get("keys_received") or 0) >= t0:
            break
    else:
        print(_("airpodsd pidió las claves pero los AirPods no respondieron; reintenta con ellos puestos"))
        return True
    k = keys_mod.load()
    if k and k == before:
        print(_("Las claves de {address} ya estaban guardadas y coinciden con las de los AirPods").format(address=k.address))
    elif k:
        print(_("Claves de {address} guardadas en {path} (0600), vía airpodsd").format(address=k.address, path=keys_mod.KEYS_PATH))
    return True


def cmd_keys(args) -> int:
    if args.action == "show":
        k = keys_mod.load()
        print(_("Claves para {address} en {path}").format(address=k.address, path=keys_mod.KEYS_PATH) if k
              else _("No hay claves guardadas"))
        return 0 if k else 1
    if not args.address and _fetch_keys_via_daemon():
        return 0
    from .aap import AapError, fetch_keys
    address = args.address
    if not address:
        try:
            chosen, candidates = select_airpods(paired_devices())
        except Exception as e:
            sys.exit(_("No se pudo consultar BlueZ: {error}").format(error=e))
        if not candidates:
            sys.exit(_("No encuentro AirPods emparejados. Emparéjalos primero o indica su dirección: "
                       "airpodsctl keys fetch AA:BB:CC:DD:EE:FF"))
        if chosen is None:
            lines = "\n".join(f"  {c['address']}  {c['name']} "
                              f"({MODEL_NAMES[modalias_product(c['modalias'])]})" for c in candidates)
            sys.exit(_("Hay varios AirPods emparejados; elige uno:\n{lines}\n"
                       "  airpodsctl keys fetch <dirección>").format(lines=lines))
        address = chosen["address"]
        print(f"AirPods: {chosen['name']} ({address})")
    try:
        k = fetch_keys(address)
    except AapError as e:
        sys.exit(_("Error: {error}").format(error=e))
    keys_mod.save(k)
    print(_("Claves de {address} guardadas en {path} (0600)").format(address=address, path=keys_mod.KEYS_PATH))
    return 0


def cmd_report(args) -> int:
    from . import report, update
    adverts: list[dict] = []
    if args.scan > 0:
        print(_("Escuchando {seconds:g} s: abre la caja de los AirPods cerca del equipo…").format(seconds=args.scan),
              file=sys.stderr)
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
            print(_("No se pudo escanear: {error}").format(error=e), file=sys.stderr)
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
        print(_("Informe guardado en {path}").format(path=args.output), file=sys.stderr)
    else:
        print(text, flush=True)
    print("\n" + _("Revísalo y pégalo en {url}").format(url=report.ISSUES_URL), file=sys.stderr)
    return 0


def cmd_airplay(args) -> int:
    """Volumen del iPhone por AirPlay (UxPlay), aparte del resto del audio del PC."""
    from .airplay import is_uxplay_stream, receiver_name, stream_volume
    from .audio import PactlSinks
    sinks = PactlSinks()
    if not sinks.available():
        sys.exit(_("Hace falta pactl (paquete libpulse)"))
    streams = [s for s in sinks.sink_inputs() if is_uxplay_stream(s)]
    if args.volume is None:
        if not streams:
            name = receiver_name()
            print(_("UxPlay no está sonando (en el iPhone, AirPlay a «{name}»)").format(name=name) if name
                  else _("UxPlay no está sonando"))
            return 1
        print(_("AirPlay (UxPlay): volumen {volume} %").format(volume=stream_volume(streams[0])))
        return 0
    if not 0 <= args.volume <= 150:
        sys.exit(_("Volumen de 0 a 150"))
    if not streams:
        sys.exit(_("UxPlay no está sonando: no hay volumen que cambiar"))
    ok = all(sinks.set_input_volume(s["index"], args.volume) for s in streams)
    if not ok:
        sys.exit(_("No se pudo cambiar el volumen"))
    print(_("AirPlay (UxPlay): volumen {volume} %").format(volume=args.volume))
    return 0


def cmd_eq(args) -> int:
    from . import config, eq
    cfg = config.load()
    action, rest = args.action, args.args

    def db(raw: str) -> float:
        try:
            return eq.clamp(float(raw.replace(",", ".")))
        except ValueError:
            sys.exit(_("valor no válido: {value} (dB, de -12 a 12)").format(value=raw))

    if action in ("on", "off"):
        cfg["eq_enabled"] = action == "on"
    elif action == "simple":
        if rest and len(rest) != 3:
            sys.exit(_("uso: airpodsctl eq simple [<graves> <medios> <agudos>]   (dB, de -12 a 12)"))
        cfg["eq_mode"] = eq.SIMPLE
        if rest:
            cfg["eq_simple"], cfg["eq_enabled"] = [db(v) for v in rest], True
    elif action == "advanced":
        cfg["eq_mode"] = eq.ADVANCED
    elif action == "preset":
        if len(rest) != 1 or rest[0] not in eq.PRESETS:
            sys.exit(_("uso: airpodsctl eq preset <nombre>") + "\n  " +
                     "\n  ".join(f"{k:14s} {_(label)}" for k, (label, _g) in eq.PRESETS.items()))
        cfg["eq_mode"], cfg["eq_preset"], cfg["eq_enabled"] = eq.ADVANCED, rest[0], True
    elif action == "set":
        if len(rest) != 2:
            sys.exit(_("uso: airpodsctl eq set <banda> <dB>   (banda: 0-9 o frecuencia, p. ej. 250 o 4k)"))
        try:
            i = eq.band_index(rest[0])
        except ValueError as e:
            sys.exit(str(e))
        gains = eq.gains_for(cfg.get("eq_preset") or "flat", cfg.get("eq_gains"))
        gains[i] = db(rest[1])
        cfg["eq_mode"], cfg["eq_preset"], cfg["eq_gains"], cfg["eq_enabled"] = eq.ADVANCED, eq.CUSTOM, gains, True
    elif action == "reset":
        # Solo el modo actual: el otro conserva sus ajustes.
        if eq.mode(cfg) == eq.SIMPLE:
            cfg["eq_simple"] = None
        else:
            cfg["eq_preset"], cfg["eq_gains"] = "flat", None
    elif action is not None:
        sys.exit(_("uso: airpodsctl eq [on|off|simple [G M A]|advanced|preset <nombre>|set <banda> <dB>|reset]"))
    if action is not None:
        config.save(cfg)
        notify_daemon()
    mode = eq.mode(cfg)
    preset = cfg.get("eq_preset") or "flat"
    simple = eq.simple_values(cfg.get("eq_simple"))
    gains = eq.config_gains(cfg)
    if args.json:
        print(json.dumps({"enabled": bool(cfg.get("eq_enabled")), "mode": mode, "preset": preset, "simple": simple,
                          "gains": gains, "bands": [f for _k, f, _q in eq.BANDS]}))
        return 0
    if mode == eq.SIMPLE:
        label = _("Sencillo")
    else:
        label = _("Personalizado") if preset == eq.CUSTOM else _(eq.PRESETS.get(preset, ("?",))[0])
    st = daemon_state() or {}
    active = (st.get("eq") or {}).get("active")
    if not cfg.get("eq_enabled"):
        head = _("Ecualizador desactivado · {preset}")
    elif active is False:
        head = _("Ecualizador activado (se aplica al conectar los AirPods) · {preset}")
    else:
        head = _("Ecualizador activado · {preset}")
    print(head.format(preset=label))

    def bar(g: float) -> str:
        n = int(round(g))
        return ("─" * (12 + min(n, 0)) + "█" * -min(n, 0)) + "│" + ("█" * max(n, 0)).ljust(12, "─")
    if mode == eq.SIMPLE:
        for name, g in zip((_("Graves"), _("Medios"), _("Agudos")), simple):
            print(f"  {name:>7s} {bar(g)} {g:+5.1f} dB")
        print("  " + _("Bandas resultantes:") + " " + " ".join(f"{g:+g}" for g in gains))
    else:
        for (_k, f, _q), g in zip(eq.BANDS, gains):
            print(f"  {eq.band_label(f):>7s} {bar(g)} {g:+5.1f} dB")
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
        print(_("No se pudo consultar GitHub: {error}").format(error=info["error"]), file=sys.stderr)
        return 1
    if not info["available"]:
        print(_("Tienes la última versión ({version}).").format(version=info["current"]))
        return 0
    print(_("Nueva versión disponible: {latest} (tienes {current})").format(latest=info["latest"], current=info["current"])
          + f"\n  {info['url']}")
    if args.check:
        return 0
    if not update.managed_install():
        print(_(update.UPDATE_HINTS[update.install_kind()]))
        return 1
    if not args.yes and sys.stdin.isatty():
        if input(_("¿Actualizar ahora? [s/N] ")).strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return 0
    return update.run_installer()


def cmd_config(args) -> int:
    from . import config
    if args.action == "get":
        cfg = config.load()
        print(json.dumps(cfg if args.key is None else cfg.get(args.key), indent=2))
        return 0
    if args.key is None or args.value is None:
        sys.exit(_("uso: airpodsctl config set <opción> <valor>"))
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
        chosen, _candidates = select_airpods(paired_devices())
        address = chosen and chosen["address"]
    if not address:
        sys.exit(_("No encuentro los AirPods emparejados"))
    from .bluez import get_alias, set_alias
    try:
        set_alias(address, args.name.strip())
    except Exception as e:
        sys.exit(_("No se pudo cambiar el nombre: {error}").format(error=e))
    notify_daemon()
    print(_("Nombre en este equipo: {name}").format(name=get_alias(address)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="airpodsctl")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help=_("estado actual o último conocido"))
    p.add_argument("--json", action="store_true")
    p.add_argument("--scan", type=float, default=None,
                   help=_("segundos máximos escuchando (0 = solo caché; por defecto 30, o 0 con "
                          "--format/--waybar). La caja cerrada anuncia cada 10-60 s"))
    p.add_argument("--format", help=_("una línea con marcadores: {left} {right} {case} {min} {left_chg} "
                                      "{name} {mode} {ago}  (p. ej. '{left}%% {right}%%')"))
    p.add_argument("--waybar", action="store_true", help=_("JSON para un módulo custom de Waybar"))
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("monitor", help=_("una línea por cada cambio (barras de estado con exec continuo)"))
    p.add_argument("--format", default="{min}%")
    p.add_argument("--waybar", action="store_true")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("mode", help=_("modo de escucha: off, noise, transparency, adaptive"))
    p.add_argument("mode", nargs="?")
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("feature", help=_("ajustes de los AirPods por AAP (sin argumentos: lista)"))
    p.add_argument("name", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_feature)

    p = sub.add_parser("history", help=_("historial de batería y tiempo restante estimado"))
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--width", type=int, default=48, help=_("columnas de la gráfica"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("watch", help=_("escanea por ventanas y muestra cada cambio"))
    p.add_argument("--json", action="store_true")
    p.add_argument("--on", type=float, default=4)
    p.add_argument("--off", type=float, default=8)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("keys", help=_("claves de proximidad (AAP)"))
    p.add_argument("action", choices=["fetch", "show"])
    p.add_argument("address", nargs="?")
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("update", help=_("busca una versión nueva y actualiza"))
    p.add_argument("--check", action="store_true", help=_("solo comprobar"))
    p.add_argument("--json", action="store_true")
    p.add_argument("-y", "--yes", action="store_true", help=_("no preguntar"))
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("config", help=_("preferencias de airpodsd (sin argumentos tras get: todas)"))
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("rename", help=_("cambia el nombre de los AirPods en este equipo ('' = original)"))
    p.add_argument("name")
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("eq", help=_("ecualizador de los AirPods (sin argumentos: el actual)"))
    p.add_argument("action", nargs="?", choices=["on", "off", "simple", "advanced", "preset", "set", "reset"])
    p.add_argument("args", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_eq)

    p = sub.add_parser("airplay", help=_("volumen del iPhone por AirPlay (UxPlay), aparte del resto"))
    p.add_argument("volume", nargs="?", type=int, help=_("0-150 (sin argumento: el actual)"))
    p.set_defaults(func=cmd_airplay)

    p = sub.add_parser("report", help=_("informe anonimizado para abrir un issue (modelos nuevos, fallos)"))
    p.add_argument("--scan", type=float, default=20, help=_("segundos capturando anuncios (0 = no escanear)"))
    p.add_argument("-o", "--output", help=_("guardar en un fichero en vez de mostrarlo"))
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
