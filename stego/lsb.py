# The actual LSB hiding. Works on any flat numpy array of samples:
# the whole audio file, or one video frame at a time.
# For every buffer we shuffle the indexes using the password, and write the
# bits in that order.

import struct

import numpy as np

from .payload import (HEADER_K_SLOTS, LEN_BITS, StegoError, bits_to_bytes,
                      bits_to_chunks, chunks_to_bits, stream_for)


def permutation(seed, index, n):
    rng = np.random.default_rng([seed & 0xFFFFFFFF, seed >> 32, index])
    return rng.permutation(n)


class LSBWriter:
    def __init__(self, blob, k, seed):
        if k < 1 or k > 4:
            raise StegoError("Bits per sample must be between 1 and 4.")
        self.k = k
        self.seed = seed
        self.k_bits = np.unpackbits(np.array([k], dtype=np.uint8))
        self.chunks = bits_to_chunks(stream_for(blob), k)
        self.pos = 0              # how many chunks we've written so far
        self.wrote_header = False
        self.index = 0            # which buffer (frame) we're on

    @property
    def done(self):
        return self.wrote_header and self.pos >= len(self.chunks)

    def process(self, buf):
        # changes buf in place
        if self.done:
            self.index += 1
            return

        order = permutation(self.seed, self.index, buf.size)
        self.index += 1
        start = 0

        if not self.wrote_header:
            if buf.size < HEADER_K_SLOTS:
                raise StegoError("Carrier too small.")
            idx = order[:HEADER_K_SLOTS]
            buf[idx] = (buf[idx] & ~np.array(1, dtype=buf.dtype)) | self.k_bits.astype(buf.dtype)
            self.wrote_header = True
            start = HEADER_K_SLOTS

        count = min(buf.size - start, len(self.chunks) - self.pos)
        if count > 0:
            idx = order[start:start + count]
            mask = np.array((1 << self.k) - 1, dtype=buf.dtype)
            values = self.chunks[self.pos:self.pos + count].astype(buf.dtype)
            buf[idx] = (buf[idx] & ~mask) | values
            self.pos += count


class LSBReader:
    def __init__(self, seed, max_bytes=None):
        self.seed = seed
        self.max_bytes = max_bytes
        self.k = None
        self.parts = []
        self.have = 0          # chunks read so far
        self.need = None       # total chunks (known once we read the length)
        self.length = 0
        self.index = 0
        self.blob = None

    @property
    def done(self):
        return self.blob is not None

    def process(self, buf):
        if self.done:
            return

        order = permutation(self.seed, self.index, buf.size)
        self.index += 1
        start = 0

        # first read k from the first 8 positions
        if self.k is None:
            kbits = (buf[order[:HEADER_K_SLOTS]] & 1).astype(np.uint8)
            self.k = int(np.packbits(kbits)[0])
            if self.k < 1 or self.k > 4:
                raise StegoError("No hidden data found (or wrong password).")
            start = HEADER_K_SLOTS

        mask = (1 << self.k) - 1
        while start < buf.size and not self.done:
            if self.need is None:
                target = (LEN_BITS + self.k - 1) // self.k   # just enough for the length
            else:
                target = self.need

            count = min(buf.size - start, target - self.have)
            if count > 0:
                self.parts.append((buf[order[start:start + count]] & mask).astype(np.uint16))
                self.have += count
                start += count

            if self.have < target:
                continue

            bits = chunks_to_bits(np.concatenate(self.parts), self.k)
            if self.need is None:
                self.length = struct.unpack(">I", bits_to_bytes(bits[:LEN_BITS]))[0]
                too_big = self.max_bytes is not None and self.length > self.max_bytes
                if self.length == 0 or too_big:
                    # wrong password gives a garbage length
                    raise StegoError("No hidden data found (or wrong password).")
                self.need = (LEN_BITS + 8 * self.length + self.k - 1) // self.k
            else:
                self.blob = bits_to_bytes(bits[LEN_BITS:LEN_BITS + 8 * self.length])
