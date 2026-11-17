# Steganography website - EECE 455 Project 19
# Flask server for hiding messages/pictures in audio and video.
# Run: python app.py   then open http://127.0.0.1:5000

import glob
import mimetypes
import os
import shutil
import tempfile
import time
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from stego import Secret, StegoError, audio, video
from stego.visuals import audio_figures, video_figures

AUDIO_EXT = [".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"]
VIDEO_EXT = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg"]

# every request gets its own folder in temp, old ones get deleted after 2 hours
JOBS_DIR = os.path.join(tempfile.gettempdir(), "stegolab_jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024   # 1 GB max upload


def find_ffmpeg_folder():
    # places ffmpeg usually ends up on Windows (winget, manual unzip, or inside this project)
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.environ.get("LOCALAPPDATA", "")
    places = [
        os.path.join(here, "ffmpeg", "bin"),
        os.path.join(here, "ffmpeg"),
        os.path.join(local, "Microsoft", "WinGet", "Links"),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
    ]
    places += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin"))
    places += glob.glob(os.path.join(here, "ffmpeg*", "bin"))
    places += glob.glob(r"C:\ffmpeg*\bin") + glob.glob(r"C:\ffmpeg\*\bin")
    for folder in places:
        if os.path.isfile(os.path.join(folder, "ffmpeg.exe")) and os.path.isfile(os.path.join(folder, "ffprobe.exe")):
            return folder
    return None


def check_ffmpeg():
    # if ffmpeg isn't on PATH, look for it ourselves and add it
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        folder = find_ffmpeg_folder()
        if folder:
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            print("  Using FFmpeg from " + folder)

    missing = []
    for tool in ["ffmpeg", "ffprobe"]:
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        print()
        print("  This app needs FFmpeg but couldn't find: " + ", ".join(missing))
        print("  Install it, open a NEW terminal, and run app.py again:")
        print("    Windows: winget install Gyan.FFmpeg")
        print("             or unzip ffmpeg into a folder called 'ffmpeg' next to app.py")
        print("    macOS:   brew install ffmpeg")
        print("    Linux:   sudo apt install ffmpeg")
        print()
        raise SystemExit(1)


def new_job():
    delete_old_jobs()
    job_id = uuid.uuid4().hex
    folder = os.path.join(JOBS_DIR, job_id)
    os.makedirs(folder)
    return job_id, folder


def delete_old_jobs():
    now = time.time()
    for name in os.listdir(JOBS_DIR):
        path = os.path.join(JOBS_DIR, name)
        if os.path.isdir(path) and now - os.path.getmtime(path) > 2 * 3600:
            shutil.rmtree(path, ignore_errors=True)


def save_upload(field, folder):
    f = request.files.get(field)
    if f is None or f.filename == "":
        raise StegoError("Please choose a file.")
    name = secure_filename(f.filename) or "upload.bin"
    path = os.path.join(folder, "in_" + name)
    f.save(path)
    return path, name


def get_kind(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    # fall back to what the page told us (if it read the file before)
    hint = request.form.get("kind")
    if hint in ["audio", "video"]:
        return hint
    raise StegoError(f"Unsupported file type '{ext}'. Use an audio file (WAV, MP3, FLAC...) "
                     f"or a video file (MP4, MKV, AVI, MOV...).")


def nice_size(n):
    if n < 1024:
        return f"{n} B"
    for unit in ["KB", "MB", "GB"]:
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}"


@app.errorhandler(StegoError)
def handle_stego_error(e):
    return jsonify({"ok": False, "error": str(e)}), 400


@app.errorhandler(413)
def handle_too_big(e):
    return jsonify({"ok": False, "error": "File too large (limit is 1 GB)."}), 413


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/info")
def api_info():
    # called as soon as the user picks a carrier, to show capacity
    job_id, folder = new_job()
    path, name = save_upload("carrier", folder)
    kind = get_kind(name)
    if kind == "audio":
        info = audio.info(path, os.path.join(folder, "work.wav"))
    else:
        info = video.info(path)
    shutil.rmtree(folder, ignore_errors=True)

    info["kind"] = kind
    info["capacity_h"] = {}
    for k, v in info["capacity"].items():
        info["capacity_h"][k] = nice_size(v)
    info["ok"] = True
    return jsonify(info)


@app.post("/api/hide")
def api_hide():
    job_id, folder = new_job()
    path, name = save_upload("carrier", folder)
    kind = get_kind(name)
    password = request.form.get("password", "")
    try:
        k = int(request.form.get("bits", 1))
    except ValueError:
        k = 1

    # secret is either an uploaded file or the typed message
    secret_file = request.files.get("secret_file")
    if secret_file is not None and secret_file.filename:
        secret = Secret(secret_file.read(), True, secure_filename(secret_file.filename) or "secret.bin")
    else:
        message = request.form.get("message", "")
        if message.strip() == "":
            raise StegoError("Type a message or choose a file/picture to hide.")
        secret = Secret(message.encode("utf-8"), False)

    base = os.path.splitext(name)[0]
    start = time.time()

    if kind == "audio":
        out_name = base + "_stego.wav"
        out_path = os.path.join(folder, out_name)
        result = audio.hide(path, out_path, os.path.join(folder, "work.wav"), secret, password, k)
        figures = audio_figures(result.pop("orig"), result.pop("stego"), result["rate"])
        preview = f"/files/{job_id}/{out_name}"
        metric = {"label": "SNR", "value": result["snr_db"], "unit": "dB"}
    else:
        out_name = base + "_stego.mkv"
        out_path = os.path.join(folder, out_name)
        result = video.hide(path, out_path, secret, password, k)
        before, after = result.pop("first_frame")
        figures = video_figures(before, after, k)
        video.preview_mp4(out_path, os.path.join(folder, "preview.mp4"))
        preview = f"/files/{job_id}/preview.mp4"
        metric = {"label": "PSNR", "value": result["psnr_db"], "unit": "dB"}

    in_size = os.path.getsize(path)
    out_size = os.path.getsize(out_path)
    os.remove(path)

    return jsonify({
        "ok": True,
        "kind": kind,
        "seconds": round(time.time() - start, 2),
        "download": f"/files/{job_id}/{out_name}?dl=1",
        "filename": out_name,
        "preview": preview,
        "metric": metric,
        "stats": result,
        "figures": figures,
        "encrypted": password != "",
        "secret_size": nice_size(len(secret.data)),
        "in_size": nice_size(in_size),
        "out_size": nice_size(out_size),
        "bits": k,
    })


@app.post("/api/extract")
def api_extract():
    job_id, folder = new_job()
    path, name = save_upload("carrier", folder)
    kind = get_kind(name)
    password = request.form.get("password", "")

    if kind == "audio":
        secret = audio.extract(path, os.path.join(folder, "work.wav"), password)
    else:
        secret = video.extract(path, password)
    os.remove(path)

    if not secret.is_file:
        return jsonify({"ok": True, "type": "text", "text": secret.text, "size": nice_size(len(secret.data))})

    # it was a file -> save it so the page can show/download it
    file_name = secure_filename(secret.name) or "secret.bin"
    with open(os.path.join(folder, file_name), "wb") as f:
        f.write(secret.data)
    mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    return jsonify({
        "ok": True,
        "type": "file",
        "filename": file_name,
        "mime": mime,
        "size": nice_size(len(secret.data)),
        "url": f"/files/{job_id}/{file_name}",
        "download": f"/files/{job_id}/{file_name}?dl=1",
    })


@app.get("/files/<job_id>/<file_name>")
def get_file(job_id, file_name):
    if not job_id.isalnum():
        abort(404)
    path = os.path.join(JOBS_DIR, job_id, secure_filename(file_name))
    if not os.path.isfile(path):
        abort(404)
    download = request.args.get("dl") == "1"
    return send_file(path, as_attachment=download, download_name=file_name, conditional=True)


if __name__ == "__main__":
    check_ffmpeg()
    print("  The site is running -> open http://127.0.0.1:5000  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)