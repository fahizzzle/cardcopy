"""Staying awake, shutting the Mac down, and watching Google Drive upload (macOS). No Qt in here.

power.py holds the rules (DriveWatcher, internet_up, next_occurrence); this module only answers the
three questions that need the system:

  keep_awake    `caffeinate`, tied to CardCopy's own pid so a crash can never leave the Mac awake
  shut_down_pc  System Events' "shut down": the ordinary kind, where an app with unsaved work may object
  drive_traffic bytes Google Drive has sent and received, from `nettop` (per-process network counters)
"""
from __future__ import annotations

import os
import subprocess

DRIVE_NAMES = ("google drive", "googledrive", "drivefs")    # the app, its helpers, its file provider
_SHUT_DOWN = 'tell application "System Events" to shut down'
_ASK = 'tell application "System Events" to get name'      # harmless; only there to raise the permission prompt

_caffeinate: subprocess.Popen | None = None


def keep_awake(on: bool) -> bool:
    """Stop the Mac from going to sleep on its idle timer (the screen may still turn off).

    `caffeinate -w <our pid>` ends by itself when CardCopy does, however it ends. It does not override
    closing a laptop's lid, the power button, or a low battery.
    """
    global _caffeinate
    if on:
        if _caffeinate is None or _caffeinate.poll() is not None:
            try:
                _caffeinate = subprocess.Popen(["caffeinate", "-i", "-m", "-s", "-w", str(os.getpid())],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
            except OSError:
                _caffeinate = None
                return False
        return True
    if _caffeinate is not None and _caffeinate.poll() is None:
        _caffeinate.terminate()
    _caffeinate = None
    return True


def _osascript(script: str, timeout: float) -> tuple[bool, str]:
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return out.returncode == 0, (out.stderr or out.stdout).strip()


def prepare_shutdown(timeout: float = 120.0) -> tuple[bool, str]:
    """Make sure CardCopy may ask System Events to shut down, while someone is there to say yes.

    The first request makes macOS ask "CardCopy wants access to control System Events". Left until
    2 a.m., that question would sit on screen unanswered and the Mac would stay on, so it is asked
    the moment the shutdown is armed. Blocking (the prompt waits for an answer): call it from a thread.
    """
    if os.environ.get("CARDCOPY_NO_SHUTDOWN"):
        return True, ""
    ok, detail = _osascript(_ASK, timeout)
    if ok:
        return True, ""
    if "-1743" in detail or "not authori" in detail.lower():
        return False, ("macOS does not let CardCopy shut the Mac down. Allow it in System Settings > "
                       "Privacy & Security > Automation > CardCopy > System Events.")
    return False, f"macOS did not answer the shutdown check ({detail or 'no reason given'})"


def shut_down_pc() -> None:
    """Ordinary shutdown, like choosing Shut Down in the Apple menu: an app with unsaved work may object."""
    if os.environ.get("CARDCOPY_NO_SHUTDOWN"):      # tests and dry runs: never the real thing
        return
    subprocess.Popen(["osascript", "-e", _SHUT_DOWN], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_nettop(text: str) -> int | None:
    """Bytes in + out of every Google Drive process in `nettop -P -L 1 -J bytes_in,bytes_out` output.

    The output is CSV: a header naming the columns, then one row per process as
    "time,<name>.<pid>,<bytes_in>,<bytes_out>,". None when no Drive process is in it.
    """
    i_in, i_out = 2, 3
    total, found = 0, False
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if "bytes_in" in parts and "bytes_out" in parts:          # the header: take the columns from it
            i_in, i_out = parts.index("bytes_in"), parts.index("bytes_out")
            continue
        if len(parts) <= max(i_in, i_out, 1):
            continue
        name = parts[1].rsplit(".", 1)[0].lower()
        if not any(n in name for n in DRIVE_NAMES):
            continue
        try:
            total += int(parts[i_in]) + int(parts[i_out])
        except ValueError:
            continue
        found = True
    return total if found else None


def drive_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-i", "-f", "google drive"], capture_output=True, timeout=10,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def drive_traffic() -> int | None:
    """Bytes Google Drive has sent and received so far (grows while it uploads).

    None: Drive is not running. 0: running, with no connection open (nothing to upload through).
    UNMEASURABLE: running, but nettop could not be read -- the watcher then never calls Drive finished,
    because a Mac that stays on is a far smaller mistake than one that switches off mid-upload.
    """
    from ..power import UNMEASURABLE
    try:
        out = subprocess.run(["nettop", "-P", "-L", "1", "-x", "-J", "bytes_in,bytes_out"],
                             capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        readable = out.returncode == 0 and "bytes_in" in out.stdout
    except (OSError, subprocess.SubprocessError):
        out, readable = None, False
    value = parse_nettop(out.stdout) if readable else None
    if value is not None:
        return value
    if not drive_running():
        return None
    return 0 if readable else UNMEASURABLE
