"""Keep one CardCopy on a Mac: the one in Applications. No Qt in here.

An update always installs into /Applications (that is where CardCopy-Installer.pkg puts it). A copy run
from anywhere else -- Downloads, the Desktop, the opened .dmg -- is then left behind, and the Mac has two
CardCopys, only one of them current. So the window (mac_window.tidy_copies) asks to keep just the one in
Applications, and an update moves the copy it replaced to the Trash.

Copies are only ever moved to the Trash, from where they can be put back; nothing is deleted. A copy on a
disk image or another disk (/Volumes/...) is never touched: that is the download, not an install.
"""
from __future__ import annotations

import os
import plistlib
import subprocess

APP = "/Applications/CardCopy.app"
BUNDLE_ID = "com.framedhorizon.cardcopy"


def version_of(app: str) -> str:
    """'1.20.1 (build 32)' from a copy's Info.plist, or '' when it cannot be read."""
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
    except Exception:            # plistlib raises several unrelated types on a damaged file
        return ""
    short, full = str(info.get("CFBundleShortVersionString", "")), str(info.get("CFBundleVersion", ""))
    build = full.rsplit(".", 1)[-1] if full.count(".") >= 3 else ""
    return f"{short} (build {build})" if build and build != "0" else short


def removable_media(path: str) -> bool:
    """On a disk image or another disk: the download, not an install. Never moved."""
    return path.startswith("/Volumes/")


def _in_trash(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return ".Trash" in parts or ".Trashes" in parts


def other_copies(me: str) -> list[str]:
    """Every other CardCopy.app Spotlight knows of on this Mac's own disk, not counting the Trash."""
    try:
        out = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{BUNDLE_ID}'"], capture_output=True,
                             text=True, timeout=15, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = set()
    for line in out.splitlines():
        path = line.strip().rstrip("/")
        if (path.endswith(".app") and path != me.rstrip("/") and os.path.isdir(path)
                and not removable_media(path) and not _in_trash(path) and ".app/" not in path):
            found.add(path)
    return sorted(found)


def to_trash(path: str) -> bool:
    """Move a copy of CardCopy to the Trash (Finder's Put Back works when macOS does it). True when it went."""
    if removable_media(path) or not os.path.isdir(path):
        return False
    from .native import trash
    if trash(path):
        return True
    folder = os.path.expanduser("~/.Trash")             # a plain move, if AppKit would not do it
    stem, ext = os.path.splitext(os.path.basename(path))
    for n in range(1, 100):
        target = os.path.join(folder, f"{stem}{ext}" if n == 1 else f"{stem} {n}{ext}")
        if not os.path.exists(target):
            try:
                os.rename(path, target)
                return True
            except OSError:
                return False
    return False


def copy_to_applications(me: str) -> str:
    """Put a copy of this app into /Applications, exactly as it is (ditto). Returns its path; OSError if not."""
    if os.path.exists(APP):
        raise OSError("there is already a CardCopy in Applications")
    try:
        out = subprocess.run(["/usr/bin/ditto", me, APP], capture_output=True, text=True, timeout=300,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(str(exc)) from exc
    if out.returncode != 0:
        raise OSError(out.stderr.strip() or "macOS would not copy it into Applications")
    return APP


SHORTCUT = os.path.join("~", "Desktop", "CardCopy")


def desktop_shortcut(app: str = APP) -> str:
    """Make sure the Desktop has a shortcut to the CardCopy in Applications. Returns what happened:
    'made', 'there', or 'left' (something of the user's is called CardCopy there, and stays as it is).

    A shortcut (a symbolic link, which Finder shows with an alias arrow), never a copy: it always opens
    the one in Applications, the one updates replace. An old shortcut of ours that points at a copy
    elsewhere is pointed at Applications instead. Raises OSError when the Desktop cannot be written
    (macOS asks once whether CardCopy may).
    """
    link = os.path.expanduser(SHORTCUT)
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(app):
            return "there"
        if not os.readlink(link).rstrip("/").endswith("CardCopy.app"):
            return "left"
        fresh = link + ".new"
        if os.path.lexists(fresh):
            return "left"
        os.symlink(app, fresh)
        os.replace(fresh, link)                     # swaps the link itself; nothing it pointed at is touched
        return "made"
    if os.path.lexists(link):
        return "left"
    os.symlink(app, link)
    return "made"


def open_app(path: str) -> None:
    subprocess.Popen(["/usr/bin/open", "-n", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
