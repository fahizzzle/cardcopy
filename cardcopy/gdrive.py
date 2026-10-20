"""What can be learned about Google Drive for desktop from the outside (Windows; a Mac uses mac/gdrive.py).
Read-only, no Qt.

Everything copied "to Google Drive" first lands in Drive's local cache and is uploaded from there, so the
drive that holds the cache needs the room, not the virtual G: drive (which reports the account's cloud quota).
The cache is no use as an "upload finished" signal: Drive keeps uploaded files in it as a local copy.
"""
from __future__ import annotations

import os
import shutil
import sys


def cache_dirs() -> list[str]:
    """The content cache folder of every signed-in account. Drive records a relocated cache in
    <account>\\content_cache_path; otherwise it is <account>\\content_cache."""
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "DriveFS")
    found = []
    try:
        accounts = [os.path.join(root, name) for name in os.listdir(root) if name.isdigit()]
    except OSError:
        return []
    for account in accounts:
        path = ""
        try:
            with open(os.path.join(account, "content_cache_path"), "rb") as f:
                path = f.read(2048).decode("utf-8", "replace").strip("\x00 \r\n")
        except OSError:
            pass
        if not (path and os.path.isdir(path)):
            path = os.path.join(account, "content_cache")
        if os.path.isdir(path):
            found.append(path)
    return found


def cache_free_space() -> tuple[int, str] | None:
    """(free bytes, drive) of the fullest drive that holds a Drive cache; None without Google Drive."""
    worst = None
    for path in cache_dirs():
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if worst is None or free < worst[0]:
            worst = (free, os.path.splitdrive(path)[0] or path)
    return worst


def effective_free_space(dest: str) -> tuple[int, str]:
    """(free bytes, the drive that actually limits it) for writing into dest.

    For a Google Drive destination that is the drive holding Drive's cache, not the virtual drive:
    everything written to G:\\ waits in that cache until Drive has uploaded it.
    """
    fallback = os.path.splitdrive(os.path.abspath(dest))[0] or dest
    if is_drive_path(dest):
        cache = cache_free_space()
        if cache is not None:
            return cache
    try:
        return shutil.disk_usage(dest).free, fallback
    except OSError:
        return 0, fallback


def is_drive_path(path: str) -> bool:
    """True for a folder on a Google Drive for desktop volume. Its label is no use (Windows cuts it to
    "name@gmail.com - G..."); the streamed volume always has a "My Drive" folder at its root."""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return bool(drive) and os.path.isdir(os.path.join(drive + os.sep, "My Drive")) and bool(cache_dirs())


def volume_name(path: str) -> str:
    """The drive a folder is on, the way a person would say it ("D:")."""
    return os.path.splitdrive(os.path.abspath(path))[0] or "that drive"


def same_volume(a: str, b: str) -> bool:
    """Both folders are on one drive, so they fill up together."""
    return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()


if sys.platform == "darwin":            # ~/Library/CloudStorage instead of a G: drive
    from .mac.gdrive import (cache_dirs, cache_free_space, default_raw_folder, effective_free_space,  # noqa: E402,F401,F811
                             is_drive_path, same_volume, volume_name)
