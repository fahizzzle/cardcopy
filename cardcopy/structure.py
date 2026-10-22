r"""Where a project's folders go and which file lands where. No Qt in here.

    <base>\Raw Photo\<project>\Cam 1 … Cam N     photos, flat
    <base>\Raw Video\<project>\Cam 1 … Cam N     videos, flat
    <base>\Raw Audio\<project>\Cam 1 … Cam N     field recorders, flat (only while Audio is ticked)

or, with audio kept with the video (audio_in_video):

    <base>\Raw Video\<project>\Audio             one recorder
    <base>\Raw Video\<project>\Audio 1 … Audio N  several, so their files never mix

A project name may contain / to nest ("Rasheda/Reception").
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from .copier import FileEntry
from .identify import CopyOptions, tag_files

KINDS = ("photo", "video", "audio")
DEFAULT_BASE = r"G:\My Drive\Raw"
if sys.platform == "darwin":                 # My Drive/Raw of the first signed-in account, if there is one
    from .gdrive import default_raw_folder
    DEFAULT_BASE = default_raw_folder()
DEFAULT_KIND_FOLDERS = {"photo": "Raw Photo", "video": "Raw Video", "audio": "Raw Audio"}
_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    """Make one path component safe for Windows and Google Drive."""
    return _BAD.sub("_", name).strip().rstrip(". ")


def project_path(project: str) -> str:
    parts = [sanitize(p) for p in re.split(r"[\\/]+", project)]
    return os.path.join(*[p for p in parts if p]) if any(parts) else ""


AUDIO_FOLDER = "Audio"       # a project's recordings, inside its Raw Video folder (audio_in_video)


def cam_folder(n: int) -> str:
    return f"Cam {n}"


def cam_folders(kind: str, count: int, audio_in_video: bool = False) -> list[str]:
    """The device folders of one Raw folder: Cam 1 … Cam N; recordings kept with the video go into
    Audio (one recorder) or Audio 1 … Audio N (several)."""
    count = max(1, int(count))
    if kind == "audio" and audio_in_video:
        return [AUDIO_FOLDER] if count == 1 else [f"{AUDIO_FOLDER} {n}" for n in range(1, count + 1)]
    return [cam_folder(n) for n in range(1, count + 1)]


def inside(path: str, folder: str) -> bool:
    """Is path the same as folder, or somewhere under it?"""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    except ValueError:                      # different drives, on Windows
        return False
    return rel == "." or not rel.startswith("..")


def overlapping(a: str, b: str) -> bool:
    """Either folder contains the other (or they are the same)."""
    return bool(a) and bool(b) and (inside(a, b) or inside(b, a))


def spill_path(dst: str, base: str, spill_base: str) -> str | None:
    """The same file's place under the backup folder, keeping the whole Raw Photo/Video/Audio
    and project layout: <base>\\Raw Video\\P\\Cam 1\\C0001.MP4 -> <spill_base>\\Raw Video\\P\\Cam 1\\C0001.MP4.

    None when there is no usable backup: no folder set, a destination that is not under the main
    folder at all, or a backup folder that overlaps the main one. Overlapping is refused because a
    backup inside the Raw folder (or a Raw folder inside the backup) is not somewhere else to go
    when the drive fills up -- it is the same drive, filling at the same time, with one shoot now
    written in two nested places.
    """
    if not spill_base or not base:
        return None
    if overlapping(base, spill_base):
        return None
    try:
        rel = os.path.relpath(os.path.abspath(dst), os.path.abspath(base))
    except ValueError:                      # different drives, on Windows
        return None
    if rel.startswith(".."):
        return None
    return os.path.join(spill_base, rel)


@dataclass
class Plan:
    roots: dict[str, str] = field(default_factory=dict)   # kind -> project folder
    folders: list[str] = field(default_factory=list)      # absolute, in creation order
    cams: dict[str, int] = field(default_factory=dict)    # kind -> how many Cam folders it has
    names: dict[str, list[str]] = field(default_factory=dict)   # kind -> its device folders, Cam 1 first

    def dest(self, kind: str, cam: int) -> str:
        names = self.names.get(kind)
        if names:
            return os.path.join(self.roots[kind], names[min(max(cam, 1), len(names)) - 1])
        return os.path.join(self.roots[kind], cam_folder(cam))


def build_plan(base: str, project: str, kinds: list[str], cam_count: int | dict[str, int],
               kind_folders: dict[str, str] | None = None, audio_in_video: bool = False) -> Plan:
    r"""cam_count is one number for every Raw folder, or a number for each.

    Three photo cameras and two video ones want Raw Photo\Cam 1-3 and Raw Video\Cam 1-2, not the
    same count in both, so each kind carries its own. audio_in_video puts the recordings in the
    project's Raw Video folder (Raw Video\<project>\Audio) instead of a Raw Audio folder of their own.
    """
    names = {**DEFAULT_KIND_FOLDERS, **(kind_folders or {})}
    counts = cam_count if isinstance(cam_count, dict) else {kind: cam_count for kind in KINDS}
    plan = Plan()
    for kind in KINDS:
        if kind not in kinds:
            continue
        how_many = max(1, int(counts.get(kind, 1)))
        raw = names["video"] if kind == "audio" and audio_in_video else names[kind]
        root = os.path.join(base, raw, project_path(project))
        plan.roots[kind] = root
        plan.cams[kind] = how_many
        plan.names[kind] = cam_folders(kind, how_many, audio_in_video)
        if root not in plan.folders:          # audio in video shares the video project folder
            plan.folders.append(root)
        plan.folders += [os.path.join(root, name) for name in plan.names[kind]]
    return plan


def create_folders(plan: Plan) -> int:
    made = 0
    for folder in plan.folders:
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
            made += 1
    return made


def copy_jobs(files: list[FileEntry], plan: Plan, cam: int, kind: str,
              options: CopyOptions | None = None) -> list[tuple[FileEntry, str]]:
    """(file, destination path) for what comes off one card; everything else stays behind.

    The device's role decides the root: an FX3 is a video camera, so its media lands in Raw Video;
    an A7 is a photo camera, so it lands in Raw Photo; a field recorder lands in Raw Audio. options
    decides which files count: RAW photos, clips and recordings always, JPG/HEIF pictures and clip
    XML files only when asked for.
    """
    if kind not in plan.roots:
        return []
    options = options or CopyOptions()
    if any(not f.kind for f in files) and not any(f.kind for f in files):
        tag_files(files)                      # a list straight from walk_files
    dest = plan.dest(kind, cam)
    return [(f, os.path.join(dest, os.path.basename(f.rel))) for f in files if f.kind and options.wants(f.kind)]
