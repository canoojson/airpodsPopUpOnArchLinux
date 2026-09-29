"""Cliente AAP mínimo (L2CAP PSM 0x1001): de momento solo pide las claves de proximidad.

Secuencia según la documentación de LibrePods (implementación propia):
  handshake  00 00 04 00 01 00 02 00 00 00 00 00 00 00 00 00
  petición   04 00 04 00 30 00 05 00
  respuesta  04 00 04 00 31 00 <n> {tipo, longitud (2 B, BE), reservado, clave}...
"""
import socket
import time

from .keys import ProximityKeys

PSM = 0x1001
HANDSHAKE = bytes.fromhex("00000400010002000000000000000000")
KEY_REQUEST = bytes.fromhex("0400040030000500")
KEY_RESPONSE = bytes.fromhex("0400040031")
KEY_IRK, KEY_ENC = 0x01, 0x04


class AapError(Exception):
    pass


def parse_key_response(pkt: bytes) -> dict[int, bytes]:
    if len(pkt) < 7 or pkt[:5] != KEY_RESPONSE:
        return {}
    keys, off = {}, 7
    for _ in range(pkt[6]):
        if off + 4 > len(pkt):
            break
        ktype, klen = pkt[off], int.from_bytes(pkt[off + 1:off + 3], "big")
        off += 4
        keys[ktype] = bytes(pkt[off:off + klen])
        off += klen
    return keys


def fetch_keys(address: str, timeout: float = 8.0) -> ProximityKeys:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    s.settimeout(timeout)
    try:
        s.connect((address, PSM))
    except OSError as e:
        raise AapError(f"no se pudo abrir L2CAP 0x1001 ({e}); ¿están conectados los AirPods?") from e
    try:
        s.send(HANDSHAKE)
        time.sleep(0.5)
        s.send(KEY_REQUEST)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                keys = parse_key_response(s.recv(2048))
            except socket.timeout:
                break
            if KEY_IRK in keys and KEY_ENC in keys:
                return ProximityKeys(address, keys[KEY_IRK], keys[KEY_ENC])
    finally:
        s.close()
    raise AapError("los AirPods no enviaron las claves; si airpods-daemon (airpods-helper) está "
                   "activo ocupa el canal AAP: systemctl --user stop airpods-daemon y reintenta")
