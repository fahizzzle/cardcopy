"""Which files on a card have not been copied yet. No Qt in here.

Reads only. It compares every file a card would copy against the place that copy would put it, and
names the ones that are not there -- all of them, not a sample: a list you cannot work through is
not much better than no list.

A file counts as copied when a file of the same name, size and date is at the destination. With
`deep` it is compared byte for byte instead, which is the difference between "something of the
right size is there" and "the footage is there".
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from dataclasses import dataclass, field
from typing import Callable

from .copier import Cancelled, FileEntry, _digest, same_file

_VARIANTS = 64           # how far to follow "name (2).ext", "name (3).ext" ...


class Listing:
    """What is really in each destination folder, read once rather than guessed at name by name."""

    def __init__(self) -> None:
        self._folders: dict[str, dict[str, tuple[int, float, str]]] = {}

    def of(self, folder: str) -> dict[str, tuple[int, float, str]]:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in self._folders:
            found: dict[str, tuple[int, float, str]] = {}
            try:
                with os.scandir(folder) as entries:
                    for e in entries:
                        try:
                            if e.is_file(follow_symlinks=False):
                                st = e.stat()
                                found[e.name.lower()] = (st.st_size, st.st_mtime, e.path)
                        except OSError:
                            continue
            except OSError:
                pass                          # no such folder: nothing was ever copied into it
            self._folders[key] = found
        return self._folders[key]


def find_copy(dst: str, entry: FileEntry, listing: Listing | None = None, src: str | None = None) -> str | None:
    """Where this exact file ended up, or None if it is not there.

    A match needs the same name, the same SIZE and the same DATE -- or, with src (the file on the card),
    the same bytes when only the date has moved (copier.same_file); a name alone proves nothing. The
    project folder is part of dst, so the same file name under another project is a different path
    and is never looked at -- C0001.MP4 in Nour and C0001.MP4 in Rasheda cannot be mistaken.

    Several cards can feed one Cam folder, so a second file with the same name is kept as
    "name (2).ext" -- the same ladder copier.Claims walks when it hands out names. The whole ladder
    is walked even where a rung is missing: this check exists to find files that have gone, and a
    deleted "C0001.MP4" must not hide the "C0001 (2).MP4" still sitting beside it.
    """
    folder, name = os.path.split(dst)
    files = (listing or Listing()).of(folder)
    base, ext = os.path.splitext(name)
    for n in range(1, _VARIANTS + 1):
        found = files.get((name if n == 1 else f"{base} ({n}){ext}").lower())
        if found is None:
            continue
        size, mtime, path = found
        if same_file(path, size, mtime, entry, src):
            return path
    return None


@dataclass
class Gap:
    """What one card is still missing at the destination."""
    label: str = ""
    source: str = ""
    destination: str = ""
    total: int = 0
    found: int = 0
    missing: list[tuple[str, int]] = field(default_factory=list)      # (path on the card, size)
    different: list[tuple[str, int]] = field(default_factory=list)    # there, but not the same file
    deep: bool = False
    cancelled: bool = False

    @property
    def short(self) -> int:
        return len(self.missing) + len(self.different)

    @property
    def size(self) -> int:
        return sum(n for _, n in self.missing) + sum(n for _, n in self.different)

    def all_copied(self) -> bool:
        return bool(self.total) and not self.cancelled and not self.short

    def summary(self) -> str:
        if self.cancelled:
            return "check cancelled"
        if not self.total:
            return "nothing on this card would be copied"
        if self.all_copied():
            how = "byte for byte" if self.deep else "by name, size and date"
            return f"all {self.total:,} files are copied ({how})"
        parts = []
        if self.missing:
            parts.append(f"{len(self.missing):,} not copied")
        if self.different:
            parts.append(f"{len(self.different):,} do not match")
        return f"{', '.join(parts)} of {self.total:,} files"


def check_jobs(src_root: str, jobs: list[tuple[FileEntry, str]], *, deep: bool = False,
               label: str = "", destination: str = "", cancel: threading.Event | None = None,
               spill_to: Callable[[str], str | None] | None = None,
               on_progress: Callable[[int, str], None] | None = None) -> Gap:
    """Compare every (file, destination) job against what is actually there.

    spill_to gives a file's place in the backup folder, so a copy that overflowed is not reported
    as missing: a file has arrived wherever it actually landed.
    """
    gap = Gap(label=label, source=src_root, destination=destination, total=len(jobs), deep=deep)
    listing = Listing()          # each destination folder is read once, however many files land in it
    done = 0
    for entry, wanted in jobs:
        if cancel is not None and cancel.is_set():
            gap.cancelled = True
            break
        landed = find_copy(wanted, entry, listing, os.path.join(src_root, entry.rel))
        if landed is None and spill_to is not None:
            elsewhere = spill_to(wanted)
            if elsewhere:
                landed = find_copy(elsewhere, entry, listing, os.path.join(src_root, entry.rel))
        if landed is None:
            gap.missing.append((entry.rel, entry.size))
        elif deep:
            try:
                if _digest(os.path.join(src_root, entry.rel), cancel) == _digest(landed, cancel):
                    gap.found += 1
                else:
                    gap.different.append((entry.rel, entry.size))
            except Cancelled:
                gap.cancelled = True
                break
            except OSError:
                gap.different.append((entry.rel, entry.size))
        else:
            gap.found += 1
        done += entry.size
        if on_progress is not None:
            on_progress(done, entry.rel)
    return gap


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def report(project: str, gaps: list[Gap], when: dt.datetime | None = None, version: str = "") -> str:
    """The whole list, in full, as a text file to work through."""
    when = when or dt.datetime.now()
    short = sum(g.short for g in gaps)
    lines = [f"CardCopy{' ' + version if version else ''} - files not copied",
             f"Project: {project or '(none)'}",
             f"Checked: {when:%d %b %Y  %H:%M}",
             ""]
    if any(g.cancelled for g in gaps):
        lines.append("THE CHECK WAS CANCELLED: this list is incomplete.")
        lines.append("")
    lines.append(f"{short:,} file(s) still to copy across {len(gaps)} card(s)."
                 if short else f"Everything on {len(gaps)} card(s) is copied.")
    for gap in gaps:
        lines += ["", "-" * 72, f"{gap.label or gap.source}", f"    from  {gap.source}",
                  f"    to    {gap.destination}", f"    {gap.summary()}"]
        if gap.short:
            lines.append(f"    {human(gap.size)} still to copy")
        lines.append("")
        for rel, size in gap.missing:
            lines.append(f"  NOT COPIED   {human(size):>9}  {rel}")
        for rel, size in gap.different:
            lines.append(f"  DOES NOT MATCH {human(size):>7}  {rel}")
    return "\n".join(lines) + "\n"


def save(folder: str, text: str, when: dt.datetime | None = None) -> str:
    """Write the list beside the Cam folders. Exclusive create: an earlier list is never replaced."""
    when = when or dt.datetime.now()
    os.makedirs(folder, exist_ok=True)
    stem = f"CardCopy not copied {when:%Y-%m-%d %H-%M}"
    n = 1
    while True:
        path = os.path.join(folder, stem + ("" if n == 1 else f" ({n})") + ".txt")
        try:
            with open(path, "x", encoding="utf-8", newline="\r\n") as f:
                f.write(text)
            return path
        except FileExistsError:
            n += 1
