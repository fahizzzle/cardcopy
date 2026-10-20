"""'A new version is available' on launch. No Qt in here.

CardCopy cannot be pushed to; it asks. Once per launch it reads one small JSON file from UPDATE_URL:

    {"version": "1.12.2", "url": "https://.../CardCopy-Setup.exe",
     "zip": "https://.../CardCopy-Setup.zip", "sha256": "<of that zip>",
     "notes": "What is new, one or two lines"}

and compares "version" with its own. Publishing an update = uploading the new Setup and editing that file.
Only https addresses are accepted, and nothing happens until the user presses Update now or Download.

"zip" and "sha256" are what let CardCopy update itself (see selfupdate.py). The zip is the script
installer, which contains no executable of ours; that is the point, because antivirus quarantines
every freshly built unsigned exe — including one CardCopy downloaded for itself. What is downloaded
is checked against sha256 before anything runs. Without those two fields, or when CardCopy is not
running from an install, the Setup link is handed to the browser as before.

Any failure of the check itself (offline, bad file) is silent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import urllib.request
from dataclasses import dataclass
from typing import Callable

# Where latest.json lives: an asset of the newest GitHub release (scripts/release.ps1 uploads it). Empty = never check.
# A Mac reads its own latest-mac.json beside it, whose "url" is the Mac download: a release without one is
# simply not offered to Macs (the check fails quietly, as when offline).
UPDATE_URL = "https://github.com/fahizzzle/cardcopy/releases/latest/download/" + \
    ("latest-mac.json" if sys.platform == "darwin" else "latest.json")


@dataclass
class Update:
    version: str
    url: str                # the Setup.exe, for the browser
    notes: str = ""
    zip_url: str = ""       # the script installer, for updating in place
    sha256: str = ""        # of the zip; without it the zip is not trusted and is not used

    def can_self_install(self) -> bool:
        return bool(self.zip_url and self.sha256)


def version_key(text: str) -> tuple[int, ...]:
    """'1.10.2' -> (1, 10, 2), so that 1.10 is newer than 1.9."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:4])


def _allowed(url: str, allow_file: bool = False) -> bool:
    return url.startswith("https://") or (allow_file and url.startswith("file:///"))


def parse(raw: str, current: str, allow_file: bool = False) -> Update | None:
    """The update described by latest.json, or None when it is not newer or not trustworthy."""
    try:
        data = json.loads(raw)
        version, url = str(data["version"]).strip(), str(data["url"]).strip()
    except (ValueError, KeyError, TypeError):
        return None
    if not version_key(version) or version_key(version) <= version_key(current) or not _allowed(url, allow_file):
        return None
    zip_url = str(data.get("zip", "")).strip()
    sha = str(data.get("sha256", "")).strip().lower()
    if not _allowed(zip_url, allow_file) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        zip_url, sha = "", ""          # half a description is no description: fall back to the browser
    return Update(version, url, str(data.get("notes", "")).strip()[:600], zip_url, sha)


class WrongFile(Exception):
    """What was downloaded is not what latest.json described. Nothing is run."""


def download(update: Update, into: str, on_progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None, timeout: float = 30.0) -> str:
    """Fetch the update's zip into `into` and check it against sha256. Returns the file's path.

    Blocking; call it from a worker thread. The file is written with an exclusive create, so it can
    never land on top of something already there, and a download that does not match the published
    checksum is kept as .bad rather than used.
    """
    if not update.can_self_install():
        raise WrongFile("this update does not publish a checksummed zip")
    os.makedirs(into, exist_ok=True)
    path = os.path.join(into, f"CardCopy-{update.version}-Setup.zip")
    request = urllib.request.Request(update.zip_url, headers={"User-Agent": f"CardCopy/{update.version}"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(path, "xb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    raise WrongFile("cancelled")
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    if digest.hexdigest() != update.sha256:
        bad = path + ".bad"
        if not os.path.exists(bad):
            os.rename(path, bad)
        raise WrongFile(f"the download does not match the published checksum; kept as {os.path.basename(bad)}")
    return path


def check(current: str, url: str | None = None, timeout: float = 6.0) -> Update | None:
    """Blocking; call it from a worker thread. None means: nothing to tell the user."""
    override = os.environ.get("CARDCOPY_UPDATE_URL")            # for testing a release before publishing it
    url = url or override or UPDATE_URL
    if not url or os.environ.get("CARDCOPY_NO_UPDATE_CHECK") or not _allowed(url, allow_file=bool(override)):
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": f"CardCopy/{current}", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(65536).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    return parse(raw, current, allow_file=bool(override))
