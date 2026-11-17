# Pictures for the results page (waveform plot, bit table, frame images).
# Everything is returned as base64 PNG so the browser can show it directly.

import base64
import io

import matplotlib
matplotlib.use("Agg")   # no window, just save to memory
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

DARK = "#0e2a47"
BLUE = "#1d5fd1"
GREY = "#9aa8b8"


def fig_to_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def array_to_png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def audio_figures(orig, stego, rate):
    # only plot the first channel
    if orig.ndim > 1:
        orig, stego = orig[:, 0], stego[:, 0]
    o = orig.astype(np.int32)
    s = stego.astype(np.int32)
    diff = s - o

    # zoom in on 400 samples around a place where something changed
    changed = np.flatnonzero(diff)
    if len(changed) > 0:
        middle = int(changed[len(changed) // 2])
    else:
        middle = len(o) // 2
    a = max(0, middle - 200)
    b = min(len(o), middle + 200)
    t = np.arange(a, b) / rate * 1000

    fig, ax = plt.subplots(3, 1, figsize=(9, 6.2), sharex=True)
    ax[0].plot(t, o[a:b], color=DARK, lw=1)
    ax[0].set_title("Original waveform (400 samples, channel 1)", loc="left", fontsize=10)
    ax[1].plot(t, s[a:b], color=BLUE, lw=1)
    ax[1].set_title("With the secret - looks the same", loc="left", fontsize=10)
    ax[2].stem(t, diff[a:b], linefmt=BLUE, markerfmt=" ", basefmt=GREY)
    ax[2].set_title("Difference (after minus before)", loc="left", fontsize=10)
    ax[2].set_xlabel("time (ms)")
    for x in ax:
        x.spines[["top", "right"]].set_visible(False)
        x.tick_params(labelsize=8)
    wave = fig_to_png(fig)

    # bits of the first 8 samples that changed
    rows = []
    indexes = changed[:8] if len(changed) > 0 else range(a, a + 8)
    for i in indexes:
        rows.append({
            "index": int(i),
            "orig": int(o[i]),
            "stego": int(s[i]),
            "orig_bits": format(int(o[i]) & 0xFFFF, "016b"),
            "stego_bits": format(int(s[i]) & 0xFFFF, "016b"),
        })
    return {"wave": wave, "bit_rows": rows}


def video_figures(orig, stego, k):
    # shrink big frames so the page doesn't get huge
    h, w, _ = orig.shape
    step = max(1, int(np.ceil(max(h, w) / 480)))
    o = orig[::step, ::step]
    s = stego[::step, ::step]

    changed = (o != s).any(axis=2)
    diff_img = np.full(o.shape, 255, dtype=np.uint8)
    diff_img[changed] = [29, 95, 209]   # changed pixels in blue

    # last bit of the green channel, as black/white
    lsb_before = ((o[:, :, 1] & 1) * 255).astype(np.uint8)
    lsb_after = ((s[:, :, 1] & 1) * 255).astype(np.uint8)

    return {
        "orig": array_to_png(o),
        "stego": array_to_png(s),
        "diff": array_to_png(diff_img),
        "lsb_orig": array_to_png(lsb_before),
        "lsb_stego": array_to_png(lsb_after),
        "changed_pixels_percent": round(100 * float(changed.mean()), 3),
    }
