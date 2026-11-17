# Packing the secret before we hide it, plus some bit helpers.
#
# What actually goes inside the carrier:
#   8 bits   -> k (how many LSBs per sample we used), always written with 1 bit per sample
#   32 bits  -> length of the data that follows
#   the data -> 'P' + package          (no password)
#               'E' + salt + nonce + AES-GCM(package)   (with password)
#
# package = "STG1" + flags + name length + file name + secret bytes

import hashlib
import os
import struct
import zlib

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b"STG1"
HEADER_K_SLOTS = 8
LEN_BITS = 32


class StegoError(Exception):
    # errors we want to show to the user as-is
    pass


class Secret:
    def __init__(self, data, is_file, name=""):
        self.data = data
        self.is_file = is_file
        self.name = name

    @property
    def text(self):
        return self.data.decode("utf-8", errors="replace")


def make_key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000)
    return kdf.derive(password.encode())


def position_seed(password):
    # the password also decides which samples we use
    h = hashlib.sha256(b"stego-positions|" + (password or "").encode()).digest()
    return int.from_bytes(h[:8], "big")


def pack(secret, password=""):
    data = secret.data
    flags = 1 if secret.is_file else 0

    # only keep the compressed version if it's actually smaller
    compressed = zlib.compress(data, 9)
    if len(compressed) < len(data):
        data = compressed
        flags |= 2

    name = secret.name.encode()[:255]
    package = MAGIC + bytes([flags]) + struct.pack(">H", len(name)) + name + data

    if not password:
        return b"P" + package

    salt = os.urandom(16)
    nonce = os.urandom(12)
    encrypted = AESGCM(make_key(password, salt)).encrypt(nonce, package, MAGIC)
    return b"E" + salt + nonce + encrypted


def unpack(blob, password=""):
    if not blob:
        raise StegoError("No hidden data found.")

    mode = blob[:1]
    rest = blob[1:]
    if mode == b"E":
        if not password:
            raise StegoError("This message is encrypted - enter the password.")
        salt, nonce, encrypted = rest[:16], rest[16:28], rest[28:]
        try:
            package = AESGCM(make_key(password, salt)).decrypt(nonce, encrypted, MAGIC)
        except InvalidTag:
            raise StegoError("Wrong password, or the file was modified.")
    elif mode == b"P":
        package = rest
    else:
        raise StegoError("No hidden data found (or wrong password).")

    if package[:4] != MAGIC:
        raise StegoError("No hidden data found (or wrong password).")

    flags = package[4]
    name_len = struct.unpack(">H", package[5:7])[0]
    name = package[7:7 + name_len].decode("utf-8", errors="replace")
    data = package[7 + name_len:]
    if flags & 2:
        data = zlib.decompress(data)
    return Secret(data, bool(flags & 1), name)


# ---------- bit helpers ----------

def bytes_to_bits(b):
    return np.unpackbits(np.frombuffer(b, dtype=np.uint8))


def bits_to_bytes(bits):
    return np.packbits(bits.astype(np.uint8)).tobytes()


def bits_to_chunks(bits, k):
    # turn the bit list into groups of k bits (each group = one number to write)
    extra = (-len(bits)) % k
    if extra:
        bits = np.concatenate([bits, np.zeros(extra, dtype=np.uint8)])
    bits = bits.reshape(-1, k).astype(np.uint16)
    chunks = np.zeros(len(bits), dtype=np.uint16)
    for i in range(k):
        chunks = (chunks << 1) | bits[:, i]
    return chunks


def chunks_to_bits(chunks, k):
    out = np.zeros((len(chunks), k), dtype=np.uint8)
    for i in range(k):
        out[:, i] = (chunks >> (k - 1 - i)) & 1
    return out.reshape(-1)


def stream_for(blob):
    # length first, then the data
    return bytes_to_bits(struct.pack(">I", len(blob)) + blob)


def chunks_needed(blob_len, k):
    total_bits = LEN_BITS + 8 * blob_len
    return (total_bits + k - 1) // k


def capacity_bytes(n_samples, k):
    usable_bits = max(0, n_samples - HEADER_K_SLOTS) * k
    return max(0, usable_bits // 8 - 4)
