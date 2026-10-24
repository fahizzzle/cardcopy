"""Choosing which recordings come off an audio card: lengths, the list, and what is then copied."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import screenshot  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from cardcopy.copier import walk_files  # noqa: E402
from cardcopy.identify import tag_files, wav_seconds  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_length_of_a_recording_from_its_header(tmp_path):
    path = tmp_path / "ZOOM0001.WAV"
    screenshot.write_wav(str(path), "ZOOM F6", 288_000 * 90 + 1000)        # 48 kHz 24-bit stereo: 288 KB a second
    assert wav_seconds(str(path)) == pytest.approx(90, abs=0.1)
    (tmp_path / "x.WAV").write_bytes(b"not a wav")
    assert wav_seconds(str(tmp_path / "x.WAV")) is None


def test_lengths_read_out(app):
    from cardcopy.pick_dialog import length
    assert (length(222), length(3735), length(None)) == ("3:42", "1:02:15", "")


def _recordings(tmp_path, count=4):
    root = tmp_path / "MICRO"
    (root / "FOLDER01").mkdir(parents=True)
    for n in range(1, count + 1):
        screenshot.write_wav(str(root / "FOLDER01" / f"ZOOM{n:04d}.WAV"), "ZOOM F6", 288_000 * n * 10)
    return str(root), tag_files(list(walk_files(str(root))))


def test_the_list_ticks_what_was_chosen_and_says_how_much(app, tmp_path):
    from cardcopy.pick_dialog import RecordingsDialog
    root, files = _recordings(tmp_path)
    dialog = RecordingsDialog(None, "Zoom F6 · SD Card 1", root, files, {files[0].rel})
    assert dialog.chosen() == {files[0].rel}
    assert dialog.summary.text().startswith("1 of 4 recordings")
    dialog._tick_all(False)
    assert not dialog.use_button.isEnabled()                       # nothing to copy is not a choice
    dialog._tick_all(True)
    assert dialog.chosen() == {f.rel for f in files}
    assert dialog.tree.topLevelItem(0).text(2) == "0:10"           # sorted by when they were recorded


def test_choose_returns_none_for_all_and_false_for_cancel(app, tmp_path, monkeypatch):
    from cardcopy import pick_dialog
    root, files = _recordings(tmp_path)
    monkeypatch.setattr(pick_dialog.RecordingsDialog, "exec", lambda self: QDialog.Accepted)
    assert pick_dialog.choose(None, "t", root, files, None) is None
    monkeypatch.setattr(pick_dialog.RecordingsDialog, "exec",
                        lambda self: (self.tree.topLevelItem(0).setCheckState(0, Qt.Unchecked), QDialog.Accepted)[1])
    assert len(pick_dialog.choose(None, "t", root, files, None)) == 3
    monkeypatch.setattr(pick_dialog.RecordingsDialog, "exec", lambda self: QDialog.Rejected)
    assert pick_dialog.choose(None, "t", root, files, None) is False
