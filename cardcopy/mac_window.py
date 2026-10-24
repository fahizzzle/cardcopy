"""The window as a Mac app lays it out: the same controls as on Windows, in Mac places.

  sidebar     what to show (Devices / SD Cards) and the folders to open, translucent like Finder's
  toolbar     the page's title with what is going on underneath, and Refresh / Add Folder / Eject
  content     the project as a form, the connected devices, then everything about the copy itself
  menu bar    every action again, with the usual shortcuts (Cmd-O, Cmd-R, Cmd-E, Cmd-1/2 ...)
  Settings    Cmd-, : the one choice that is about the app rather than the copy (update checks)

ui.MainWindow builds the controls and owns all the behaviour; this module only places them and adds
the menu bar and the Settings window, so the two platforms cannot drift apart in what they do.
"""
from __future__ import annotations

import os
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QMenuBar, QMessageBox,
                               QVBoxLayout, QWidget)

from . import BUILD_NUMBER, __version__, updates, version_label
from .aqua import STYLE, Logo, Panel, PillButton, Subtitle, ToolGroup, Toolbar, heading, nav_caption, well_text
from .structure import KINDS

HELP_URL = "https://github.com/fahizzzle/cardcopy#readme"
SIDEBAR_W = 220
VERSION = version_label()            # "1.20.0 (build 57)"


def arrange(w) -> None:
    # Mac wording: title case on buttons and in the sidebar, shorter switch labels (details in the tooltips)
    w.mode_cards_btn.setText("SD Cards")
    for button, text in ((w.open_raw_btn, "Raw Folder"), (w.open_project_photo_btn, "Photos"),
                         (w.open_project_video_btn, "Videos"), (w.open_project_audio_btn, "Audio")):
        button.setText(text)
    w.base_btn.setText("Choose…")
    w.spill_btn.setText("Choose…")
    w.verify_check.setText("Verify with checksum")
    w.verify_check.setToolTip("Reads every copied file back and compares it with the card. Slower, and certain.")
    w.receipt_check.setText("Save offload receipt")
    w.eject_check.setText("Eject cards when done")
    w.update_check.setText("Check for updates when CardCopy opens")
    w.missing_btn.setText("What’s Not Copied?")
    w.folders_btn.setText("Create Folders Only")
    w.copy_btn.setText("Create Folders + Copy Cards")

    # ---- sidebar
    side = QVBoxLayout(w.sidebar)
    side.setContentsMargins(10, 52, 10, 12)          # the traffic lights sit in the top 52 points
    side.setSpacing(1)
    side.addWidget(nav_caption("Copy from"))
    side.addWidget(w.mode_cameras_btn)
    side.addWidget(w.mode_cards_btn)
    side.addWidget(nav_caption("Open"))
    for button in (w.open_raw_btn, w.open_photo_btn, w.open_video_btn, w.open_audio_btn):
        side.addWidget(button)
    side.addWidget(nav_caption("This project"))
    for button in (w.open_project_photo_btn, w.open_project_video_btn, w.open_project_audio_btn):
        side.addWidget(button)
    side.addStretch(1)
    version = QLabel(f"CardCopy {VERSION}")
    version.setStyleSheet(STYLE["scan"] + " padding: 0 10px;")
    side.addWidget(version)
    w.sidebar.setFixedWidth(SIDEBAR_W)

    # ---- toolbar: title, what is going on, actions
    toolbar = Toolbar()
    bar = QHBoxLayout(toolbar)
    bar.setContentsMargins(22, 6, 14, 4)
    bar.setSpacing(10)
    titles = QVBoxLayout()
    titles.setSpacing(0)
    title = QLabel("Devices")
    title.setStyleSheet("font-size: 15px; font-weight: 700;")
    w.scan_label = Subtitle("")                       # replaces the plain label: hides itself when empty
    w.scan_label.setStyleSheet(STYLE["scan"])
    w.scan_label.setVisible(False)
    titles.addStretch(1)
    titles.addWidget(title)
    titles.addWidget(w.scan_label)
    titles.addStretch(1)
    bar.addLayout(titles)
    bar.addStretch(1)
    bar.addWidget(ToolGroup([w.refresh_btn, w.add_folder_btn, w.eject_btn]), 0, Qt.AlignVCenter)
    w.mode_cameras_btn.toggled.connect(lambda on: title.setText("Devices" if on else "SD Cards"))
    w.toolbar_title = title

    # ---- project
    kinds_row = QHBoxLayout()
    kinds_row.setSpacing(14)
    for check in (w.all_check, w.photo_check, w.video_check, w.audio_check):
        kinds_row.addWidget(check)
    kinds_row.addStretch(1)
    base_row = QHBoxLayout()
    base_row.setSpacing(6)
    base_row.addWidget(w.base_edit)
    base_row.addWidget(w.base_btn)
    spill_box = QVBoxLayout()
    spill_box.setSpacing(4)
    spill_box.addWidget(w.spill_check)
    spill_box.addWidget(w.spill_row)
    w.spill_row.layout().setSpacing(6)
    cams_row = QHBoxLayout()
    cams_row.setSpacing(6)
    for kind in KINDS:
        cams_row.addWidget(w.cam_labels[kind])
        cams_row.addWidget(w.cam_spins[kind])
        cams_row.addSpacing(10)
    cams_row.addStretch(1)
    extras_row = QHBoxLayout()
    extras_row.setSpacing(14)
    extras_row.addWidget(w.jpeg_check)
    extras_row.addWidget(w.xml_check)
    extras_row.addStretch(1)
    form = QFormLayout()
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(7)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    audio_row = QHBoxLayout()                         # the popup at its natural width, not stretched
    audio_row.addWidget(w.audio_place)
    audio_row.addStretch(1)
    for label, row in (("Project name", w.project_edit), ("Raw folder", base_row), ("Uploading", kinds_row),
                       ("Audio goes to", audio_row), ("Cam folders", cams_row), ("Also copy", extras_row),
                       ("When full", spill_box)):
        caption = QLabel(label)
        caption.setStyleSheet(STYLE["soft"])
        form.addRow(caption, row)
    preview_side = QVBoxLayout()
    preview_side.setSpacing(5)
    created = QLabel("What will be created")
    created.setStyleSheet(STYLE["detail"])
    preview_side.addWidget(created)
    preview_side.addWidget(well_text(w.preview), 1)
    project = Panel(radius=20)
    pv = QHBoxLayout(project)
    pv.setContentsMargins(18, 12, 16, 12)
    pv.setSpacing(22)
    form_side = QVBoxLayout()
    form_side.addLayout(form)
    form_side.addStretch(1)
    pv.addLayout(form_side, 5)
    pv.addLayout(preview_side, 4)

    # ---- devices
    cameras_head = QHBoxLayout()
    cameras_head.setContentsMargins(0, 4, 4, 0)
    cameras_head.setSpacing(12)
    cameras_head.addWidget(w.cameras_heading)
    cameras_head.addStretch(1)
    cameras_head.addWidget(w.empty_note)
    cameras_head.addWidget(w.empty_check)

    # ---- the copy: options, shutdown, progress, buttons
    options = QHBoxLayout()
    options.setSpacing(18)
    for check in (w.verify_check, w.receipt_check, w.eject_check):
        options.addWidget(check)
    options.addStretch(1)
    power = QHBoxLayout()
    power.setSpacing(8)
    for widget in (w.shutdown_check, w.shutdown_mode, w.shutdown_minutes, w.shutdown_at):
        power.addWidget(widget)
    power.addWidget(w.shutdown_status, 1)
    buttons = QHBoxLayout()
    buttons.setSpacing(4)
    buttons.addWidget(w.missing_btn)
    buttons.addWidget(w.folders_btn)
    buttons.addStretch(1)
    buttons.addWidget(w.cancel_btn)
    buttons.addWidget(w.copy_btn)
    copy_panel = Panel(radius=20)
    cp = QVBoxLayout(copy_panel)
    cp.setContentsMargins(16, 10, 12, 8)
    cp.setSpacing(4)
    cp.addLayout(options)
    cp.addLayout(power)
    cp.addWidget(w.bar)
    cp.addLayout(buttons)
    log = well_text(w.log)
    log.setFixedHeight(52)

    body = QVBoxLayout()
    body.setContentsMargins(20, 2, 20, 14)
    body.setSpacing(8)
    body.addWidget(heading("Project"))
    body.addWidget(project)
    body.addLayout(cameras_head)
    body.addWidget(w.camera_scroll, 1)
    body.addWidget(copy_panel)
    body.addWidget(log)
    content = QVBoxLayout(w.workspace)
    content.setContentsMargins(0, 0, 0, 0)
    content.setSpacing(0)
    content.addWidget(toolbar)
    content.addLayout(body, 1)

    central = QWidget()
    root = QHBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    root.addWidget(w.sidebar)
    root.addWidget(w.workspace, 1)
    for widget in (w, central):                       # run up under the title bar: no safe-area margin
        widget.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
    w.setCentralWidget(central)

    w.settings_dialog = SettingsDialog(w)
    if sys.platform == "darwin":                      # a QMenuBar without a parent is the Mac's global menu bar
        w.menu_bar = menus(w)
        if not os.environ.get("CARDCOPY_SELFTEST"):   # once the window is up: one CardCopy, in Applications
            QTimer.singleShot(1200, lambda: tidy_copies(w))


# ------------------------------------------------------------------ settings

class _Found(QObject):
    done = Signal(object)


class SettingsDialog(QDialog):
    """Cmd-, : the app's own preferences. The copy's choices stay in the window, where they are used."""

    def __init__(self, w) -> None:
        super().__init__(w)
        self.window_ = w
        self.setWindowTitle("CardCopy Settings")
        self.setMinimumWidth(460)
        now = PillButton("Check Now")
        self.status = QLabel("")
        self.status.setStyleSheet(STYLE["detail"])
        self.status.setWordWrap(True)
        version = QLabel(f"Version {VERSION}  ·  Framed Horizon LLC")
        version.setStyleSheet(STYLE["detail"])
        group = Panel(radius=20)
        gl = QVBoxLayout(group)
        gl.setContentsMargins(16, 12, 16, 12)
        gl.setSpacing(6)
        gl.addWidget(w.update_check)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(now)
        gl.addLayout(row)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 20)
        lay.setSpacing(10)
        lay.addWidget(Logo("CardCopy"))
        lay.addWidget(version)
        lay.addSpacing(4)
        lay.addWidget(QLabel("Updates"))
        lay.addWidget(group)
        self._found = _Found()
        self._found.done.connect(self._on_checked)
        now.clicked.connect(self.check_now)

    def check_now(self) -> None:
        """Look for a newer CardCopy now, and say so either way (the launch check only speaks up when there is one)."""
        self.status.setText("Checking…")
        threading.Thread(target=lambda: self._found.done.emit(updates.check(__version__, build=BUILD_NUMBER)),
                         daemon=True).start()

    def _on_checked(self, found) -> None:
        if found is None:
            self.status.setText(f"CardCopy {VERSION} is the newest version (or GitHub could not be reached).")
            return
        self.status.setText(f"CardCopy {found.label} is available.")
        self.window_.signals.update_found.emit(found)


# --------------------------------------------------------------------- menus

def _action(menu, text: str, slot, shortcut: str = "", role=None, enabled_by=None) -> QAction:
    action = QAction(text, menu)
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    if role is not None:
        action.setMenuRole(role)
    action.triggered.connect(lambda checked=False: slot())
    if enabled_by is not None:
        action.setData(enabled_by)
    menu.addAction(action)
    return action


def _follow(menu) -> None:
    """Grey out a menu's items whenever the matching button in the window is greyed out."""
    def sync() -> None:
        for action in menu.actions():
            button = action.data()
            if button is not None:
                action.setEnabled(button.isEnabled())
    menu.aboutToShow.connect(sync)


def menus(w) -> QMenuBar:
    bar = QMenuBar(None)

    app = bar.addMenu("CardCopy")
    _action(app, "About CardCopy", lambda: about(w), role=QAction.AboutRole)
    _action(app, "Check for Updates…", lambda: (w.settings_dialog.show(), w.settings_dialog.check_now()),
            role=QAction.ApplicationSpecificRole)
    _action(app, "Settings…", w.settings_dialog.show, "Ctrl+,", role=QAction.PreferencesRole)
    _action(app, "Quit CardCopy", QApplication.closeAllWindows, "Ctrl+Q", role=QAction.QuitRole)

    file = bar.addMenu("File")
    _action(file, "Add Folder…", w._add_folder, "Ctrl+O", enabled_by=w.add_folder_btn)
    _action(file, "Refresh", w.refresh, "Ctrl+R", enabled_by=w.refresh_btn)
    _action(file, "Eject All Cards", lambda: w._eject_all(), "Ctrl+E", enabled_by=w.eject_btn)
    file.addSeparator()
    _action(file, "Create Folders Only", lambda: w._start(copy=False), "Ctrl+Shift+N", enabled_by=w.folders_btn)
    _action(file, "Create Folders + Copy Cards", lambda: w._start(copy=True), "Ctrl+Return", enabled_by=w.copy_btn)
    _action(file, "What’s Not Copied?", w._check_missing, "Ctrl+I", enabled_by=w.missing_btn)
    _action(file, "Stop", w._cancel, "Ctrl+.", enabled_by=w.cancel_btn)
    _follow(file)

    view = bar.addMenu("View")
    _action(view, "Devices", w.mode_cameras_btn.click, "Ctrl+1", enabled_by=w.mode_cameras_btn)
    _action(view, "SD Cards", w.mode_cards_btn.click, "Ctrl+2", enabled_by=w.mode_cards_btn)
    view.addSeparator()
    empty = QAction("Show Empty Cards", view)
    empty.setCheckable(True)
    empty.triggered.connect(w.empty_check.setChecked)
    view.addAction(empty)
    view.aboutToShow.connect(lambda: empty.setChecked(w.empty_check.isChecked()))
    _follow(view)

    go = bar.addMenu("Go")
    for button, text, key in ((w.open_raw_btn, "Raw Folder", "Ctrl+Shift+R"), (w.open_photo_btn, "Raw Photo", ""),
                              (w.open_video_btn, "Raw Video", ""), (w.open_audio_btn, "Raw Audio", ""),
                              (None, "", ""),
                              (w.open_project_photo_btn, "Project Photos", "Ctrl+Shift+P"),
                              (w.open_project_video_btn, "Project Videos", "Ctrl+Shift+V"),
                              (w.open_project_audio_btn, "Project Audio", "")):
        if button is None:
            go.addSeparator()
            continue
        _action(go, text, button.click, key, enabled_by=button)
    _follow(go)

    window = bar.addMenu("Window")
    _action(window, "Minimize", w.showMinimized, "Ctrl+M")
    _action(window, "Zoom", lambda: w.showNormal() if w.isMaximized() else w.showMaximized())

    helper = bar.addMenu("Help")
    _action(helper, "CardCopy Help", lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
    _action(helper, "Copy Diagnostic Report", lambda: copy_report(w))
    return bar


def about(w) -> None:
    QMessageBox.about(w, "About CardCopy",
                      f"<b>CardCopy {VERSION}</b><br><br>Copies the photos, videos and recordings off camera "
                      "cards into tidy project folders. It never deletes and never overwrites anything, on the "
                      "cards or at the destination.<br><br>Made by Framed Horizon LLC.")


def _ask(w, title: str, text: str, yes: str, no: str) -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, parent=w)
    go = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go


def _where(path: str) -> str:
    """The folder a copy is in, said the way a person would: 'Downloads', 'the disk image'."""
    from .mac.copies import removable_media
    if removable_media(path):
        return "the disk image"
    folder, home = os.path.dirname(path), os.path.expanduser("~")
    return folder[len(home) + 1:] if folder.startswith(home + "/") else folder


def tidy_copies(w) -> None:
    """Keep one CardCopy on this Mac: the one in Applications, which is where updates go.

    Run from somewhere else, this copy offers to move into Applications (or to hand over to the copy
    already there); run from Applications, it offers once to move any older copies to the Trash.
    """
    from .mac import copies
    from .mac.selfupdate import app_bundle, is_installed
    me = app_bundle()
    if not is_installed() or not me:
        return
    if me != copies.APP and os.path.isdir(copies.APP):
        there, here = copies.version_of(copies.APP), copies.version_of(me)
        if _ask(w, "Use the CardCopy in Applications?",
                f"This CardCopy ({here}) is running from {_where(me)}. There is another one ({there}) in your "
                "Applications folder.\n\nUpdates go to the one in Applications, so keeping just that one means "
                "you always open the newest." + ("" if copies.removable_media(me) else
                                                  "\n\nThis copy will be moved to the Trash."),
                "Use the One in Applications", "Keep This One"):
            copies.open_app(copies.APP)
            if not copies.removable_media(me):
                copies.to_trash(me)
            QApplication.quit()
        return
    if me != copies.APP:
        if _ask(w, "Move CardCopy to Applications?",
                f"CardCopy is running from {_where(me)}. In your Applications folder it stays put, finds its "
                "updates, and is always the one you open." + ("" if copies.removable_media(me) else
                                                               "\n\nThis copy will be moved to the Trash."),
                "Move to Applications", "Not Now"):
            try:
                copies.copy_to_applications(me)
            except OSError as exc:
                QMessageBox.warning(w, "CardCopy", f"CardCopy could not be copied into Applications:\n{exc}")
                return
            copies.open_app(copies.APP)
            if not copies.removable_media(me):
                copies.to_trash(me)
            QApplication.quit()
        return
    kept = set(w.settings.get("kept_copies") or [])
    others = [p for p in copies.other_copies(me) if p not in kept]
    if not others:
        return
    listing = "\n".join(f"•  {_where(p)}/{os.path.basename(p)}   {copies.version_of(p)}" for p in others)
    if _ask(w, "Other copies of CardCopy",
            f"There are other copies of CardCopy on this Mac:\n\n{listing}\n\nMove them to the Trash, so the one "
            "in Applications (the one that updates) is the only one you can open?",
            "Move to Trash", "Keep Them"):
        left = [p for p in others if not copies.to_trash(p)]
        if left:
            QMessageBox.information(w, "CardCopy", "These could not be moved to the Trash:\n\n" + "\n".join(left))
    else:
        w.settings["kept_copies"] = sorted(kept | set(others))     # asked once; not again for these
        w._save_settings()


def copy_report(w) -> None:
    """Help > Copy Diagnostic Report: what CardCopy sees, on the clipboard, ready to paste into a message."""
    QApplication.clipboard().setText(w.diagnostic_report())
    QMessageBox.information(w, "CardCopy", "The diagnostic report is on the clipboard.\n\n"
                                           "Paste it (Cmd-V) into your message. It lists the cards' names, "
                                           "folders and what CardCopy found on them; nothing from inside the files.")
