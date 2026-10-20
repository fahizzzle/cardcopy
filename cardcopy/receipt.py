"""The offload receipt: a plain text record of what was copied, saved in the project folder. No Qt in here.

It is evidence to check before formatting a card: every file, where it went, its size, what happened to it
(copied / already there / ERROR) and, when verification was on, its checksum. A receipt is never overwritten:
each run gets its own file.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

from .copier import CopyResult


@dataclass
class CardReport:
    source: str             # "D:\\"
    camera: str             # "FX3"
    slot: str               # "Card 1"
    destination: str        # the Cam folder
    planned: int            # files this card was meant to deliver
    result: CopyResult


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def build(project: str, started: dt.datetime, finished: dt.datetime, cards: list[CardReport], *,
          verified: bool, also_copied: str, version: str) -> str:
    safe = sum(c.result.copied + c.result.skipped for c in cards)
    planned = sum(c.planned for c in cards)
    errors = sum(len(c.result.errors) for c in cards)
    cancelled = any(c.result.cancelled for c in cards)
    if cancelled:
        verdict = f"CANCELLED: {safe} of {planned} files are at the destination. Run the copy again to finish."
    elif errors or safe != planned:
        verdict = f"PROBLEMS: {safe} of {planned} files are at the destination, {errors} error(s). Do NOT format these cards yet."
    else:
        verdict = f"COMPLETE: all {planned} files are at the destination" + \
                  (", each verified by checksum." if verified else " (sizes checked; checksum verification was off).")
    lines = [
        "CardCopy offload receipt",
        "========================",
        f"Project:   {project}",
        f"Started:   {started:%Y-%m-%d %H:%M:%S}",
        f"Finished:  {finished:%Y-%m-%d %H:%M:%S}",
        f"Copied:    RAW photos and video clips{also_copied}",
        f"Verify:    {'checksum (MD5) of every copied file compared with the card' if verified else 'file sizes only'}",
        f"CardCopy:  {version}",
        "",
        verdict,
        "",
    ]
    for c in cards:
        r = c.result
        lines += [
            f"{c.source}  {c.camera}  {c.slot}",
            f"  to: {c.destination}",
            f"  {r.copied} copied ({_size(r.bytes_copied)}), {r.skipped} already there, {len(r.errors)} error(s)"
            + (", cancelled" if r.cancelled else "") + f"; {c.planned} planned",
        ]
        for rec in r.records:
            digest = f"  md5 {rec.digest}" if rec.digest else ""
            lines.append(f"    {rec.status:<14} {rec.size:>14,}  {os.path.basename(rec.dst)}  <-  {rec.rel}{digest}")
        reached = {rec.rel for rec in r.records}
        if r.cancelled and c.planned > len(reached):
            lines.append(f"    ({c.planned - len(reached)} file(s) were not reached before the cancel)")
        lines.append("")
    return "\n".join(lines)


def write(folder: str, text: str, when: dt.datetime) -> str:
    """Save next to the Cam folders. Exclusive create: an existing receipt is never replaced."""
    os.makedirs(folder, exist_ok=True)
    stem = f"CardCopy receipt {when:%Y-%m-%d %H-%M}"
    n = 1
    while True:
        path = os.path.join(folder, stem + ("" if n == 1 else f" ({n})") + ".txt")
        try:
            with open(path, "x", encoding="utf-8", newline="\r\n") as f:
                f.write(text)
            return path
        except FileExistsError:
            n += 1
