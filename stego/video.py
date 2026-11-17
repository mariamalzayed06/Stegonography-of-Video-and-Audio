# Video: ffmpeg decodes the frames to raw RGB bytes, we change the LSBs,
# and ffmpeg saves them again with FFV1 (lossless) in an .mkv.
# The original sound track is copied over.
# We go frame by frame through pipes so big videos don't fill up the RAM.

import json
import subprocess

import numpy as np

from .lsb import LSBReader, LSBWriter
from .payload import StegoError, capacity_bytes, pack, position_seed, unpack


def probe(path):
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise StegoError("Couldn't read this video file.")
    meta = json.loads(result.stdout)

    v = None
    has_audio = False
    for s in meta["streams"]:
        if s.get("codec_type") == "video" and v is None:
            v = s
        if s.get("codec_type") == "audio":
            has_audio = True
    if v is None:
        raise StegoError("No video stream found in this file.")

    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "25/1").split("/")
    if float(den) == 0 or float(num) == 0:
        num, den = (v.get("r_frame_rate") or "25/1").split("/")
    fps = float(num) / float(den)

    duration = float(meta.get("format", {}).get("duration", 0) or 0)
    frames = int(v.get("nb_frames") or 0)
    if frames == 0:
        frames = int(round(duration * fps))

    return {
        "width": int(v["width"]), "height": int(v["height"]),
        "fps": fps, "fps_str": f"{num}/{den}",
        "duration": round(duration, 2), "frames": frames,
        "codec": v.get("codec_name"), "has_audio": has_audio,
    }


def info(path):
    p = probe(path)
    per_frame = p["width"] * p["height"] * 3
    total = per_frame * max(p["frames"], 1)
    p["capacity"] = {k: capacity_bytes(total, k) for k in (1, 2, 3, 4)}
    p["capacity_per_frame"] = {k: capacity_bytes(per_frame, k) for k in (1, 2, 3, 4)}
    return p


def _decoder(path, w, h):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 6)


def _frames(proc, w, h):
    size = w * h * 3
    while True:
        raw = proc.stdout.read(size)
        if len(raw) < size:
            return
        yield np.frombuffer(raw, dtype=np.uint8).copy()


def hide(carrier, out_mkv, secret, password="", k=1):
    p = probe(carrier)
    w, h = p["width"], p["height"]
    blob = pack(secret, password)
    cap = capacity_bytes(w * h * 3 * max(p["frames"], 1), k)
    if len(blob) > cap:
        raise StegoError(f"Message too large: needs {len(blob):,} bytes but this video holds about "
                         f"{cap:,} bytes at {k} bit(s) per channel.")

    enc_cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", p["fps_str"], "-i", "-"]
    if p["has_audio"]:
        enc_cmd += ["-i", carrier, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy"]
    enc_cmd += ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp", out_mkv]

    encoder = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    decoder = _decoder(carrier, w, h)
    writer = LSBWriter(blob, k, position_seed(password))

    mse_total = 0.0
    frames_used = 0
    n = 0
    first_frame = None
    try:
        for frame in _frames(decoder, w, h):
            if writer.done:
                writer.process(frame)   # nothing to write, just counts the frame
            else:
                before = frame.copy()
                writer.process(frame)
                frames_used += 1
                diff = before.astype(np.float64) - frame.astype(np.float64)
                mse_total += float(np.mean(diff ** 2))
                if first_frame is None:
                    first_frame = (before.reshape(h, w, 3), frame.reshape(h, w, 3).copy())
            encoder.stdin.write(frame.tobytes())
            n += 1
    finally:
        encoder.stdin.close()
        decoder.stdout.close()
        decoder.wait()
        err = encoder.stderr.read().decode(errors="replace")
        encoder.wait()

    if encoder.returncode != 0:
        raise StegoError("Encoding failed: " + err[-300:])
    if not writer.done:
        raise StegoError("The video ended before the whole message was written. Try more bits per channel.")

    mse = mse_total / max(frames_used, 1)
    psnr = None if mse == 0 else round(10 * np.log10(255 ** 2 / mse), 2)
    return {
        "width": w, "height": h, "frames": n, "frames_used": frames_used,
        "payload_bytes": len(blob), "capacity": cap,
        "used_percent": round(100 * len(blob) / cap, 4),
        "psnr_db": psnr, "first_frame": first_frame,
    }


def extract(stego_file, password=""):
    p = probe(stego_file)
    w, h = p["width"], p["height"]
    decoder = _decoder(stego_file, w, h)
    reader = LSBReader(position_seed(password), max_bytes=capacity_bytes(w * h * 3 * max(p["frames"], 1), 4))
    try:
        for frame in _frames(decoder, w, h):
            reader.process(frame)
            if reader.done:
                break   # no need to read the rest of the video
    finally:
        decoder.kill()
        decoder.wait()
    if not reader.done:
        raise StegoError("No hidden data found (or wrong password).")
    return unpack(reader.blob, password)


def preview_mp4(src_mkv, dst_mp4, max_seconds=30):
    # small normal mp4 just so the browser can play it (the secret does NOT survive this)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src_mkv, "-t", str(max_seconds),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-movflags", "+faststart", dst_mp4]
    subprocess.run(cmd, capture_output=True)
