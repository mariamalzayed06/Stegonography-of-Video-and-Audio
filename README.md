# StegoLab: Audio & Video Steganography (Project 19)

An educational web app that hides a text message or any file (for example a picture) inside an
**audio** or **video** carrier, and extracts it again. It also shows *why* the change cannot be
heard or seen: SNR/PSNR, waveform differences, bit tables, changed-pixel maps and LSB planes.

## Requirements

* Python 3.10+
* **FFmpeg** on the PATH (`ffmpeg` and `ffprobe`)
  * Windows: `winget install ffmpeg`, or download it from ffmpeg.org and add `bin` to PATH
  * macOS: `brew install ffmpeg`
  * Linux: `sudo apt install ffmpeg`
* Python packages: `pip install -r requirements.txt`

## Run

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

## Using it

1. **Hide** tab: upload a carrier (WAV, MP3, FLAC, OGG, M4A… or MP4, MKV, AVI, MOV, WEBM…). Type a
   message or choose a picture/file, optionally set a password, choose 1–4 bits per sample, then
   click *Hide the secret*. Download the result:
   * audio → `*_stego.wav` (16-bit PCM)
   * video → `*_stego.mkv` (lossless FFV1 video; the original audio track is kept)
2. **Extract** tab: upload that `.wav` / `.mkv` file with the same password to get the message or
   picture back.
3. **Try to detect it** tab: runs the chi-square steganalysis attack on any file and shows a
   p-value curve. Clean files and small scattered payloads usually pass; filling the whole
   capacity gets caught.
4. **How it works** and **Methods** tabs: an interactive bit demo and a comparison of the methods.

> The output must stay lossless. Converting the stego WAV to MP3, or the MKV to MP4, or sending it
> through WhatsApp or YouTube, re-compresses it and destroys the hidden bits.

## Method (both carriers)

Randomized LSB substitution with encryption:

1. The secret is zlib-compressed and stored with its file name.
2. With a password, a key is derived using PBKDF2-HMAC-SHA256 (200k iterations) and the data is
   sealed with AES-256-GCM, which also detects a wrong password or tampering.
3. A 32-bit length header is prepended. The bits-per-sample value *k* is stored in the first 8 slots.
4. A password-seeded PRNG permutes the sample or pixel positions, so changes are scattered across the carrier.
5. The *k* least-significant bits of each selected sample are replaced.
   * Audio: 16-bit PCM samples (all channels interleaved).
   * Video: R, G and B bytes of each decoded frame. Each frame has its own permutation, and the
     message spills into the next frame only when one frame is full.
6. The result is written losslessly (WAV / FFV1-MKV).

## Project layout

```
app.py              Flask web server and JSON API
stego/payload.py    packing, compression, AES-GCM, bit helpers
stego/lsb.py        generic randomized-LSB writer/reader
stego/audio.py      audio carrier (ffmpeg → PCM → LSB → WAV)
stego/video.py      video carrier (ffmpeg frame pipes → LSB → FFV1/MKV)
stego/visuals.py    educational figures
stego/analysis.py   chi-square steganalysis (the "Try to detect it" tab)
templates/, static/ web interface
tests/test_roundtrip.py  automated tests (python -m pytest or python tests/test_roundtrip.py)
```

## API (used by the page)

| Endpoint | Form fields | Returns |
|---|---|---|
| `POST /api/info` | `carrier` | duration/resolution and capacity for k = 1…4 |
| `POST /api/hide` | `carrier`, `message` or `secret_file`, `password`, `bits` | metrics, figures, download link |
| `POST /api/extract` | `carrier`, `password` | text, or a link to the recovered file |
| `POST /api/analyze` | `carrier` | chi-square verdict, p-values and a plot |
