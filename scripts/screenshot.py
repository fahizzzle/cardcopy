"""Open CardCopy on made-up cards and save pictures of the window, without touching a real card.

    python scripts/screenshot.py OUT_DIR [--appearance light|dark|both] [--size 1320x860]

Three fake cards are made in a temporary folder -- a Sony FX3 video card, an A7 IV photo card and a
Zoom recorder -- and added as folder sources, so the window shows what it would with cameras plugged in.
Used by the Mac build (scripts/build_mac.sh) to show the real macOS rendering, and on Windows with
CARDCOPY_THEME=mac to check the Mac layout. Settings live in the temporary folder too: nothing of the
user's is read or written.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _tiff(make: str, model: str) -> bytes:
    """The smallest TIFF header naming a camera: what identify.read_exif looks for in a RAW file."""
    entries = []
    blobs = b""
    base = 8 + 2 + 2 * 12 + 4
    for tag, text in ((0x010F, make), (0x0110, model)):
        raw = text.encode() + b"\0"
        entries.append(struct.pack("<HHII", tag, 2, len(raw), base + len(blobs)))
        blobs += raw
    return b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", len(entries)) + b"".join(entries) + b"\0\0\0\0" + blobs


def make_cards(root: str) -> list[str]:
    fx3 = os.path.join(root, "FX3 card")
    clips = os.path.join(fx3, "PRIVATE", "M4ROOT", "CLIP")
    os.makedirs(clips)
    with open(os.path.join(fx3, "PRIVATE", "M4ROOT", "MEDIAPRO.XML"), "w") as f:
        f.write('<MediaProfile><Properties><System systemId="5051234" systemKind="ILME-FX3"/></Properties></MediaProfile>')
    for n in range(1, 13):
        with open(os.path.join(clips, f"C{n:04d}.MP4"), "wb") as f:
            f.truncate(3_000_000 + n * 50_000)
        with open(os.path.join(clips, f"C{n:04d}M01.XML"), "w") as f:
            f.write("<NonRealTimeMeta/>")
    a7 = os.path.join(root, "A7 IV card")
    dcim = os.path.join(a7, "DCIM", "100MSDCF")
    os.makedirs(dcim)
    for n in range(1, 41):
        with open(os.path.join(dcim, f"DSC{n:05d}.ARW"), "wb") as f:
            f.write(_tiff("SONY", "ILCE-7M4"))
            f.truncate(2_400_000)
        if n % 2:
            with open(os.path.join(dcim, f"DSC{n:05d}.JPG"), "wb") as f:
                f.truncate(600_000)
    zoom = os.path.join(root, "Zoom card")
    folder = os.path.join(zoom, "FOLDER01")
    os.makedirs(folder)
    for n in range(1, 5):
        write_wav(os.path.join(folder, f"ZOOM{n:04d}.WAV"), "ZOOM F6", 1_500_000 * n)
    return [fx3, a7, zoom]


def write_wav(path: str, originator: str = "", size: int = 1_500_000) -> None:
    """A WAV header the way a field recorder writes one (BWF originator, 48 kHz 24-bit stereo), padded to
    `size` bytes: what identify reads the recorder's name and the recording's length from."""
    bext = b"Interview".ljust(256, b"\0") + originator.encode().ljust(32, b"\0") + b"\0" * 314
    fmt = struct.pack("<HHIIHH", 1, 2, 48000, 48000 * 2 * 3, 6, 24)
    head = (b"bext" + struct.pack("<I", len(bext)) + bext if originator else b"") + \
        b"fmt " + struct.pack("<I", len(fmt)) + fmt
    sound = size - 12 - len(head) - 8
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", size - 8) + b"WAVE" + head + b"data" + struct.pack("<I", sound))
        f.truncate(size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--appearance", default="both", choices=("light", "dark", "both"))
    parser.add_argument("--size", default="1320x860")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cardcopy-shot-")
    raw = os.path.join(work, "Raw")
    os.makedirs(raw)
    cards = make_cards(os.path.join(work, "cards"))
    home = os.path.join(work, "home")
    os.makedirs(home)
    with open(os.path.join(home, "settings.json"), "w") as f:
        json.dump({"base": raw, "folders": cards, "kinds": {"photo": True, "video": True, "audio": True},
                   "receipt": True, "eject_after": True}, f)
    os.environ.update(CARDCOPY_HOME=home, CARDCOPY_NO_DEVICES="1", CARDCOPY_NO_UPDATE_CHECK="1",
                      CARDCOPY_NO_SHUTDOWN="1", CARDCOPY_ASSUME_ONLINE="1", CARDCOPY_NO_ANIMATION="1")
    appearances = ["light", "dark"] if args.appearance == "both" else [args.appearance]

    from PySide6.QtWidgets import QApplication
    width, height = (int(n) for n in args.size.lower().split("x"))
    saved = []
    app = None
    for appearance in appearances:
        os.environ["CARDCOPY_APPEARANCE"] = appearance
        if app is None:
            app = QApplication([])
            from cardcopy import ui
            from cardcopy.theme import install
            install(app)
        else:
            from cardcopy import theme
            if theme.MAC:
                from cardcopy.aqua import apply_appearance
                apply_appearance(app)
        window = ui.MainWindow()
        window.resize(width, height)
        window.project_edit.setText("Nour/Reception")
        window.show()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and (window.scanning or not window.panels):
            app.processEvents()
            time.sleep(0.02)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        path = os.path.join(args.out, f"cardcopy-{appearance}.png")
        window.grab().save(path)
        saved.append(path)
        if sys.platform == "darwin":             # the real thing, title bar and vibrancy included
            import subprocess
            window.raise_()
            window.activateWindow()
            for _ in range(20):
                app.processEvents()
                time.sleep(0.05)
            screen = os.path.join(args.out, f"screen-{appearance}.png")
            subprocess.run(["screencapture", "-x", screen], check=False)
            if os.path.exists(screen):
                saved.append(screen)
        window.close()
    print("\n".join(saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
