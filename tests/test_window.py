"""The window opens, in both looks, on made-up cards; nothing real is touched (see conftest)."""
import importlib
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch, look: str):
    import screenshot
    monkeypatch.setenv("CARDCOPY_THEME", look)
    home = tmp_path / "home"
    home.mkdir()
    raw = tmp_path / "Raw"
    raw.mkdir()
    cards = screenshot.make_cards(str(tmp_path / "cards"))
    (home / "settings.json").write_text(json.dumps({"base": str(raw), "folders": cards}))
    monkeypatch.setenv("CARDCOPY_HOME", str(home))
    import cardcopy.aqua
    import cardcopy.theme
    import cardcopy.camera_panel
    import cardcopy.ui
    for module in (cardcopy.theme, cardcopy.camera_panel, cardcopy.ui):
        importlib.reload(module)
    window = cardcopy.ui.MainWindow()
    window.project_edit.setText("Nour")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and (window.scanning or not window.panels):
        QApplication.processEvents()
        time.sleep(0.02)
    return window


@pytest.mark.parametrize("look", ["glass", "mac"])
def test_window_finds_the_three_devices(app, tmp_path, monkeypatch, look):
    window = _window(tmp_path, monkeypatch, look)
    try:
        names = sorted(cam.name for cam in window.cameras)
        assert names == ["A7 IV", "FX3", "Zoom F6"]
        kinds = {cam.name: window._kind_of(cam) for cam in window.cameras}
        assert kinds == {"A7 IV": "photo", "FX3": "video", "Zoom F6": "audio"}
        preview = window.preview.toPlainText()
        assert "Raw Photo" in preview and "Cam 1" in preview
    finally:
        window.close()


def test_mac_layout_has_toolbar_settings_and_follows_the_mode(app, tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch, "mac")
    try:
        assert window.toolbar_title.text() == "Devices"
        window.mode_cards_btn.click()
        assert window.toolbar_title.text() == "SD Cards"
        assert window.settings["mode"] == "cards"
        assert window.update_check.parent() is not None          # lives in the Settings window
        assert window.copy_btn.text() == "Create Folders + Copy Cards"
    finally:
        window.close()


def test_recorder_microsd_in_the_cameras_reader_gets_its_own_tile(app, tmp_path, monkeypatch):
    """An FX3 card and a recorder's microSD in one two-slot reader (one USB device). The recorder writes
    plain WAVs that name nobody, so only its contents give it away once the card has been read."""
    import screenshot
    from cardcopy.devices import DRIVE_REMOVABLE, Volume
    fx3 = screenshot.make_cards(str(tmp_path / "cards"))[0]
    recorder = tmp_path / "MICROSD" / "STEREO" / "FOLDER01"
    recorder.mkdir(parents=True)
    for n in range(1, 4):
        (recorder / f"230101_{n:03d}.WAV").write_bytes(b"RIFF\x24\0\0\0WAVEdata\x00\0\0\0" + b"\0" * 2000)
    reader = "usb:01100000:READER"
    volumes = [Volume(root=fx3, label="Untitled", serial="A", drive_type=DRIVE_REMOVABLE, device_key=reader, lun=0),
               Volume(root=str(tmp_path / "MICROSD"), label="NO NAME", serial="B", drive_type=DRIVE_REMOVABLE,
                      device_key=reader, lun=1)]
    monkeypatch.delenv("CARDCOPY_NO_DEVICES", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"base": str(tmp_path)}))
    monkeypatch.setenv("CARDCOPY_HOME", str(home))
    import cardcopy.ui
    monkeypatch.setattr(cardcopy.ui, "find_cards", lambda: [Volume(**v.__dict__) for v in volumes])
    window = cardcopy.ui.MainWindow()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and window.scanning:
            QApplication.processEvents()
            time.sleep(0.02)
        QApplication.processEvents()
        tiles = {cam.default_name: [c.volume.root for c in cam.cards] for cam in window.cameras}
        assert tiles == {"FX3": [fx3], "Audio recorder": [str(tmp_path / "MICROSD")]}
        recorder_cam = next(cam for cam in window.cameras if cam.default_name == "Audio recorder")
        assert window._kind_of(recorder_cam) == "audio"
        assert recorder_cam.cards[0].key in window.checked and window.audio_check.isChecked()
        report = window.diagnostic_report()
        assert "MICROSD" in report and "Audio recorder" in report and "usb:01100000:READER" in report
    finally:
        window.close()


@pytest.mark.parametrize("look", ["glass", "mac"])
def test_audio_goes_into_the_projects_raw_video_folder_by_default(app, tmp_path, monkeypatch, look):
    window = _window(tmp_path, monkeypatch, look)
    try:
        window.project_edit.setText("bob")
        assert window.audio_place.currentData() == "with_video"
        preview = window.preview.toPlainText()
        assert "Raw Audio" not in preview and f"Audio{os.sep}   <-- " in preview      # the Zoom card's line
        zoom = next(p for p in window.panels if p.kind_combo.currentText().endswith("Audio"))
        assert zoom.combo.itemText(0) == "Audio"
        assert window.open_audio_btn.isHidden()                       # no Raw Audio folder to offer
        window.folders_btn.click()                                   # Create folders only
        assert os.path.isdir(os.path.join(window.base_edit.text(), "Raw Video", "bob", "Audio"))
        assert not os.path.exists(os.path.join(window.base_edit.text(), "Raw Audio"))
        window.audio_place.setCurrentIndex(window.audio_place.findData("raw_audio"))     # the old layout, on request
        assert window.settings["audio_place"] == "raw_audio"
        assert f"Raw Audio{os.sep}" in window.preview.toPlainText()
    finally:
        window.close()


def test_an_old_separate_audio_setting_is_not_carried_over(app, tmp_path, monkeypatch):
    """The first previews saved "audio_in_video": false by default; that must not keep audio apart."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"audio_in_video": False}))
    monkeypatch.setenv("CARDCOPY_HOME", str(home))
    from cardcopy import settings
    assert settings.load()["audio_place"] == "with_video"


def test_eject_never_takes_the_disk_the_raw_folder_is_on(app, tmp_path, monkeypatch):
    from cardcopy.cameras import Card
    from cardcopy.devices import DRIVE_REMOVABLE, Volume
    window = _window(tmp_path, monkeypatch, "glass")
    try:
        on_raw_disk = tmp_path / "card"                    # tmp_path is the Raw folder's disk too
        on_raw_disk.mkdir()
        window.cards = [Card(Volume(root=str(on_raw_disk), label="X", drive_type=DRIVE_REMOVABLE))]
        asked = []
        window.eject_volume = lambda root: asked.append(root) or (True, "ejected")
        window._eject_all()
        QApplication.processEvents()
        assert asked == [] and "left connected" in window.log.toPlainText()
    finally:
        window.close()


def test_mac_appearance_switches_palette(app, monkeypatch):
    from cardcopy import aqua
    monkeypatch.setenv("CARDCOPY_APPEARANCE", "dark")
    aqua.apply_appearance(app)
    assert aqua.is_dark()
    monkeypatch.setenv("CARDCOPY_APPEARANCE", "light")
    aqua.apply_appearance(app)
    assert not aqua.is_dark()
