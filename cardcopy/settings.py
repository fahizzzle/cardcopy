"""Remembered choices: %APPDATA%\\CardCopy\\settings.json on Windows,
~/Library/Application Support/CardCopy/settings.json on a Mac (or CARDCOPY_HOME)."""
from __future__ import annotations

import json
import os
import sys

from .structure import DEFAULT_BASE, DEFAULT_KIND_FOLDERS

DEFAULTS = {
    "base": DEFAULT_BASE,
    "spill": False,         # when the Raw folder fills up, carry on in spill_base instead of waiting
    "spill_base": "",       # the backup folder; the same Raw Photo/Video/Audio layout is made inside it
    "kind_folders": dict(DEFAULT_KIND_FOLDERS),
    "kinds": {"photo": True, "video": True, "audio": False},   # audio ticks itself when a recorder turns up
    # Where recordings go: "with_video" = Raw Video\<project>\Audio, beside the footage they belong to;
    # "raw_audio" = Raw Audio\<project>\Cam N. (A new name: an older "audio_in_video": false is not carried over.)
    "audio_place": "with_video",
    "copy_jpeg": False,     # photos: RAW only unless this is on
    "copy_xml": False,      # video: clips only unless this is on
    "cam_counts": {"photo": 0, "video": 0, "audio": 0},   # Cam folders per Raw folder; 0 = one per device
    "cam_assign": {},       # camera identity -> Cam number
    "cam_kind": {},         # camera identity -> "photo" | "video" (default comes from the model)
    "mode": "cameras",      # or "cards": every SD card listed on its own
    "camera_names": {},
    "camera_pictures": {},  # camera identity -> image path
    "verify": False,
    "check_updates": True,  # look for a newer version on launch (needs updates.UPDATE_URL)
    "skipped_version": "",  # "Skip this version" in the update notice
    "receipt": False,       # save an offload receipt in the project folder after a copy (off unless switched on)
    "eject_after": False,   # eject the cards after a clean copy, and before an automatic shutdown
    "show_empty": False,    # list cards that hold nothing to copy
    "shutdown_mode": "copy",  # "copy" | "drive" | "time" | "at"; the shutdown switch itself is never remembered
    "shutdown_minutes": 60,
    "shutdown_at": "02:00",   # clock time for the "at a set time" option
    "folders": [],
    "kept_copies": [],        # Mac: other CardCopy.app copies the user chose to keep (asked once, not again)
}


def settings_path() -> str:
    home = os.environ.get("CARDCOPY_HOME")
    if not home and sys.platform == "darwin":
        home = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "CardCopy")
    home = home or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "CardCopy")
    return os.path.join(home, "settings.json")


def load() -> dict:
    data = json.loads(json.dumps(DEFAULTS))
    try:
        with open(settings_path(), encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            # a file written by an older CardCopy has no "audio" in these: keep the new defaults for
            # whatever it does not mention instead of dropping them
            for name in ("kind_folders", "kinds", "cam_counts"):
                if isinstance(stored.get(name), dict):
                    stored[name] = {**DEFAULTS[name], **stored[name]}
            data.update(stored)
    except (OSError, ValueError):
        pass
    if data["base"] == DEFAULT_BASE and not os.path.isdir(DEFAULT_BASE):
        data["base"] = ""          # someone else's PC: let them pick their own Raw folder
    return data


def save(data: dict) -> None:
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
