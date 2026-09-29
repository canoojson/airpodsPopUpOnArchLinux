"""Parser de los anuncios Apple Proximity Pairing (manufacturer 0x004C, tipo 0x07).

Todos los offsets asumen los datos tal como los entrega BlueZ, sin el prefijo
de compañía `4C 00`. Formatos confirmados con AirPods Pro 3 en docs/findings.md.

Hay dos anuncios:
- Largo (0x19, 27 bytes): lo emite un auricular. 11 bytes en claro + 16 cifrados.
- Corto (0x11, 19 bytes): lo emite la caja, también con la tapa cerrada.
  3 bytes en claro + 16 cifrados.
"""
from dataclasses import dataclass

from .crypto import aes_ecb_decrypt

PROXIMITY_TYPE = 0x07
LONG_LEN = 0x19
SHORT_LEN = 0x11
# ID de producto (el mismo que el modalias de BlueZ, p. ej. bluetooth:v004Cp2027).
# Pro 3 verificado; el resto según LibrePods.
MODEL_NAMES = {
    0x2002: "AirPods", 0x200F: "AirPods (2.ª gen.)", 0x2013: "AirPods (3.ª gen.)",
    0x2019: "AirPods 4", 0x201B: "AirPods 4 (ANC)",
    0x200E: "AirPods Pro", 0x2014: "AirPods Pro 2", 0x2024: "AirPods Pro 2 (USB-C)",
    0x2027: "AirPods Pro 3",
    0x200A: "AirPods Max", 0x201F: "AirPods Max (USB-C)",
}
# Un anuncio de caja bien descifrado empieza por un ID de producto 0x20xx en
# little-endian (0x2029 en la caja del Pro 3) y tiene los bytes 8-11 a cero.


@dataclass(frozen=True)
class Battery:
    level: int  # %
    charging: bool


def battery_from_byte(b: int) -> Battery | None:
    """Byte cifrado: bit 7 = cargando, bits 0-6 = %, 0x7f = no disponible."""
    level = b & 0x7F
    if level == 0x7F or level > 100:
        return None
    return Battery(level, bool(b & 0x80))


def battery_from_nibble(n: int) -> int | None:
    """Nibble en claro: 0x0-0x9 = n*10 %, 0xA-0xE = 100 %, 0xF = no disponible."""
    return None if n == 0xF else min(n, 10) * 10


@dataclass(frozen=True)
class PodAdvert:
    """Anuncio largo de un auricular, parte en claro."""
    model: int
    primary_left: bool
    left: Battery | None
    right: Battery | None
    case: Battery | None
    left_in_ear: bool
    right_in_ear: bool
    both_in_case: bool
    one_in_case: bool
    this_in_case: bool
    lid_closed: bool | None  # solo fiable con algún auricular en la caja
    lid_open_count: int
    color: int
    connection_state: int
    encrypted: bytes

    @property
    def model_name(self) -> str:
        return MODEL_NAMES.get(self.model, f"0x{self.model:04x}")


def parse_pod_advert(data: bytes) -> PodAdvert | None:
    if len(data) < 27 or data[0] != PROXIMITY_TYPE or data[1] != LONG_LEN:
        return None
    if data[2] != 0x01:  # 0x00 = modo emparejamiento, estructura distinta
        return None
    status, pods, flags_case, lid = data[5], data[6], data[7], data[8]
    primary_left = bool(status & 0x20)
    flipped = not primary_left
    flags = flags_case >> 4
    # Nibbles de batería de auriculares y bits de carga: orden según primario.
    left_n, right_n = (pods >> 4, pods & 0xF) if flipped else (pods & 0xF, pods >> 4)
    left_chg = bool(flags & (0x02 if flipped else 0x01))
    right_chg = bool(flags & (0x01 if flipped else 0x02))

    def nib(n, chg):
        lvl = battery_from_nibble(n)
        return None if lvl is None else Battery(lvl, chg)

    # En oreja: bits 1 y 3 con lógica XOR (LibrePods), comprobado con 0x0b/0x01.
    xor = flipped ^ bool(status & 0x40)
    left_in_ear = bool(status & (0x08 if xor else 0x02))
    right_in_ear = bool(status & (0x02 if xor else 0x08))
    # Byte 8 bit 5: "este auricular en la caja" (observado; bit 6 de status no encaja).
    this_in_case = bool(lid & 0x20)
    any_in_case = bool(status & 0x14)
    return PodAdvert(
        model=int.from_bytes(data[3:5], "little"),
        primary_left=primary_left,
        left=nib(left_n, left_chg),
        right=nib(right_n, right_chg),
        case=nib(flags_case & 0xF, bool(flags & 0x04)),
        left_in_ear=left_in_ear,
        right_in_ear=right_in_ear,
        both_in_case=bool(status & 0x04),
        one_in_case=bool(status & 0x10),
        this_in_case=this_in_case,
        lid_closed=bool(lid & 0x08) if any_in_case else None,
        lid_open_count=lid & 0x07,
        color=data[9],
        connection_state=data[10],
        encrypted=bytes(data[11:27]),
    )


@dataclass(frozen=True)
class PodSecret:
    """Parte cifrada del anuncio largo, ya descifrada."""
    left: Battery | None
    right: Battery | None
    case: Battery | None


def decrypt_pod(adv: PodAdvert, enc_key: bytes) -> PodSecret:
    d = aes_ecb_decrypt(enc_key, adv.encrypted)
    li, ri = (1, 2) if adv.primary_left else (2, 1)
    return PodSecret(battery_from_byte(d[li]), battery_from_byte(d[ri]), battery_from_byte(d[3]))


@dataclass(frozen=True)
class CaseAdvert:
    """Anuncio corto de la caja, descifrado."""
    flags: int  # sin decodificar del todo; ver docs/findings.md §11
    case: Battery | None
    left: Battery | None
    right: Battery | None
    counter: int

    @property
    def pods_in_case(self) -> bool:
        return self.left is not None or self.right is not None

    @property
    def lid_closed(self) -> bool:
        return bool(self.flags & 0x08)  # bit 3, coherente con todas las capturas

    @property
    def on_charger(self) -> bool:
        return bool(self.flags & 0x02)  # bit 1 (docs/findings.md §12); el bit 0 es desconocido


def is_case_advert(data: bytes) -> bool:
    return len(data) == 19 and data[0] == PROXIMITY_TYPE and data[1] == SHORT_LEN


def decrypt_case(data: bytes, enc_key: bytes) -> CaseAdvert | None:
    """Descifra un anuncio de caja. Devuelve None si no es de *nuestra* caja
    (con otra clave el bloque sale aleatorio: probabilidad de falso positivo ~2^-40)."""
    if not is_case_advert(data):
        return None
    d = aes_ecb_decrypt(enc_key, data[-16:])
    if d[1] != 0x20 or any(d[8:12]):
        return None
    # Bytes 4-5: auriculares. El orden L/R aún no está verificado (siempre iguales).
    return CaseAdvert(flags=d[2], case=battery_from_byte(d[3]), left=battery_from_byte(d[4]),
                      right=battery_from_byte(d[5]), counter=int.from_bytes(d[12:14], "little"))
