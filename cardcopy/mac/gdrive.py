"""What can be learned about Google Drive for desktop from the outside (macOS). Read-only, no Qt.

Current Drive for desktop is a macOS File Provider: My Drive is a real folder at
~/Library/CloudStorage/GoogleDrive-<account>/My Drive, on this Mac's own disk. Files written there take
room on that disk until Drive has uploaded them (and stay while they are kept offline), so the free space
that limits a copy is simply that disk's. Older versions mounted a virtual /Volumes/GoogleDrive that
reports the account's cloud quota instead; there, as on Windows, the disk holding Drive's cache counts.
"""
from __future__ import annotations

import glob
import os
import shutil

CLOUD_STORAGE = os.path.join("~", "Library", "CloudStorage")
DRIVEFS = os.path.join("~", "Library", "Application Support", "Google", "DriveFS")
LEGACY_VOLUME = "/Volumes/GoogleDrive"


def drive_roots() -> list[str]:
    """The top folder of every signed-in Google Drive account (each holds "My Drive")."""
    roots = sorted(glob.glob(os.path.join(os.path.expanduser(CLOUD_STORAGE), "GoogleDrive-*")))
    roots += sorted(glob.glob(LEGACY_VOLUME + "*"))
    return [r for r in roots if os.path.isdir(r)]


def default_raw_folder() -> str:
    """Where the Raw folder would be on this Mac: My Drive/Raw of the first account, or ''."""
    for root in drive_roots():
        my_drive = os.path.join(root, "My Drive")
        if os.path.isdir(my_drive):
            return os.path.join(my_drive, "Raw")
    return ""


def cache_dirs() -> list[str]:
    """The content cache folder of every signed-in account (only the legacy virtual volume uses it)."""
    root = os.path.expanduser(DRIVEFS)
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


def _mount_point(path: str) -> str:
    path = os.path.abspath(path)
    while not os.path.ismount(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


def volume_name(path: str) -> str:
    """The disk a folder is on, the way a person would say it: "this Mac" or the volume's name."""
    mount = _mount_point(path)
    if mount in ("/", "/System/Volumes/Data"):
        return "this Mac"
    return os.path.basename(mount) or mount


def same_volume(a: str, b: str) -> bool:
    """Both folders are on one disk, so they fill up together."""
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return _mount_point(a) == _mount_point(b)


def _legacy(path: str) -> bool:
    return os.path.abspath(path).startswith(LEGACY_VOLUME)


def cache_free_space() -> tuple[int, str] | None:
    """(free bytes, disk) of the fullest disk that holds a Drive cache; None without one."""
    worst = None
    for path in cache_dirs():
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if worst is None or free < worst[0]:
            worst = (free, volume_name(path))
    return worst


def effective_free_space(dest: str) -> tuple[int, str]:
    """(free bytes, the disk that actually limits it) for writing into dest."""
    if _legacy(dest):
        cache = cache_free_space()
        if cache is not None:
            return cache
    try:
        return shutil.disk_usage(dest).free, volume_name(dest)
    except OSError:
        return 0, volume_name(dest)


def is_drive_path(path: str) -> bool:
    """True for a folder inside a Google Drive for desktop account."""
    here = os.path.normcase(os.path.abspath(path))
    for root in drive_roots():
        root = os.path.normcase(os.path.abspath(root))
        if here == root or here.startswith(root + os.sep):
            return True
    return False
