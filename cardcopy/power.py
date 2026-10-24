"""Shutting the PC down when the work is done (Windows; a Mac's answers come from mac/power.py). No Qt in here.

Google Drive for desktop has no public "am I synced?" signal, so "Drive has finished" is an estimate:
the GoogleDriveFS processes move megabytes per second while they upload (they read their cache and
send it) and only a trickle when idle. Drive counts as finished once that traffic has stayed under
QUIET_BYTES_PER_SEC for QUIET_SECONDS in a row. (The cache folder is no help: uploaded files stay in it.)

Quiet traffic only means "finished" while there is a connection to be quiet on. With the internet
down, Drive has nothing to upload through and looks exactly like Drive with nothing left to upload,
so the wait is held rather than counted until the connection comes back. Otherwise a dropped Wi-Fi
at 2 a.m. would read as success and shut the PC down on footage that never left the building.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import socket
import subprocess
import sys
import time
from typing import Callable

if os.name == "nt":
    from ctypes import wintypes

DRIVE_PROCESS = "googledrivefs.exe"
UNMEASURABLE = -1           # drive_traffic: Drive is running, but how busy it is cannot be read
QUIET_BYTES_PER_SEC = 400 * 1024
QUIET_SECONDS = 300
_CREATE_NO_WINDOW = 0x08000000
# Public DNS resolvers: a TCP handshake shows the connection reaches the internet. Nothing is sent
# and nothing is looked up; the first one to answer ends the check.
CONNECT_HOSTS = (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53))
ONLINE_EVERY = 30.0          # seconds between connection checks while waiting for Drive


def internet_up(timeout: float = 3.0) -> bool:
    """Is there a working connection? A TCP handshake with a public resolver; no data either way."""
    if os.environ.get("CARDCOPY_ASSUME_ONLINE"):      # tests and dry runs: never touch the network
        return True
    for host, port in CONNECT_HOSTS:
        try:
            with socket.create_connection((host, port), timeout):
                return True
        except OSError:
            continue
    return False


if os.name == "nt":
    class _ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", ctypes.c_wchar * 260)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


def drive_traffic() -> int | None:
    """Bytes Google Drive has read plus sent/received so far (grows while it syncs). None: Drive is not running."""
    if os.name != "nt":
        return None
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE
    snapshot = k.CreateToolhelp32Snapshot(0x2, 0)               # TH32CS_SNAPPROCESS
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(_ProcessEntry)
    total, found = 0, False
    more = k.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        if entry.exe.lower() == DRIVE_PROCESS:
            handle = k.OpenProcess(0x1000, False, entry.pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                io = _IoCounters()
                if k.GetProcessIoCounters(handle, ctypes.byref(io)):
                    found = True
                    total += io.read_bytes + io.other_bytes    # reads its cache, talks to the network
                k.CloseHandle(handle)
        more = k.Process32NextW(snapshot, ctypes.byref(entry))
    k.CloseHandle(snapshot)
    return total if found else None


class DriveWatcher:
    """Feed it poll() calls every few seconds; quiet() turns True once Drive has been idle long enough."""

    def __init__(self, sample: Callable[[], int | None] | None = None, clock: Callable[[], float] = time.monotonic,
                 quiet_rate: float = QUIET_BYTES_PER_SEC, quiet_seconds: float = QUIET_SECONDS,
                 check_online: Callable[[], bool] = internet_up, online_every: float = ONLINE_EVERY) -> None:
        self.sample = sample if sample is not None else drive_traffic    # looked up now: a Mac replaces it below
        self.clock = clock
        self.quiet_rate, self.quiet_seconds = quiet_rate, quiet_seconds
        self.check_online, self.online_every = check_online, online_every
        self.last: tuple[float, int] | None = None
        self.quiet_since: float | None = None
        self.rate = 0.0
        self.running = True
        self.online = True
        self.measurable = True
        self._checked_at: float | None = None

    def poll(self) -> None:
        now, value = self.clock(), self.sample()
        self.running = value is not None
        self.measurable = value != UNMEASURABLE
        if value == UNMEASURABLE:              # running, but how busy is unknown: never call that finished
            self.last, self.rate, self.quiet_since = None, 0.0, None
            return
        if value is None:                      # Drive is not running: there is nothing to wait for
            self.last, self.rate = None, 0.0
            if self.quiet_since is None:
                self.quiet_since = now
            return
        # Drive IS running, so it has somewhere to upload to only while the connection is up.
        if self._checked_at is None or now - self._checked_at >= self.online_every:
            self._checked_at, self.online = now, bool(self.check_online())
        if not self.online:
            self.last, self.rate = None, 0.0   # the gap makes the next rate meaningless
            self.quiet_since = None            # nothing was uploaded while the line was down
            return
        if self.last is not None and now > self.last[0]:
            self.rate = max(value - self.last[1], 0) / (now - self.last[0])
            if self.rate < self.quiet_rate:
                if self.quiet_since is None:
                    self.quiet_since = self.last[0]
            else:
                self.quiet_since = None
        self.last = (now, value)

    def quiet_for(self) -> float:
        return 0.0 if self.quiet_since is None else self.clock() - self.quiet_since

    def quiet(self) -> bool:
        return self.quiet_for() >= self.quiet_seconds


_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def keep_awake(on: bool) -> bool:
    """Stop Windows from going to sleep on its idle timer (the screen may still turn off).

    The request belongs to the calling thread and lasts until that thread releases it or ends, so call
    this from the GUI thread. It does not override the power button, closing a laptop lid, or a low battery.
    """
    if os.name != "nt":
        return False
    flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))


def next_occurrence(hour: int, minute: int, now: dt.datetime | None = None) -> dt.datetime:
    """The next time the clock shows hour:minute: today if that is still ahead, otherwise tomorrow."""
    now = now or dt.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + dt.timedelta(days=1)


def prepare_shutdown() -> tuple[bool, str]:
    """(ok, why not): can this computer be shut down by CardCopy later? Windows always lets it."""
    return True, ""


def shut_down_pc() -> None:
    """Ordinary shutdown: /t 0 so Windows does NOT force-close programs with unsaved work
    (any delay above zero implies /f)."""
    if os.environ.get("CARDCOPY_NO_SHUTDOWN"):      # tests and dry runs: never the real thing
        return
    subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=_CREATE_NO_WINDOW)


if sys.platform == "darwin":            # caffeinate, System Events and nettop instead of the Win32 calls
    from .mac.power import drive_traffic, keep_awake, prepare_shutdown, shut_down_pc  # noqa: E402,F401,F811
