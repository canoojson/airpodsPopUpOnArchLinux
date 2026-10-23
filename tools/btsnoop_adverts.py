#!/usr/bin/env python3
"""Anuncios Apple Proximity (0x004C, tipo 0x07) de una captura de `btmon -w`.

btmon guarda en formato btsnoop "Linux Monitor" (datalink 2001): cada registro lleva
en el campo de flags el índice del adaptador y el código de operación. Aquí se leen
los eventos HCI LE Advertising Report (normal y extendido), se sacan los datos de
fabricante de Apple y se miden los intervalos entre anuncios a nivel de controlador,
que es lo que BlueZ no deja ver (solo avisa cuando cambian el RSSI o los datos).

Uso: btsnoop_adverts.py captura.btsnoop [--short] [--decrypt]
  --short    solo los de la caja (0x11)
  --decrypt  descifra los de nuestra caja con las claves guardadas y muestra los flags
"""
import statistics
import struct
import sys

BTSNOOP_MAGIC = b"btsnoop\0"
MONITOR_EVENT = 0x0003           # opcode de "Linux Monitor" para eventos HCI
EPOCH_DELTA_US = 0x00DCDDB30F2F8000   # btsnoop cuenta desde el año 0
LE_META, ADV_REPORT, EXT_ADV_REPORT = 0x3E, 0x02, 0x0D


def records(data: bytes):
    """(segundos Unix, opcode, paquete) de cada registro."""
    if data[:8] != BTSNOOP_MAGIC:
        raise ValueError("no es una captura btsnoop")
    off = 16
    while off + 24 <= len(data):
        _orig, incl, flags, _drops, ts = struct.unpack(">IIIIq", data[off:off + 24])
        off += 24
        yield (ts - EPOCH_DELTA_US) / 1e6, flags & 0xFFFF, data[off:off + incl]
        off += incl


def apple_payloads(ad: bytes):
    """Datos de fabricante de Apple (sin el 4C 00) dentro de una estructura AD."""
    i = 0
    while i < len(ad):
        n = ad[i]
        if n == 0 or i + 1 + n > len(ad):
            break
        if ad[i + 1] == 0xFF and ad[i + 2:i + 4] == b"\x4c\x00":
            yield ad[i + 4:i + 1 + n]
        i += 1 + n


def adverts(data: bytes):
    """(segundos, dirección, rssi, datos Apple) de cada anuncio de proximidad."""
    for ts, opcode, pkt in records(data):
        if opcode != MONITOR_EVENT or len(pkt) < 3 or pkt[0] != LE_META:
            continue
        sub, body = pkt[2], pkt[3:]
        if sub == ADV_REPORT and body:
            # Un solo informe por evento (lo normal); tipo, tipo de dirección, dirección, longitud, datos, rssi.
            if len(body) < 10:
                continue
            addr = ":".join(f"{b:02X}" for b in reversed(body[3:9]))
            n = body[9]
            ad, rssi = body[10:10 + n], struct.unpack("b", body[10 + n:11 + n] or b"\0")[0]
        elif sub == EXT_ADV_REPORT and body:
            if len(body) < 25:
                continue
            addr = ":".join(f"{b:02X}" for b in reversed(body[4:10]))
            rssi = struct.unpack("b", body[18:19])[0]
            n = body[24]
            ad = body[25:25 + n]
        else:
            continue
        for payload in apple_payloads(ad):
            if payload[:1] == b"\x07":
                yield ts, addr, rssi, payload


def intervals(times: list[float]) -> dict:
    gaps = [b - a for a, b in zip(times, times[1:])]
    if not gaps:
        return {"count": len(times)}
    return {"count": len(times), "median_s": round(statistics.median(gaps), 2),
            "max_s": round(max(gaps), 1), "gaps_over_60s": sum(g > 60 for g in gaps)}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    only_short = "--short" in sys.argv or "--decrypt" in sys.argv
    found = [a for a in adverts(open(sys.argv[1], "rb").read()) if not only_short or a[3][1:2] == b"\x11"]
    by_addr: dict[str, list[float]] = {}
    for ts, addr, _rssi, _p in found:
        by_addr.setdefault(addr, []).append(ts)
    for addr, times in by_addr.items():
        print(addr, intervals(times))
    print("total:", intervals(sorted(ts for ts, *_ in found)))
    if "--decrypt" in sys.argv:
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from airpods_linux import keys
        from airpods_linux.proximity import decrypt_case
        k = keys.load()
        if k is None:
            print("sin claves: airpodsctl keys fetch")
            return 1
        last = None
        for ts, addr, _rssi, payload in found:
            case = decrypt_case(payload, k.enc_key)
            if case and (case.flags, case.case) != last:
                last = (case.flags, case.case)
                print(f"  {ts:.1f}  {addr}  flags=0x{case.flags:02x} ({case.flags:04b})  caja={case.case}  "
                      f"L={case.left}  R={case.right}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
