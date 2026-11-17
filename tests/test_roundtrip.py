# Quick tests: hide then extract, check we get the same thing back. Needs ffmpeg.
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stego import Secret, StegoError, audio, video  # noqa: E402

TMP = tempfile.mkdtemp()


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def p(name):
    return os.path.join(TMP, name)


def setup_media():
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-ac", "2", "-ar", "44100", p("tone.mp3"))
    ff("-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25", "-f", "lavfi", "-i",
       "sine=frequency=300:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       p("clip.mp4"))


def test_audio():
    for k in (1, 2, 3, 4):
        for pw in ("", "secret"):
            msg = Secret("Hello, world! مرحبا 🔐".encode(), False)
            audio.hide(p("tone.mp3"), p("a.wav"), p("w.wav"), msg, pw, k)
            assert audio.extract(p("a.wav"), p("w2.wav"), pw).data == msg.data
    blob = os.urandom(20000)
    audio.hide(p("tone.mp3"), p("a.wav"), p("w.wav"), Secret(blob, True, "x.bin"), "pw", 2)
    s = audio.extract(p("a.wav"), p("w2.wav"), "pw")
    assert s.data == blob and s.name == "x.bin"
    try:
        audio.extract(p("a.wav"), p("w2.wav"), "wrong")
        raise AssertionError("wrong password accepted")
    except StegoError:
        pass


def test_video():
    for k in (1, 3):
        blob = os.urandom(300000)  # bigger than one frame at k=1 -> spans frames
        video.hide(p("clip.mp4"), p("v.mkv"), Secret(blob, True, "big.bin"), "pw", k)
        assert video.extract(p("v.mkv"), "pw").data == blob
    try:
        video.extract(p("v.mkv"), "nope")
        raise AssertionError("wrong password accepted")
    except StegoError:
        pass


def test_too_big():
    try:
        audio.hide(p("tone.mp3"), p("a.wav"), p("w.wav"), Secret(os.urandom(500000), True, "b"), "", 1)
        raise AssertionError("oversized message accepted")
    except StegoError:
        pass


setup_media()

if __name__ == "__main__":
    for t in (test_audio, test_video, test_too_big):
        t()
        print("PASS", t.__name__)