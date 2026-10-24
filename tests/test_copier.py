"""The hard rule: nothing is ever deleted or overwritten, on the card or at the destination."""
import os

import pytest

from cardcopy import copier
from cardcopy.copier import Claims, FileEntry, copy_files, rename_new, walk_files


def _card(tmp_path, files: dict[str, bytes]) -> str:
    root = tmp_path / "card"
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return str(root)


def _jobs(root: str, dest: str) -> list:
    return [(e, os.path.join(dest, os.path.basename(e.rel))) for e in walk_files(root)]


def test_rename_new_refuses_to_replace(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"new")
    b.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        rename_new(str(a), str(b))
    assert b.read_bytes() == b"precious" and a.read_bytes() == b"new"


def test_rename_new_moves_into_a_free_name(tmp_path):
    a = tmp_path / "a"
    a.write_bytes(b"x")
    rename_new(str(a), str(tmp_path / "c"))
    assert not a.exists() and (tmp_path / "c").read_bytes() == b"x"


def test_copy_keeps_card_and_existing_files(tmp_path):
    root = _card(tmp_path, {"DCIM/100/A.ARW": b"shot one", "DCIM/100/B.ARW": b"shot two"})
    dest = tmp_path / "Cam 1"
    dest.mkdir()
    (dest / "A.ARW").write_bytes(b"someone else's file, different size")
    result = copy_files(root, _jobs(root, str(dest)))
    assert result.errors == []
    assert (dest / "A.ARW").read_bytes() == b"someone else's file, different size"   # untouched
    assert (dest / "A (2).ARW").read_bytes() == b"shot one"
    assert (dest / "B.ARW").read_bytes() == b"shot two"
    assert sorted(os.listdir(os.path.join(root, "DCIM", "100"))) == ["A.ARW", "B.ARW"]   # card as it was


def test_second_run_skips_what_is_there(tmp_path):
    root = _card(tmp_path, {"C0001.MP4": b"clip"})
    dest = str(tmp_path / "Cam 1")
    first = copy_files(root, _jobs(root, dest))
    second = copy_files(root, _jobs(root, dest))
    assert (first.copied, second.copied, second.skipped) == (1, 0, 1)


def test_partial_is_resumed_not_restarted(tmp_path):
    root = _card(tmp_path, {"C0001.MP4": b"0123456789"})
    dest = tmp_path / "Cam 1"
    dest.mkdir()
    (entry, wanted), = _jobs(root, str(dest))
    with open(copier.partial_path(wanted, entry), "wb") as f:
        f.write(b"01234")
    result = copy_files(root, [(entry, wanted)])
    assert result.copied == 1 and (dest / "C0001.MP4").read_bytes() == b"0123456789"


def test_mac_metadata_files_are_not_footage(tmp_path):
    root = _card(tmp_path, {"DCIM/100/C0001.MP4": b"clip", "DCIM/100/._C0001.MP4": b"finder info",
                            "DCIM/.DS_Store": b"x", ".Spotlight-V100/store.db": b"x", ".fseventsd/x": b"x"})
    assert [e.rel.replace("\\", "/") for e in walk_files(root)] == ["DCIM/100/C0001.MP4"]


def test_a_card_that_disappears_stops_the_card_once(tmp_path):
    root = _card(tmp_path, {f"C{n:04d}.MP4": b"clip" for n in range(1, 6)})
    jobs = _jobs(root, str(tmp_path / "Cam 1"))
    gone = os.path.join(root + "-gone")
    os.rename(root, gone)                       # the card is pulled before the copy starts
    result = copy_files(root, jobs)
    assert len(result.errors) == 1 and "disappeared" in result.aborted


def test_claims_share_one_name_for_the_same_shot(tmp_path):
    claims = Claims()
    entry = FileEntry("A.ARW", 10, 1000.0)
    path = str(tmp_path / "A.ARW")
    assert claims.resolve(path, entry) == (path, False)
    assert claims.resolve(path, FileEntry("A.ARW", 10, 1001.0)) == (path, True)       # the backup card's copy
    assert claims.resolve(path, FileEntry("A.ARW", 11, 1000.0))[0].endswith("A (2).ARW")
