"""Protocolo AAP (Apple Accessory Protocol, L2CAP PSM 0x1001), implementación propia.

Formatos según la documentación de LibrePods. Todos los paquetes de control empiezan
por `04 00 04 00` y un código de operación de 2 bytes (little-endian):

  handshake      00 00 04 00 01 00 02 00 00 00 00 00 00 00 00 00  ->  01 00 04 00 ...
  funciones      04 00 04 00 4d 00 ff 00 00 00 00 00 00 00        ->  04 00 04 00 4e 00 ...
  notificaciones 04 00 04 00 0f 00 ff ff ff ff
  (cada paso espera la respuesta del anterior: sin ella los AirPods ignoran la suscripción
   y no mandan ni batería ni oreja; comprobado con unos AirPods Pro 3)
  claves         04 00 04 00 30 00 05 00  ->  04 00 04 00 31 00 <n> {tipo, longitud (2 B, BE), reservado, clave}...
  batería        04 00 04 00 04 00 <n> {componente, 01, nivel, estado, 01}...
  oreja          04 00 04 00 06 00 <primario> <secundario>          (0 oreja, 1 fuera, 2 caja)
  ajuste         04 00 04 00 09 00 <id> <v1> <v2> <v3> <v4>        (en los dos sentidos)
  conversación   04 00 04 00 4b 00 02 00 01 <nivel>

Este módulo no abre conexiones salvo fetch_keys(); el cliente de airpodsd está en aap_client.
"""
import socket
import time
from dataclasses import dataclass

from .keys import ProximityKeys
from .proximity import Battery

PSM = 0x1001
HEADER = bytes.fromhex("04000400")
HANDSHAKE = bytes.fromhex("00000400010002000000000000000000")
SET_FEATURES = bytes.fromhex("04000400" "4d00" "ff00000000000000")
REQUEST_NOTIFICATIONS = bytes.fromhex("04000400" "0f00" "ffffffff")
KEY_REQUEST = bytes.fromhex("0400040030000500")
KEY_RESPONSE = bytes.fromhex("0400040031")
KEY_IRK, KEY_ENC = 0x01, 0x04

OP_BATTERY, OP_EAR, OP_SETTING, OP_KEYS, OP_CONVERSATION = 0x04, 0x06, 0x09, 0x31, 0x4B
OP_FEATURES_ACK = 0x4E
HANDSHAKE_ACK = bytes.fromhex("01000400")   # respuesta al handshake (sin cabecera 04 00 04 00)

# Batería: componente y estado
PART_RIGHT, PART_LEFT, PART_CASE = 0x02, 0x04, 0x08
BAT_CHARGING, BAT_DISCONNECTED = 0x01, 0x04

# Oreja
EAR_IN, EAR_OUT, EAR_CASE = 0x00, 0x01, 0x02


class AapError(Exception):
    pass


# --- ajustes -------------------------------------------------------------------

@dataclass(frozen=True)
class Setting:
    ident: int
    kind: str                     # "enum" | "bool" | "range"
    values: dict | None = None    # enum: nombre -> byte
    label: str = ""

    def encode(self, value) -> int:
        if self.kind == "enum":
            if value not in self.values:
                raise ValueError(f"valores posibles: {', '.join(self.values)}")
            return self.values[value]
        if self.kind == "bool":
            return 0x01 if value else 0x02
        v = int(value)
        if not 0 <= v <= 100:
            raise ValueError("valor de 0 a 100")
        return v

    def decode(self, byte: int):
        if self.kind == "enum":
            return next((k for k, v in self.values.items() if v == byte), None)
        if self.kind == "bool":
            return {0x01: True, 0x02: False}.get(byte)
        return byte if 0 <= byte <= 100 else None

    def parse(self, raw: str):
        """Valor escrito por el usuario (CLI) -> valor del ajuste."""
        if self.kind == "bool":
            low = raw.strip().lower()
            if low in ("1", "true", "on", "yes", "si", "sí"):
                return True
            if low in ("0", "false", "off", "no"):
                return False
            raise ValueError("espera on/off")
        if self.kind == "range":
            try:
                return int(raw)
            except ValueError:
                raise ValueError("espera un número de 0 a 100") from None
        return raw.strip().lower()


LISTENING_MODES = {"off": 0x01, "noise": 0x02, "transparency": 0x03, "adaptive": 0x04}
SETTINGS = {
    "listening_mode": Setting(0x0D, "enum", LISTENING_MODES, "modo de escucha"),
    "conversational_awareness": Setting(0x28, "bool", label="detección de conversación"),
    "adaptive_noise_level": Setting(0x2E, "range", label="nivel del modo adaptativo (0 = más ambiente)"),
    "one_bud_anc": Setting(0x1B, "bool", label="cancelación de ruido con un solo auricular"),
    "volume_swipe": Setting(0x25, "bool", label="volumen deslizando en el tallo"),
    "mic_mode": Setting(0x01, "enum", {"auto": 0x00, "right": 0x01, "left": 0x02}, "micrófono"),
    "chime_volume": Setting(0x1F, "range", label="volumen de los avisos sonoros"),
}
SETTING_BY_ID = {s.ident: name for name, s in SETTINGS.items()}

# Modos de escucha por modelo (IDs de proximity.MODEL_NAMES). Sin cancelación de ruido: ninguno.
_ADAPTIVE = {0x2014, 0x2024, 0x2027, 0x201B}     # Pro 2, Pro 2 USB-C, Pro 3, AirPods 4 ANC
_ANC_ONLY = {0x200E, 0x200A, 0x201F}             # Pro, Max, Max USB-C


def listening_modes(model: int | None) -> list[str]:
    """Modos que ofrece el control, en el orden de iOS."""
    if model in _ADAPTIVE:
        return ["off", "transparency", "adaptive", "noise"]
    if model in _ANC_ONLY:
        return ["off", "transparency", "noise"]
    return []


def setting_packet(name: str, value) -> bytes:
    s = SETTINGS[name]
    return HEADER + bytes([OP_SETTING, 0x00, s.ident, s.encode(value), 0, 0, 0])


# --- paquetes recibidos ---------------------------------------------------------

@dataclass(frozen=True)
class AapBattery:
    left: Battery | None
    right: Battery | None
    case: Battery | None
    primary_left: bool | None     # el primer auricular del paquete es el primario


@dataclass(frozen=True)
class AapEar:
    primary: int      # EAR_IN / EAR_OUT / EAR_CASE
    secondary: int


def opcode(pkt: bytes) -> int | None:
    if len(pkt) < 6 or pkt[:4] != HEADER:
        return None
    return int.from_bytes(pkt[4:6], "little")


def parse_battery(pkt: bytes) -> AapBattery | None:
    if opcode(pkt) != OP_BATTERY or len(pkt) < 7:
        return None
    parts, primary_left = {}, None
    for i in range(pkt[6]):
        off = 7 + 5 * i
        if off + 5 > len(pkt):
            break
        kind, level, status = pkt[off], pkt[off + 2], pkt[off + 3]
        if kind in (PART_LEFT, PART_RIGHT) and primary_left is None:
            primary_left = kind == PART_LEFT
        if status == BAT_DISCONNECTED or level > 100:
            parts[kind] = None
        else:
            parts[kind] = Battery(level, status == BAT_CHARGING)
    if not parts:
        return None
    return AapBattery(parts.get(PART_LEFT), parts.get(PART_RIGHT), parts.get(PART_CASE), primary_left)


def parse_ear(pkt: bytes) -> AapEar | None:
    if opcode(pkt) != OP_EAR or len(pkt) < 8:
        return None
    return AapEar(pkt[6], pkt[7])


def parse_setting(pkt: bytes) -> tuple[str, object] | None:
    if opcode(pkt) != OP_SETTING or len(pkt) < 8:
        return None
    name = SETTING_BY_ID.get(pkt[6])
    if name is None:
        return None
    value = SETTINGS[name].decode(pkt[7])
    return (name, value) if value is not None else None


def parse_conversation(pkt: bytes) -> int | None:
    if opcode(pkt) != OP_CONVERSATION or len(pkt) < 10:
        return None
    return pkt[9]


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


def ear_sides(ear: AapEar, primary_left: bool | None) -> tuple[int, int] | None:
    """(izquierdo, derecho) a partir de primario/secundario. Sin saber cuál es el
    primario solo se puede si los dos están igual."""
    if primary_left is None:
        return (ear.primary, ear.secondary) if ear.primary == ear.secondary else None
    return (ear.primary, ear.secondary) if primary_left else (ear.secondary, ear.primary)


def ear_count(ear: AapEar) -> int:
    return int(ear.primary == EAR_IN) + int(ear.secondary == EAR_IN)


# --- conexión directa (airpodsctl keys fetch sin airpodsd) -----------------------

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
