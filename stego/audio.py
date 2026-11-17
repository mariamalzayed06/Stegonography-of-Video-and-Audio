# Audio: convert whatever the user gives us to 16-bit PCM with ffmpeg,
# hide in the LSBs of the samples, save as WAV.
# (MP3 output would destroy the hidden bits, so it's always WAV.)

import subprocess

import numpy as np
from scipy.io import wavfile

from .lsb import LSBReader, LSBWriter
from .payload import StegoError, capacity_bytes, chunks_needed, pack, position_seed, unpack


def load(path, temp_wav):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-acodec", "pcm_s16le", temp_wav]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise StegoError("Couldn't read this audio file: " + result.stderr.strip()[-300:])
    rate, data = wavfile.read(temp_wav)
    if data.dtype != np.int16:
        raise StegoError("Unsupported sample format.")
    return rate, data


def info(path, temp_wav):
    rate, data = load(path, temp_wav)
    channels = 1 if data.ndim == 1 else data.shape[1]
    return {
        "rate": int(rate),
        "channels": int(channels),
        "duration": round(len(data) / rate, 2),
        "samples": int(data.size),
        "capacity": {k: capacity_bytes(data.size, k) for k in (1, 2, 3, 4)},
    }


def hide(carrier, out_wav, temp_wav, secret, password="", k=1):
    rate, data = load(carrier, temp_wav)
    blob = pack(secret, password)
    cap = capacity_bytes(data.size, k)
    if len(blob) > cap:
        raise StegoError(f"Message too large: needs {len(blob):,} bytes but this audio only holds "
                         f"{cap:,} bytes at {k} bit(s) per sample. Use a longer file or more bits.")

    original = data.copy()
    samples = data.reshape(-1).view(np.uint16)   # same memory, so this edits data too
    writer = LSBWriter(blob, k, position_seed(password))
    writer.process(samples)
    wavfile.write(out_wav, rate, data)

    # signal-to-noise ratio, to show it can't be heard
    o = original.astype(np.float64).reshape(-1)
    s = data.astype(np.float64).reshape(-1)
    noise = np.sum((o - s) ** 2)
    snr = None if noise == 0 else round(float(10 * np.log10(np.sum(o ** 2) / noise)), 2)

    return {
        "rate": int(rate),
        "payload_bytes": len(blob),
        "capacity": cap,
        "used_percent": round(100 * len(blob) / cap, 3),
        "samples_changed": int(np.count_nonzero(o != s)),
        "samples_used": int(chunks_needed(len(blob), k) + 8),
        "snr_db": snr,
        "orig": original,
        "stego": data,
    }


def extract(stego_file, temp_wav, password=""):
    rate, data = load(stego_file, temp_wav)
    samples = data.reshape(-1).view(np.uint16)
    reader = LSBReader(position_seed(password), max_bytes=capacity_bytes(samples.size, 4))
    reader.process(samples)
    if not reader.done:
        raise StegoError("No hidden data found (or wrong password).")
    return unpack(reader.blob, password)
