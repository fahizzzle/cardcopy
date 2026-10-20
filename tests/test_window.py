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


def test_mac_appearance_switches_palette(app, monkeypatch):
    from cardcopy import aqua
    monkeypatch.setenv("CARDCOPY_APPEARANCE", "dark")
    aqua.apply_appearance(app)
    assert aqua.is_dark()
    monkeypatch.setenv("CARDCOPY_APPEARANCE", "light")
    aqua.apply_appearance(app)
    assert not aqua.is_dark()
