#!/usr/bin/env python3
"""Prueba del ecualizador con audio de verdad, sin tocar lo que estás escuchando.

Crea una salida nula temporal, lanza el filtro tal como lo genera eq.render_conf()
apuntando a ella, reproduce un tono de 1 kHz hacia esa salida (WirePlumber lo pasa por
el filtro, como haría con la música hacia los AirPods), graba lo que llega y mide el
pico. Comprueba que suena, que una banda a -12 dB se nota y que los cambios en vivo
con pw-cli se aplican. Al terminar quita la salida nula y el filtro.

Uso: tools/eq_selftest.py      (necesita PipeWire, WirePlumber 0.5, pw-play y pw-record)
"""
import json
import math
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from airpods_linux import eq  # noqa: E402

NULL = "airpods_linux_eqtest_null"
LEVEL = 8000 / 32768       # pico del tono de prueba


def write_tone(path: Path, seconds: float = 2.5) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<hh", *(2 * [int(8000 * math.sin(2 * math.pi * 1000 * i / 48000))]))
                               for i in range(int(48000 * seconds))))


def peak(path: Path) -> float:
    with wave.open(str(path)) as w:
        fr = w.readframes(w.getnframes())
        vals = (struct.unpack(f"<{len(fr) // 4}f", fr) if w.getsampwidth() == 4
                else [v / 32768 for v in struct.unpack(f"<{len(fr) // 2}h", fr)])
    # Solo el último tercio: fuera queda el arranque del enlace y, en la prueba en vivo,
    # lo que sonó antes del cambio.
    return max((abs(v) for v in vals[2 * len(vals) // 3:]), default=0.0)


def measure(tmp: Path, tone: Path, before_play=None) -> float:
    out = tmp / "out.wav"
    # Enlaces a mano desde el monitor de la salida nula: con un smart filter, WirePlumber
    # llevaría la grabación al monitor del propio filtro, que es su entrada (sin procesar).
    rec = subprocess.Popen(["pw-record", "-P", "{ node.autoconnect = false node.name = airpods_linux_eqtest_rec }",
                            str(out)], stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    for ch in ("FL", "FR"):
        subprocess.run(["pw-link", f"{NULL}:monitor_{ch}", f"airpods_linux_eqtest_rec:input_{ch}"],
                       capture_output=True)
    play = subprocess.Popen(["pw-play", "--target", NULL, str(tone)])
    if before_play:
        time.sleep(0.8)
        before_play()
    play.wait()
    time.sleep(0.3)
    rec.terminate()
    rec.wait()
    return peak(out)


def node_id() -> int | None:
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
    return eq.find_node_id(dump)


def main() -> int:
    ok = True
    mod = subprocess.run(["pactl", "load-module", "module-null-sink", f"sink_name={NULL}"],
                         capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        tone = tmp / "tone.wav"
        write_tone(tone)
        proc = None

        def check(label, value, lo, hi):
            nonlocal ok
            good = lo <= value <= hi
            ok &= good
            print(f"  {'✔' if good else '✘'} {label}: pico {value:.3f} (esperado {lo:.3f}-{hi:.3f})")

        try:
            base = measure(tmp, tone)
            check("sin filtro", base, LEVEL * 0.95, LEVEL * 1.05)
            for label, gains, lo, hi in [("plano", eq.FLAT, 0.95, 1.05),
                                         ("-12 dB en 1 kHz", [0, 0, 0, 0, 0, -12, 0, 0, 0, 0], 0.15, 0.6)]:
                conf = tmp / "eq.conf"
                conf.write_text(eq.render_conf(NULL, gains))
                proc = subprocess.Popen(["pipewire", "-c", str(conf)], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                time.sleep(1.5)
                check(f"filtro {label}", measure(tmp, tone), LEVEL * lo, LEVEL * hi)
                if label == "plano":
                    nid = node_id()
                    live = [0, 0, 0, 0, 0, -12, 0, 0, 0, 0]

                    def change():
                        subprocess.run(["pw-cli", "set-param", str(nid), "Props", eq.props_param(live)],
                                       capture_output=True)
                    check("cambio en vivo a -12 dB en 1 kHz", measure(tmp, tone, change), LEVEL * 0.15, LEVEL * 0.6)
                proc.terminate()
                proc.wait()
                proc = None
        finally:
            if proc:
                proc.terminate()
            subprocess.run(["pactl", "unload-module", mod], capture_output=True)
    print("Todo bien" if ok else "FALLA")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
