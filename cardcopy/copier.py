"""Copy files off a card. No Qt in here.

Hard rule: this module never deletes and never overwrites a file, on the card or at
the destination. Cards are opened read-only; tests/test_cardcopy.py enforces all of it.
"""
from __future__ import annotations

import errno
import hashlib
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterator

SKIP_DIRS = {"system volume information", "$recycle.bin", ".trashes", ".spotlight-v100", ".fseventsd"}
CHUNK = 4 * 1024 * 1024
GIVE_UP_AFTER = 3      # device errors in a row before a card is treated as gone
# Windows raises these two when a disk fills up: ERROR_HANDLE_DISK_FULL and ERROR_DISK_FULL.
_DISK_FULL_WINERRORS = (39, 112)


class Cancelled(Exception):
    pass


# What Windows says when a drive goes away mid-copy: not ready, I/O error, no such device,
# device does not exist, general failure. EINVAL is the one a failing card reader gives.
_LOST_WINERRORS = (21, 31, 55, 433, 1117)
_LOST_ERRNOS = (errno.EINVAL, errno.EIO, errno.ENODEV, errno.ENXIO, errno.EBADF)


def device_lost(exc: OSError) -> bool:
    """Does this look like a drive disappearing rather than a problem with one file?"""
    return exc.errno in _LOST_ERRNOS or getattr(exc, "winerror", None) in _LOST_WINERRORS


def explain(exc: OSError, src_root: str) -> str:
    """The error, plus what a person should do about it.

    "[Errno 22] Invalid argument" is true and useless. The same error means "your card reader just
    dropped the card", which is something you can act on.
    """
    if not device_lost(exc):
        return str(exc)
    if not os.path.isdir(src_root):
        return f"{exc} - the card is no longer there; check the reader, cable or USB port"
    return f"{exc} - a drive stopped responding; check the reader, cable or USB port"


def is_disk_full(exc: OSError) -> bool:
    """The destination ran out of room — as opposed to a real failure like an unplugged card.

    Worth telling apart: out of room is temporary and the copy can simply wait for it, which is what
    happens when cards go into Google Drive faster than Drive can upload and clear its cache.
    """
    return exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in _DISK_FULL_WINERRORS


@dataclass
class FileEntry:
    rel: str
    size: int
    mtime: float
    kind: str = ""          # "raw" | "jpeg" | "video" | "xml" | "" (not media); set by identify.tag_files


@dataclass
class FileRecord:
    rel: str                  # path on the card
    dst: str                  # where it is now
    size: int
    status: str               # "copied" | "already there" | "ERROR: ..."
    digest: str = ""          # MD5 of the file, when the copy was verified


@dataclass
class CopyResult:
    copied: int = 0
    skipped: int = 0          # already there with the same size
    bytes_copied: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    aborted: str = ""         # the card went away: why, and how many files were never tried
    records: list[FileRecord] = field(default_factory=list)   # one per file dealt with


def walk_files(root: str) -> Iterator[FileEntry]:
    """Every file on the card, relative to its root, skipping OS housekeeping folders."""
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in SKIP_DIRS:
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    st = entry.stat()
                    yield FileEntry(os.path.relpath(entry.path, root), st.st_size, st.st_mtime)
            except OSError:
                continue


def _digest(path: str, cancel: threading.Event | None) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            if cancel is not None and cancel.is_set():
                raise Cancelled
            h.update(chunk)
    return h.hexdigest()


def partial_path(dst: str, entry: FileEntry) -> str:
    """Where an unfinished copy of this exact file (name, size, time) is kept."""
    return f"{dst}.{entry.size}-{int(entry.mtime)}.partial"


def _copy_file(src: str, dst: str, entry: FileEntry, verify: bool,
               cancel: threading.Event | None, on_bytes: Callable[[int], None]) -> str:
    """Copy src to dst without ever deleting or overwriting a file. Returns the file's MD5 when verify is on.

    The source is only read. Data goes into a .partial file that is renamed to
    dst once complete; a cancelled or failed copy leaves the .partial behind and
    the next run carries on from where it stopped. os.rename refuses to replace
    an existing file on Windows, so nothing already at the destination can be lost.
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = partial_path(dst, entry)
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > entry.size:
        raise OSError(f"{os.path.basename(part)} is larger than the file on the card; left untouched")
    if have:
        on_bytes(have)
    h = hashlib.md5() if verify and not have else None
    # The .partial is opened only once the card has actually given us something. A card that dies
    # on the first read would otherwise leave an empty .partial for every file it never sent -- a
    # failed offload of 372 clips left 371 of them.
    fout = None
    try:
        with open(src, "rb") as fin:
            fin.seek(have)
            while chunk := fin.read(CHUNK):
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                if fout is None:
                    fout = open(part, "ab")
                fout.write(chunk)
                if h is not None:
                    h.update(chunk)
                on_bytes(len(chunk))
        if fout is None and not have:
            fout = open(part, "ab")          # a genuinely empty file still has to arrive
    finally:
        if fout is not None:
            fout.close()
    problem, digest = "", ""
    if os.path.getsize(part) != entry.size:
        problem = f"size mismatch after copy ({os.path.getsize(part)} vs {entry.size} bytes)"
    elif verify:
        digest = h.hexdigest() if h is not None else _digest(src, cancel)   # what the card holds
        if _digest(part, cancel) != digest:
            problem = "checksum mismatch after copy"
    if problem:
        bad = part + ".bad"   # set aside, not deleted, so the next run starts this file afresh
        if not os.path.exists(bad):
            os.rename(part, bad)
        raise OSError(f"{problem}; the faulty copy was kept as {os.path.basename(bad)}")
    try:
        os.utime(part, (entry.mtime, entry.mtime))
    except OSError:
        pass
    os.rename(part, dst)
    return digest


class Claims:
    """Destination names handed out during one run, shared by the card threads.

    Several cards can feed one Cam folder: two claims on a name with the same
    size and time are the same shot (the backup card), anything else is a
    different file that needs its own name.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._taken: dict[str, tuple[int, float]] = {}

    @staticmethod
    def _same(size: int, mtime: float, entry: FileEntry) -> bool:
        return size == entry.size and abs(mtime - entry.mtime) < 3  # FAT keeps 2 s steps

    def resolve(self, dst: str, entry: FileEntry) -> tuple[str, bool]:
        """(path to write, already there). Never returns a path holding a different file."""
        base, ext = os.path.splitext(dst)
        n = 1
        with self._lock:
            while True:
                cand = dst if n == 1 else f"{base} ({n}){ext}"
                key = cand.lower()
                if key in self._taken:
                    if self._same(*self._taken[key], entry):
                        return cand, True
                elif os.path.isfile(cand):
                    st = os.stat(cand)
                    if self._same(st.st_size, st.st_mtime, entry):
                        return cand, True
                else:
                    self._taken[key] = (entry.size, entry.mtime)
                    return cand, False
                n += 1

    def release(self, dst: str) -> None:
        """Hand a claimed name back: nothing was written there after all.

        Only used when a file spills into the backup folder. Without this the abandoned name would
        still look taken, and the same shot arriving from the other card would be counted as already
        there when in truth nothing was ever written to it.
        """
        with self._lock:
            self._taken.pop(dst.lower(), None)


def copy_files(src_root: str, jobs: list[tuple[FileEntry, str]], *, verify: bool = False,
               cancel: threading.Event | None = None, claims: Claims | None = None,
               on_progress: Callable[[int, str], None] | None = None,
               wait_for_space: Callable[[int, str, str], bool] | None = None,
               spill_to: Callable[[str], str | None] | None = None) -> CopyResult:
    """Copy each (file, destination path) job from one card.

    A file already at its destination (same size and time) is skipped, so an
    interrupted copy can simply be run again; a different file with the same
    name is kept as "name (2).ext". on_progress(bytes_done, rel_path) counts
    skipped files too, so it ends at the jobs' total size.

    spill_to(planned_path) gives the same file's place in the backup folder, or None for "there is
    no backup". When the destination fills up it is asked first: if it offers somewhere, this file
    and every file after it on this card go there instead, and the copy never pauses at all.

    wait_for_space(bytes_needed, rel_path, destination) is the fallback when there is no backup (or
    the backup is full too). It should block until there is room and return True, or return False to
    give up. The file is then tried again and carries on from what its .partial already holds, so a
    full disk costs time, never data.
    """
    claims = claims or Claims()
    result = CopyResult()
    done = 0
    lost = 0               # device errors in a row: a dying reader, not one awkward file
    spilling = False        # this card's remaining files go to the backup folder

    def report(n: int, rel: str) -> None:
        nonlocal done
        done += n
        if on_progress is not None:
            on_progress(done, rel)

    for entry, wanted in jobs:
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        before = done
        try:
            planned = wanted
            if spilling and spill_to is not None:
                planned = spill_to(wanted) or wanted
            dst, present = claims.resolve(planned, entry)
            digest, skipped = "", present
            while not skipped:
                try:
                    digest = _copy_file(os.path.join(src_root, entry.rel), dst, entry, verify, cancel,
                                        lambda n: report(n, entry.rel))
                    break
                except OSError as exc:
                    if not is_disk_full(exc):
                        raise
                    # the .partial keeps what was written; the retry re-reports it, so rewind the
                    # running total to where this file started rather than counting those bytes twice
                    done = before
                    elsewhere = spill_to(wanted) if (spill_to is not None and not spilling) else None
                    if elsewhere and elsewhere != dst:
                        # what is already in the full folder stays exactly as it is, .partial and all
                        claims.release(dst)
                        spilling = True
                        dst, present = claims.resolve(elsewhere, entry)
                        skipped = present
                        continue
                    if wait_for_space is None or not wait_for_space(entry.size, entry.rel, dst):
                        raise Cancelled
            if skipped:
                result.skipped += 1
                result.records.append(FileRecord(entry.rel, dst, entry.size, "already there"))
                report(entry.size, entry.rel)
                continue
            result.copied += 1
            result.bytes_copied += entry.size
            result.records.append(FileRecord(entry.rel, dst, entry.size, "copied", digest))
        except Cancelled:
            result.cancelled = True
            break
        except OSError as exc:
            why = explain(exc, src_root)
            result.errors.append(f"{entry.rel}: {why}")
            result.records.append(FileRecord(entry.rel, wanted, entry.size, f"ERROR: {why}"))
            report(before + entry.size - done, entry.rel)  # keep the bar honest
            if device_lost(exc):
                # The card has gone, or the reader has stopped answering for it. Trying the rest one
                # at a time only fills the log with the same failure hundreds of times over; say it
                # once and stop. A reader can keep the drive letter visible while every read fails,
                # so a run of these counts as gone even when the folder still seems to be there.
                lost += 1
                if not os.path.isdir(src_root) or lost >= GIVE_UP_AFTER:
                    left = len(jobs) - jobs.index((entry, wanted)) - 1
                    gone = "disappeared" if not os.path.isdir(src_root) else "stopped responding"
                    result.aborted = (f"{src_root} {gone} mid-copy, so {left} more file(s) were not tried. "
                                      "Nothing on the card was touched; reconnect it and run again.")
                    break
            else:
                lost = 0
    return result
