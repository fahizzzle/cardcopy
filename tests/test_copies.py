"""One CardCopy on a Mac: finding other copies, moving them to the Trash, and the questions the window asks."""
import plistlib
import sys

import pytest

from cardcopy.mac import copies


def fake_app(folder, version="1.20.1", build=32):
    app = folder / "CardCopy.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": version, "CFBundleVersion": f"{version}.{build}"}, f)
    return app


def test_version_of_a_copy(tmp_path):
    assert copies.version_of(str(fake_app(tmp_path, build=30))) == "1.20.1 (build 30)"
    assert copies.version_of(str(tmp_path / "missing.app")) == ""


def test_other_copies_leave_out_this_one_the_trash_and_disk_images(tmp_path, monkeypatch):
    me = fake_app(tmp_path / "Applications")
    old = fake_app(tmp_path / "Downloads", build=30)
    trashed = fake_app(tmp_path / ".Trash", build=21)

    class Found:
        stdout = "\n".join([str(me), str(old), str(trashed), "/Volumes/CardCopy/CardCopy.app", ""])
    monkeypatch.setattr(copies.subprocess, "run", lambda *a, **k: Found())
    assert copies.other_copies(str(me)) == [str(old)]


def test_to_trash_moves_never_deletes(tmp_path, monkeypatch):
    monkeypatch.setattr("cardcopy.mac.native.trash", lambda path: False)        # not on a Mac: the plain move
    monkeypatch.setattr(copies.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home"), 1))
    (tmp_path / "home" / ".Trash").mkdir(parents=True)
    old = fake_app(tmp_path / "Downloads", build=30)
    assert copies.to_trash(str(old))
    assert not old.exists() and (tmp_path / "home" / ".Trash" / "CardCopy.app" / "Contents" / "Info.plist").exists()
    assert not copies.to_trash("/Volumes/CardCopy/CardCopy.app")             # the download is never touched


def test_the_updater_trashes_the_copy_it_replaced():
    from cardcopy.mac.selfupdate import _RUNNER
    assert 'old="$4"' in _RUNNER and '.Trash/' in _RUNNER and "/Volumes/*" in _RUNNER


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is a POSIX shell script")
def test_the_runner_still_parses(tmp_path):
    import subprocess
    from cardcopy.mac.selfupdate import _RUNNER
    script = tmp_path / "run.sh"
    script.write_text(_RUNNER)
    assert subprocess.run(["/bin/sh", "-n", str(script)]).returncode == 0
