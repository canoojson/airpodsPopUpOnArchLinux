#!/usr/bin/env python3
"""Spike: resuelve direcciones con la IRK y descifra los 16 bytes finales de
cada anuncio 0x07 de las fixtures con la ENC_KEY (AES-128-ECB).

Uso: decrypt_fixtures.py [fixtures/*.jsonl]
"""
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEYS_PATH = Path.home() / ".config" / "airpods-linux" / "keys.json"


def aes_ecb(key: bytes, block: bytes, decrypt: bool) -> bytes:
    c = Cipher(algorithms.AES(key), modes.ECB())
    op = c.decryptor() if decrypt else c.encryptor()
    return op.update(block) + op.finalize()


def resolves(irk: bytes, addr: str) -> bool:
    """RPA: los 3 bytes altos son prand (bits 7-6 = 01), los 3 bajos el hash."""
    b = bytes.fromhex(addr.replace(":", ""))  # orden de presentación = big-endian
    prand, h = b[:3], b[3:]
    if prand[0] >> 6 != 0b01:
        return False
    return aes_ecb(irk, bytes(13) + prand, decrypt=False)[-3:] == h


def batt(b: int) -> str:
    lvl, chg = b & 0x7F, bool(b & 0x80)
    return "--" if lvl == 0x7F else f"{lvl}%{'⚡' if chg else ''}"


def main():
    keys = json.loads(KEYS_PATH.read_text())
    irk, enc = bytes.fromhex(keys["irk"]), bytes.fromhex(keys["enc_key"])
    irks = {"irk": irk, "irk_rev": irk[::-1]}

    files = sys.argv[1:] or sorted(str(p) for p in (Path(__file__).parent.parent / "fixtures").glob("*.jsonl"))
    for f in files:
        print(f"== {Path(f).name}")
        seen = {}
        for line in open(f):
            r = json.loads(line)
            raw = bytes.fromhex(r["hex"])
            if raw[0] != 0x07:
                continue
            match = [n for n, k in irks.items() if resolves(k, r["addr"])]
            dec = aes_ecb(enc, raw[-16:], decrypt=True)
            key = (r["addr"], raw.hex())
            if key in seen:
                continue
            seen[key] = True
            kind = "largo" if raw[1] == 0x19 else f"corto({raw[1]:#04x})"
            print(f"  {r['addr']} {kind:11s} irk={','.join(match) or 'no':8s} "
                  f"dec={dec.hex()}  L/R?={batt(dec[1])}/{batt(dec[2])} caja?={batt(dec[3])}")


if __name__ == "__main__":
    main()
