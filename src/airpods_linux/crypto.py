"""Primitivas criptográficas: resolución de RPA con la IRK y descifrado AES."""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def aes_ecb_encrypt(key: bytes, block: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(block) + enc.finalize()


def aes_ecb_decrypt(key: bytes, block: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(block) + dec.finalize()


def resolves_rpa(irk: bytes, address: str) -> bool:
    """¿Es `address` (formato BlueZ, AA:BB:..) una RPA generada con `irk`?

    `irk` en el orden en que la entregan los AirPods por AAP (little-endian);
    AES trabaja en big-endian, de ahí la inversión.
    """
    b = bytes.fromhex(address.replace(":", ""))
    if len(b) != 6 or b[0] >> 6 != 0b01:
        return False
    prand, hash_ = b[:3], b[3:]
    return aes_ecb_encrypt(irk[::-1], bytes(13) + prand)[-3:] == hash_


def make_rpa(irk: bytes, prand: bytes) -> str:
    """Genera una RPA (para tests). `prand` de 3 bytes con los bits altos a 01."""
    prand = bytes([(prand[0] & 0x3F) | 0x40]) + prand[1:3]
    h = aes_ecb_encrypt(irk[::-1], bytes(13) + prand)[-3:]
    return ":".join(f"{x:02X}" for x in prand + h)
