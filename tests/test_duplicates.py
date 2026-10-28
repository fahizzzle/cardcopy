"""No duplicates: what is already copied is never copied a second time, under any name, in any folder.

The other side of the hard rule (nothing is ever overwritten): a different file that happens to share a
name is kept as "name (2).ext", but the same file is only ever there once.
"""
import os

from cardcopy import missing
from cardcopy.copier import copy_files, walk_files


def card(tmp_path, files: dict[str, bytes], name="card") -> str:
    root = tmp_path / name
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return str(root)


def jobs(root: str, dest: str) -> list:
    return [(e, os.path.join(dest, os.path.basename(e.rel))) for e in walk_files(root)]


def shot(n: int, size: int = 600_000) -> bytes:
    return (f"shot {n} ".encode() * size)[:size]


def test_running_the_copy_again_copies_nothing(tmp_path):
    root = card(tmp_path, {f"DCIM/100/DSC{n:05d}.ARW": shot(n) for n in range(1, 6)})
    dest = str(tmp_path / "Cam 1")
    copy_files(root, jobs(root, dest))
    again = copy_files(root, jobs(root, dest))
    assert (again.copied, again.skipped) == (0, 5) and len(os.listdir(dest)) == 5


def test_a_copy_whose_date_moved_is_not_copied_again(tmp_path):
    """Google Drive, or a time-zone / daylight-saving change, can move a copied file's date afterwards."""
    root = card(tmp_path, {"DSC00001.ARW": shot(1)})
    dest = tmp_path / "Cam 1"
    copy_files(root, jobs(root, str(dest)))
    copied = dest / "DSC00001.ARW"
    os.utime(copied, (copied.stat().st_mtime + 3600, copied.stat().st_mtime + 3600))     # an hour later
    again = copy_files(root, jobs(root, str(dest)))
    assert (again.copied, again.skipped) == (0, 1) and os.listdir(dest) == ["DSC00001.ARW"]
    gap = missing.check_jobs(root, jobs(root, str(dest)))
    assert gap.all_copied()                                    # and "What's not copied?" agrees


def test_a_different_photo_with_the_same_name_and_size_is_kept_too(tmp_path):
    """Uncompressed RAW files are all one size: name and size alone must never make two photos one."""
    dest = tmp_path / "Cam 1"
    first = card(tmp_path, {"DSC00001.ARW": shot(1)}, "monday")
    copy_files(first, jobs(first, str(dest)))
    second = card(tmp_path, {"DSC00001.ARW": shot(2)}, "tuesday")            # numbering started again
    os.utime(os.path.join(second, "DSC00001.ARW"), (2_000_000_000, 2_000_000_000))
    result = copy_files(second, jobs(second, str(dest)))
    assert result.copied == 1 and sorted(os.listdir(dest)) == ["DSC00001 (2).ARW", "DSC00001.ARW"]
    assert (dest / "DSC00001.ARW").read_bytes() == shot(1)                     # the first one untouched


def test_both_slots_recording_the_same_clips_give_one_copy(tmp_path):
    clips = {f"PRIVATE/M4ROOT/CLIP/C{n:04d}.MP4": shot(n) for n in range(1, 4)}
    slot1, slot2 = card(tmp_path, clips, "slot1"), card(tmp_path, clips, "slot2")
    for rel in clips:                                          # the backup slot: same clips, same times
        stamp = os.stat(os.path.join(slot1, rel)).st_mtime
        os.utime(os.path.join(slot2, rel), (stamp, stamp))
    dest = str(tmp_path / "Cam 1")
    from cardcopy.copier import Claims
    claims = Claims()
    a = copy_files(slot1, jobs(slot1, dest), claims=claims)
    b = copy_files(slot2, jobs(slot2, dest), claims=claims)
    assert (a.copied, b.copied, b.skipped) == (3, 0, 3) and len(os.listdir(dest)) == 3


def test_files_in_the_backup_folder_are_not_copied_again_into_the_raw_folder(tmp_path):
    base, spill = tmp_path / "Raw", tmp_path / "Backup"
    root = card(tmp_path, {"C0001.MP4": shot(1), "C0002.MP4": shot(2)})
    dest = base / "Raw Video" / "bob" / "Cam 1"

    def spill_to(path: str) -> str:
        return os.path.join(str(spill), os.path.relpath(path, str(base)))
    # an earlier run filled the Raw folder after C0001, and put C0002 in the backup folder
    copy_files(root, jobs(root, str(dest))[:1])
    copy_files(root, [(e, spill_to(d)) for e, d in jobs(root, str(dest))[1:]])
    again = copy_files(root, jobs(root, str(dest)), spill_to=spill_to)
    assert (again.copied, again.skipped) == (0, 2)
    assert os.listdir(dest) == ["C0001.MP4"]                    # C0002 stays only where it already is
