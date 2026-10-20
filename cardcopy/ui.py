"""The window. All the real work lives in the Qt-free modules."""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from . import __version__, gdrive, missing as missing_mod, power, receipt, selfupdate, updates
from . import settings as settings_mod
from .camera_panel import CameraPanel, CardOption, human
from .cameras import Camera, Card, default_kind, group_cards, split_per_card
from .copier import Claims, CopyResult, copy_files
from .devices import drive_mask, eject_volume, find_cards, folder_volume
from .identify import CopyOptions, identify, scan
from .progress import Progress
from .glass import (ASSETS, TEXT_SOFT, Backdrop, LineEdit, Logo, NavButton, Panel, PillButton, ProgressBar, Sidebar,
                    TitleStrip, Toggle, app_stylesheet, enable_blur_behind, heading, hit_test_border, nav_caption, well_text)
from .structure import (KINDS, Plan, build_plan, cam_folder, copy_jobs, create_folders, overlapping,
                        project_path, spill_path)

PICTURE_FILTER = "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)"


def render_plan(plan: Plan, base: str, notes: dict[str, list[str]]) -> str:
    """Indented folder tree, in the order the folders will be created."""
    tree: dict = {}
    for folder in plan.folders:
        node = tree
        for part in os.path.relpath(folder, base).split(os.sep):
            node = node.setdefault(part, {})
    lines: list[str] = []

    def walk(node: dict, path: str, depth: int) -> None:
        for name, child in node.items():
            full = os.path.join(path, name)
            note = "; ".join(notes.get(full.lower(), []))
            lines.append(f"{'    ' * depth}{name}\\{('   <-- ' + note) if note else ''}")
            walk(child, full, depth + 1)

    walk(tree, base, 0)
    return "\n".join(lines)


class Signals(QObject):
    cards_found = Signal(int, list)
    card_scanned = Signal(int, str)
    card_progress = Signal(str, object, str)   # object: byte counts overflow a C int
    card_done = Signal(str, object)
    all_done = Signal()
    ejected = Signal(list)
    card_gap = Signal(str, object)             # one card's "not copied yet" result
    gaps_done = Signal(list)
    space_wait = Signal(str)
    update_found = Signal(object)
    update_progress = Signal(int, int)
    update_ready = Signal(object)
    log = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CardCopy")
        self.setAttribute(Qt.WA_TranslucentBackground)   # the workspace is glass over the desktop
        # frameless: Windows smears the native caption once blur-behind is on, so glass.TitleStrip replaces it
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint)
        self._blur_tried = False
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1420, area.width() - 40), min(1000, area.height() - 50))
        self.settings = settings_mod.load()
        self.signals = Signals()
        self.cards: list[Card] = []
        self.cameras: list[Camera] = []     # real bodies
        self.view: list[Camera] = []        # what is listed: bodies, or one entry per card
        self.checked: set[str] = set()
        self.card_cam: dict[str, int] = {}   # SD cards view: Cam folder picked for one card
        self.seen: set[str] = set()
        self.generation = 0
        self.scanning = False
        self.copying = False
        self.checking = False
        self.cancel = threading.Event()
        self.progress: dict[str, int] = {}
        self.totals: dict[str, int] = {}
        self.last_roots: list[str] = []
        self.panels: list[CameraPanel] = []
        self.run_failed = False                 # the last copy had errors or was cancelled
        self.run_info: dict[str, tuple] = {}    # card key -> (source, camera, slot, destination, planned files)
        self.run_results: dict[str, CopyResult] = {}
        self.run_started = dt.datetime.now()
        self.shutdown_deadline: float | None = None
        self.shutdown_clock: dt.datetime | None = None
        self.drive_watcher: power.DriveWatcher | None = None
        self.drive_online = True                 # so a dropped connection is logged once, not every tick
        self._update_box = None                  # the download dialog, while an update is being fetched
        self._auto_counts: dict[str, int] = {}       # Cam folders per kind, as last worked out
        self.run_progress: Progress | None = None    # speed and time left for the run in hand
        self.card_progress: dict[str, Progress] = {}  # the same, per card, for its own tile
        self.spilled_to = ""                     # set once a run overflows into the backup folder
        self._spill_lock = threading.Lock()      # several card threads can hit "full" at the same moment
        self.shut_down_pc = power.shut_down_pc   # replaced in tests
        self.keep_awake = power.keep_awake       # replaced in tests
        self.eject_volume = eject_volume         # replaced in tests
        self._after_eject = None
        self.awake = False
        self._build()
        self._connect()
        self._load_settings()
        self.mask = drive_mask()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_drives)
        self.timer.start(2000)
        self.power_timer = QTimer(self)
        self.power_timer.timeout.connect(self._power_tick)
        self.power_timer.start(5000)
        QTimer.singleShot(1500, self._check_for_update)   # after the window is up
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        # ---- sidebar: the two views, and the things you do to the card list
        self.mode_cameras_btn = NavButton("Devices", "camera", checkable=True)
        self.mode_cameras_btn.setToolTip("Cameras and recorders, each with its own cards grouped underneath it")
        self.mode_cards_btn = NavButton("SD cards", "card", checkable=True)
        self.mode_cards_btn.setToolTip("Cards plugged into readers: every card is listed on its own and all are copied")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_cameras_btn)
        self.mode_group.addButton(self.mode_cards_btn)
        self.refresh_btn = NavButton("Refresh", "refresh")
        self.add_folder_btn = NavButton("Add folder", "folder")
        self.eject_btn = NavButton("Eject cards", "eject")
        self.eject_btn.setToolTip("Safely remove every connected card (what Eject does in Explorer), then unplug")
        self.add_folder_btn.setToolTip("Use a normal folder as a source (a card copied earlier, a reader that was not detected)")
        self.open_raw_btn = NavButton("Raw folder", "folder")
        self.open_photo_btn = NavButton("Raw Photo", "image")
        self.open_video_btn = NavButton("Raw Video", "film")
        self.open_audio_btn = NavButton("Raw Audio", "audio")
        self.open_project_photo_btn = NavButton("Project photos", "image")
        self.open_project_video_btn = NavButton("Project videos", "film")
        self.open_project_audio_btn = NavButton("Project audio", "audio")
        self.scan_label = QLabel("")
        self.scan_label.setWordWrap(True)
        self.scan_label.setStyleSheet("color: rgba(255,255,255,0.45); padding: 0 6px;")
        side = QVBoxLayout()
        side.setContentsMargins(18, 18, 14, 14)
        side.setSpacing(2)
        side.addWidget(Logo("CardCopy"))
        side.addWidget(nav_caption("Copy from"))
        side.addWidget(self.mode_cameras_btn)
        side.addWidget(self.mode_cards_btn)
        side.addWidget(nav_caption("Sources"))
        side.addWidget(self.refresh_btn)
        side.addWidget(self.add_folder_btn)
        side.addWidget(self.eject_btn)
        side.addWidget(nav_caption("Open"))
        for button in (self.open_raw_btn, self.open_photo_btn, self.open_video_btn, self.open_audio_btn):
            side.addWidget(button)
        side.addWidget(nav_caption("This project"))
        side.addWidget(self.open_project_photo_btn)
        side.addWidget(self.open_project_video_btn)
        side.addWidget(self.open_project_audio_btn)
        self.receipt_check = Toggle("Offload receipt")
        self.receipt_check.setToolTip("Save a text file in the project folder listing every file: where it went, its size, "
                                      "copied / already there / error, and its checksum when Verify is on")
        self.eject_check = Toggle("Eject cards")
        self.eject_check.setToolTip("Eject the cards as soon as a copy finishes without errors (and before an automatic shutdown)")
        after = QVBoxLayout()
        after.setContentsMargins(6, 2, 0, 2)
        after.setSpacing(4)
        after.addWidget(self.receipt_check)
        after.addWidget(self.eject_check)
        side.addWidget(nav_caption("After copying"))
        side.addLayout(after)
        self.update_check = Toggle("Check for updates")
        self.update_check.setToolTip("On launch, look up whether a newer CardCopy exists. Nothing is downloaded or installed by itself.")
        app_box = QVBoxLayout()
        app_box.setContentsMargins(6, 2, 0, 2)
        app_box.addWidget(self.update_check)
        side.addWidget(nav_caption("CardCopy " + __version__))
        side.addLayout(app_box)
        side.addStretch(1)
        side.addWidget(self.scan_label)
        sidebar = Sidebar()
        sidebar.setLayout(side)
        sidebar.setFixedWidth(216)

        # ---- project panel
        self.all_check = Toggle("All")
        self.photo_check = Toggle("Photo")
        self.video_check = Toggle("Video")
        self.audio_check = Toggle("Audio")
        self.audio_check.setToolTip("Field recorders (Zoom, Tascam, Sound Devices ...). Ticks itself when a "
                                    "recorder's card is plugged in; its recordings go to the Raw Audio folder.")
        kinds_row = QHBoxLayout()
        kinds_row.setSpacing(16)
        for w in (self.all_check, self.photo_check, self.video_check, self.audio_check):
            kinds_row.addWidget(w)
        kinds_row.addStretch(1)
        self.project_edit = LineEdit()
        self.project_edit.setPlaceholderText("e.g. Nour")
        self.project_edit.setToolTip("The folder made inside Raw Photo / Raw Video / Raw Audio.\n"
                                     "A / nests it: Rasheda/Reception makes Rasheda\\Reception.")
        self.base_edit = LineEdit()
        self.base_btn = PillButton("Browse", small=True)
        base_row = QHBoxLayout()
        base_row.setSpacing(4)
        base_row.addWidget(self.base_edit)
        base_row.addWidget(self.base_btn)
        self.spill_check = Toggle("Use a backup folder when this one fills up")
        self.spill_check.setToolTip("Off: a full destination pauses the copy until there is room again.\n"
                                    "On: the copy carries on in the backup folder instead and never waits.")
        self.spill_edit = LineEdit()
        self.spill_edit.setPlaceholderText("e.g. D:\\Overflow        another drive with room")
        self.spill_btn = PillButton("Browse", small=True)
        self.spill_row = QWidget()          # one widget, so hiding it collapses the row completely
        spill_row = QHBoxLayout(self.spill_row)
        spill_row.setContentsMargins(0, 0, 0, 0)
        spill_row.setSpacing(4)
        spill_row.addWidget(self.spill_edit)
        spill_row.addWidget(self.spill_btn)
        spill_box = QVBoxLayout()
        spill_box.setSpacing(4)
        spill_box.addWidget(self.spill_check)
        spill_box.addWidget(self.spill_row)
        # One Cam count per Raw folder: three photo bodies and two video ones want Cam 1-3 in Raw Photo
        # and Cam 1-2 in Raw Video. "auto" (0) means one per connected camera of that kind.
        self.cam_spins: dict[str, QSpinBox] = {}
        self.cam_labels: dict[str, QLabel] = {}
        cams_row = QHBoxLayout()
        cams_row.setSpacing(6)
        for kind in KINDS:
            spin = QSpinBox()
            spin.setRange(0, 12)
            spin.setSpecialValueText("auto")
            spin.setFixedWidth(78)
            spin.setToolTip(f"How many Cam folders to make in the {kind} Raw folder.\n"
                            f"auto = one for each {kind} device plugged in.")
            label = QLabel(kind.capitalize())
            label.setStyleSheet(f"color: {TEXT_SOFT};")
            cams_row.addWidget(label)
            cams_row.addWidget(spin)
            cams_row.addSpacing(10)
            self.cam_spins[kind], self.cam_labels[kind] = spin, label
        cams_row.addStretch(1)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.jpeg_check = Toggle("JPG / HEIF photos")
        self.jpeg_check.setToolTip("Off: only RAW files (ARW, CR3, NEF, DNG ...) are copied from the photos")
        self.xml_check = Toggle("Clip XML files")
        self.xml_check.setToolTip("Off: only the video files are copied. On: also the XML metadata file Sony writes beside each clip")
        extras_row = QHBoxLayout()
        extras_row.setSpacing(16)
        extras_row.addWidget(self.jpeg_check)
        extras_row.addWidget(self.xml_check)
        extras_row.addStretch(1)
        for label, row in (("Project name", self.project_edit), ("Raw folder", base_row),
                           ("Uploading", kinds_row), ("Cam folders", cams_row),
                           ("Also copy", extras_row), ("When full", spill_box)):
            caption = QLabel(label)
            caption.setStyleSheet(f"color: {TEXT_SOFT};")
            form.addRow(caption, row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 10))
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        preview_well = well_text(self.preview)

        project_tile = Panel(radius=20)
        pv = QHBoxLayout(project_tile)
        pv.setContentsMargins(22, 12, 22, 14)
        pv.setSpacing(26)
        form_side = QVBoxLayout()
        form_side.addLayout(form)
        form_side.addStretch(1)
        preview_side = QVBoxLayout()
        preview_side.setSpacing(6)
        created = QLabel("What will be created")
        created.setStyleSheet(f"color: {TEXT_SOFT};")
        preview_side.addWidget(created)
        preview_side.addWidget(preview_well, 1)
        pv.addLayout(form_side, 3)
        pv.addLayout(preview_side, 4)

        # ---- cameras / cards
        self.camera_list = QGridLayout()          # two per row
        self.camera_list.setSpacing(12)
        self.camera_list.setContentsMargins(0, 0, 8, 0)
        self.camera_list.setColumnStretch(0, 1)
        self.camera_list.setColumnStretch(1, 1)
        holder = QWidget()
        holder.setLayout(self.camera_list)
        self.camera_scroll = QScrollArea()
        self.camera_scroll.setWidgetResizable(True)
        self.camera_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.camera_scroll.setWidget(holder)
        self.camera_scroll.viewport().installEventFilter(self)   # re-flow the grid when the width changes
        self.camera_columns = 2
        self.cameras_heading = heading("Connected devices")

        # ---- actions
        self.verify_check = Toggle("Verify with checksum (reads every file back; slower)")
        self.missing_btn = PillButton("What is not copied?")
        self.missing_btn.setToolTip("List every file on the ticked cards that is not yet in this project's "
                                    "folders. Reads only: nothing is copied, changed or deleted.")
        self.folders_btn = PillButton("Create folders only")
        self.copy_btn = PillButton("Create folders + copy cards", primary=True)
        self.copy_btn.setDefault(True)
        self.cancel_btn = PillButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.shutdown_check = Toggle("Shut down PC")
        self.shutdown_check.setToolTip("Always off when CardCopy starts. A 60 second countdown with a Cancel button comes first.")
        self.shutdown_mode = QComboBox()
        for label, mode in (("when copying finishes", "copy"), ("when Google Drive has finished syncing", "drive"),
                            ("after a set time", "time"), ("at a set time of day", "at")):
            self.shutdown_mode.addItem(label, mode)
        self.shutdown_minutes = QSpinBox()
        self.shutdown_minutes.setRange(1, 1440)
        self.shutdown_minutes.setSuffix(" min")
        self.shutdown_minutes.setFixedWidth(96)
        self.shutdown_at = QTimeEdit()
        self.shutdown_at.setDisplayFormat("h:mm AP")
        self.shutdown_at.setFixedWidth(110)
        self.shutdown_status = QLabel("")
        self.shutdown_status.setStyleSheet(f"color: {TEXT_SOFT};")
        power_row = QHBoxLayout()
        power_row.setSpacing(10)
        for w in (self.shutdown_check, self.shutdown_mode, self.shutdown_minutes, self.shutdown_at):
            power_row.addWidget(w)
        power_row.addWidget(self.shutdown_status, 1)
        self.empty_check = Toggle("Show empty cards")
        self.empty_note = QLabel("")
        self.empty_note.setStyleSheet(f"color: {TEXT_SOFT};")
        actions = QHBoxLayout()
        actions.setSpacing(2)
        actions.addWidget(self.verify_check)
        actions.addStretch(1)
        for w in (self.missing_btn, self.folders_btn, self.cancel_btn, self.copy_btn):
            actions.addWidget(w)
        self.bar = ProgressBar()
        self.bar.setRange(0, 1000)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        log_well = well_text(self.log)
        log_well.setFixedHeight(62)

        self.workspace = workspace = Backdrop()
        lv = QVBoxLayout(workspace)
        lv.setContentsMargins(30, 0, 0, 14)
        lv.setSpacing(6)
        lv.addWidget(TitleStrip())
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 26, 0)
        body.setSpacing(6)
        lv.addLayout(body)
        lv = body
        lv.addWidget(heading("Project"))
        lv.addWidget(project_tile)
        lv.addSpacing(6)
        cameras_head = QHBoxLayout()
        cameras_head.setContentsMargins(0, 0, 8, 0)
        cameras_head.setSpacing(12)
        cameras_head.addWidget(self.cameras_heading)
        cameras_head.addStretch(1)
        cameras_head.addWidget(self.empty_note)
        cameras_head.addWidget(self.empty_check)
        lv.addLayout(cameras_head)
        lv.addWidget(self.camera_scroll, 1)
        lv.addLayout(power_row)
        lv.addLayout(actions)
        lv.addWidget(self.bar)
        lv.addWidget(log_well)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addWidget(workspace, 1)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        s = self.signals
        s.cards_found.connect(self._on_cards_found)
        s.card_scanned.connect(self._on_card_scanned)
        s.card_progress.connect(self._on_card_progress)
        s.card_done.connect(self._on_card_done)
        s.all_done.connect(self._on_all_done)
        s.log.connect(self._log)
        s.ejected.connect(self._on_ejected)
        s.card_gap.connect(self._on_card_gap)
        s.gaps_done.connect(self._on_gaps_done)
        s.space_wait.connect(self.bar.setFormat)
        s.update_found.connect(self._on_update_found)
        s.update_progress.connect(self._on_update_progress)
        s.update_ready.connect(self._on_update_ready)
        self.refresh_btn.clicked.connect(self.refresh)
        self.mode_cameras_btn.clicked.connect(lambda: self._set_mode("cameras"))
        self.mode_cards_btn.clicked.connect(lambda: self._set_mode("cards"))
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.eject_btn.clicked.connect(lambda: self._eject_all())
        self.eject_check.toggled.connect(lambda: self._save_settings())
        self.receipt_check.toggled.connect(lambda: self._save_settings())
        self.update_check.toggled.connect(lambda: self._save_settings())
        self.base_btn.clicked.connect(self._browse_base)
        self.spill_btn.clicked.connect(self._browse_spill)
        self.spill_check.toggled.connect(self._on_spill_changed)
        self.spill_edit.textChanged.connect(self._update_preview)
        self.project_edit.textChanged.connect(self._update_preview)
        self.base_edit.textChanged.connect(self._update_preview)
        self.all_check.clicked.connect(self._on_all_clicked)
        self.photo_check.toggled.connect(self._on_kinds_changed)
        self.video_check.toggled.connect(self._on_kinds_changed)
        self.audio_check.toggled.connect(self._on_kinds_changed)
        for spin in self.cam_spins.values():
            spin.valueChanged.connect(self._on_cam_count_changed)
        self.jpeg_check.toggled.connect(self._on_options_changed)
        self.empty_check.toggled.connect(self._on_show_empty_changed)
        self.shutdown_check.toggled.connect(self._on_shutdown_changed)
        self.shutdown_mode.currentIndexChanged.connect(self._on_shutdown_changed)
        self.shutdown_minutes.valueChanged.connect(self._on_shutdown_changed)
        self.shutdown_at.timeChanged.connect(self._on_shutdown_changed)
        self.xml_check.toggled.connect(self._on_options_changed)
        self.folders_btn.clicked.connect(lambda: self._start(copy=False))
        self.copy_btn.clicked.connect(lambda: self._start(copy=True))
        self.missing_btn.clicked.connect(self._check_missing)
        self.cancel_btn.clicked.connect(self._cancel)
        for button in (self.open_raw_btn, self.open_photo_btn, self.open_video_btn, self.open_audio_btn,
                       self.open_project_photo_btn, self.open_project_video_btn, self.open_project_audio_btn):
            button.clicked.connect(lambda checked=False, b=button: self._open_folder(b))

    def _load_settings(self) -> None:
        s = self.settings
        for w, value in ((self.photo_check, s["kinds"].get("photo", True)),
                         (self.video_check, s["kinds"].get("video", True)),
                         (self.audio_check, s["kinds"].get("audio", False)),
                         (self.jpeg_check, s["copy_jpeg"]), (self.xml_check, s["copy_xml"]),
                         (self.empty_check, s["show_empty"]), (self.eject_check, s["eject_after"]), (self.receipt_check, s["receipt"]), (self.update_check, s["check_updates"]), (self.verify_check, s["verify"]),
                         (self.spill_check, s["spill"])):
            w.blockSignals(True)
            w.setChecked(bool(value))
            w.blockSignals(False)
        self._sync_all_check()
        for kind, spin in self.cam_spins.items():
            spin.blockSignals(True)
            spin.setValue(int(s["cam_counts"].get(kind, 0)))
            spin.blockSignals(False)
        self.base_edit.setText(s["base"])
        self.spill_edit.setText(s["spill_base"])
        self._on_spill_changed()
        for w, value in ((self.shutdown_mode, max(self.shutdown_mode.findData(s["shutdown_mode"]), 0)),
                         (self.shutdown_minutes, int(s["shutdown_minutes"]))):
            w.blockSignals(True)
            w.setCurrentIndex(value) if w is self.shutdown_mode else w.setValue(value)
            w.blockSignals(False)
        self.shutdown_minutes.setVisible(self.shutdown_mode.currentData() == "time")
        self.shutdown_at.blockSignals(True)
        at = QTime.fromString(str(s["shutdown_at"]), "HH:mm")
        self.shutdown_at.setTime(at if at.isValid() else QTime(2, 0))
        self.shutdown_at.blockSignals(False)
        self.shutdown_at.setVisible(self.shutdown_mode.currentData() == "at")
        (self.mode_cards_btn if s["mode"] == "cards" else self.mode_cameras_btn).setChecked(True)

    def _save_settings(self) -> None:
        s = self.settings
        s["base"] = self.base_edit.text().strip()
        s["spill"] = self.spill_check.isChecked()
        s["spill_base"] = self.spill_edit.text().strip()
        s["kinds"] ={"photo": self.photo_check.isChecked(), "video": self.video_check.isChecked(),
                      "audio": self.audio_check.isChecked()}
        s["cam_counts"] = {kind: spin.value() for kind, spin in self.cam_spins.items()}
        s["verify"] = self.verify_check.isChecked()
        s["show_empty"] = self.empty_check.isChecked()
        s["eject_after"] = self.eject_check.isChecked()
        s["receipt"] = self.receipt_check.isChecked()
        s["check_updates"] = self.update_check.isChecked()
        s["shutdown_mode"] = self.shutdown_mode.currentData()
        s["shutdown_minutes"] = self.shutdown_minutes.value()
        s["shutdown_at"] = self.shutdown_at.time().toString("HH:mm")
        s["copy_jpeg"] = self.jpeg_check.isChecked()
        s["copy_xml"] = self.xml_check.isChecked()
        try:
            settings_mod.save(s)
        except OSError as exc:
            self._log(f"Could not save settings: {exc}")

    def _log(self, text: str) -> None:
        self.log.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {text}")

    def _kinds(self) -> list[str]:
        on = {"photo": self.photo_check.isChecked(), "video": self.video_check.isChecked(),
              "audio": self.audio_check.isChecked()}
        return [k for k in KINDS if on[k]]

    # ------------------------------------------------------------ scanning

    def _poll_drives(self) -> None:
        mask = drive_mask()
        if mask != self.mask and not self.copying:
            self.mask = mask
            self.refresh()

    def refresh(self) -> None:
        if self.copying:
            return
        self.generation += 1
        self.scanning = True
        self.scan_label.setText("Looking for cards…")
        folders = list(self.settings["folders"])
        threading.Thread(target=self._scan_worker, args=(self.generation, folders), daemon=True).start()

    def _scan_worker(self, gen: int, folders: list[str]) -> None:
        try:
            # CARDCOPY_NO_DEVICES: tests use folder sources only and must never touch a real card
            volumes = [] if os.environ.get("CARDCOPY_NO_DEVICES") else find_cards()
        except Exception as exc:  # never let a flaky device kill the scan thread
            self.signals.log.emit(f"Drive scan failed: {exc}")
            volumes = []
        volumes += [folder_volume(p) for p in folders if os.path.isdir(p)]
        cards = [Card(v) for v in volumes]

        def quick(card: Card) -> None:
            try:
                card.info = identify(card.volume.root)
            except Exception as exc:
                self.signals.log.emit(f"{card.volume.root}: could not identify the device ({exc})")

        def full(card: Card) -> None:
            try:
                _, card.files = scan(card.volume.root, card.info)
            except Exception as exc:
                self.signals.log.emit(f"{card.volume.root}: scan failed ({exc})")
            self.signals.card_scanned.emit(gen, card.key)

        if cards:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(quick, cards))
        self.signals.cards_found.emit(gen, cards)
        if cards:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(full, cards))
        self.signals.card_scanned.emit(gen, "")

    def _on_cards_found(self, gen: int, cards: list) -> None:
        if gen != self.generation:
            return
        self.cards = cards
        self.checked &= {c.key for c in cards}
        self.card_cam = {k: v for k, v in self.card_cam.items() if k in {c.key for c in cards}}
        self._rebuild_cameras(tick_new=True)
        self.scan_label.setText("Reading card contents…" if cards else "")
        if not cards:
            self._log("No cards found. Plug the cameras or recorders in (cameras need USB mode: Mass Storage), "
                      "or use Add folder…")

    def _on_card_scanned(self, gen: int, key: str) -> None:
        if gen != self.generation:
            return
        if key == "":
            self.scanning = False
            self.scan_label.setText("")
            if any(not any(c.info.model for c in cam.cards) for cam in self.cameras):
                self._rebuild_cameras()          # a card that names no camera: photo or video is known only now
                return
        card = next((c for c in self.cards if c.key == key), None)
        if card is not None and card.info.audios and not self.audio_check.isChecked():
            # a recorder's card is plugged in: nobody wants to be told afterwards that its audio was left behind
            self.audio_check.setChecked(True)
            self._save_settings()
            self._log(f"{card.volume.root} holds {card.info.audios:,} recording(s): Audio ticked, they go to "
                      f"{self.settings['kind_folders']['audio']}. Untick Audio if you would rather leave them.")
        if card is not None and self._is_empty(card) and not self.empty_check.isChecked():
            self._rebuild_cameras()              # it just turned out to be empty: take it off the list
            return
        self._refresh_rows()
        self._update_preview()

    def _kind_of(self, cam: Camera) -> str:
        """Which Raw folder this camera feeds: remembered per body, else from its model."""
        saved = self.settings["cam_kind"].get(cam.identity)
        if saved:
            return saved
        photo = sum(c.info.raw_size + c.info.jpeg_size for c in cam.cards)
        video = sum(c.info.video_size for c in cam.cards)
        audio = sum(c.info.audio_size for c in cam.cards)
        return default_kind(cam.model if any(c.info.model for c in cam.cards) else "", photo, video, audio)

    def _active_of(self, kind: str) -> list[str]:
        """The cameras of this kind that will actually copy: ones with a ticked card.

        A camera whose cards are all unticked contributes nothing, so it must not reserve a Cam
        folder: untick one of two and the preview should show one folder, not two with an empty one.
        """
        return [cam.identity for cam in self.cameras if self._kind_of(cam) == kind
                and any(card.key in self.checked for card in cam.cards)]

    def _devices_of(self, kind: str) -> int:
        """How many cameras of this kind are plugged in AND ticked (bodies, not cards)."""
        return len(self._active_of(kind))

    def _cam_count(self, kind: str) -> int:
        """Cam folders for one Raw folder: what was typed, or one per device of that kind.

        Each kind counts on its own, so three photo bodies and two video ones give Raw Photo three
        Cam folders and Raw Video two. With nothing plugged in yet, one -- enough for "Create
        folders only" to make something sensible before the cameras arrive.
        """
        typed = self.cam_spins[kind].value() if kind in self.cam_spins else 0
        return typed if typed else max(1, self._devices_of(kind))

    def _cam_counts(self) -> dict[str, int]:
        return {kind: self._cam_count(kind) for kind in KINDS}

    def _cam_numbers(self, kind: str) -> dict[str, int]:
        """A Cam folder for each camera of this kind that is copying, no two sharing one.

        A number the user picked themselves wins, as long as it fits the folders that exist and
        nobody else has it. Everything else takes the next free folder, so unticking a camera
        closes up the gap instead of leaving two cameras pointed at the same Cam.
        """
        count = self._cam_count(kind)
        active = self._active_of(kind)
        chosen = self.settings["cam_assign"]
        numbers: dict[str, int] = {}
        taken: set[int] = set()
        for identity in active:
            try:
                want = int(chosen.get(identity, 0) or 0)
            except (TypeError, ValueError):
                want = 0
            if 1 <= want <= count and want not in taken:
                numbers[identity] = want
                taken.add(want)
        free = [n for n in range(1, count + 1) if n not in taken]
        for identity in active:
            if identity not in numbers:
                numbers[identity] = free.pop(0) if free else count
        return numbers

    def _cam_of(self, cam: Camera) -> int:
        """The Cam folder number this camera copies into."""
        kind = self._kind_of(cam)
        numbers = self._cam_numbers(kind)
        if cam.identity in numbers:
            return numbers[cam.identity]
        # not copying just now (no ticked card): show whatever it would have, within range
        stored = self.settings["cam_assign"].get(cam.identity, 1)
        try:
            stored = int(stored)
        except (TypeError, ValueError):
            stored = 1
        return min(max(stored, 1), self._cam_count(kind))

    def _kind_off(self, cam: Camera) -> str:
        """'Video' when this device feeds a Raw folder the Uploading row has switched off, else ''.

        Its cards are left ticked -- the choice is the user's -- but nothing is copied from them,
        so the tile has to say so instead of showing a file count it will not honour.
        """
        kind = self._kind_of(cam)
        return "" if kind in self._kinds() else kind.capitalize()

    def _options(self) -> CopyOptions:
        return CopyOptions(jpeg=self.jpeg_check.isChecked(), xml=self.xml_check.isChecked())

    def _size_of(self, card: Card) -> int:
        return card.info.selected(self._options())[1]

    @staticmethod
    def _is_empty(card: Card) -> bool:
        """Scanned, and nothing on it that CardCopy could ever copy."""
        i = card.info
        return i.scanned and not (i.raws or i.jpegs or i.videos or i.audios)

    def _on_show_empty_changed(self) -> None:
        self._save_settings()
        self._rebuild_cameras()

    def _on_options_changed(self) -> None:
        self._refresh_rows()
        self._update_preview()

    def _rebuild_cameras(self, tick_new: bool = False) -> None:
        self.cameras = group_cards(self.cards, self.settings["camera_names"])
        cards_mode = self.settings["mode"] == "cards"
        if tick_new:
            # a camera we have not seen before starts with its first card ticked;
            # in the SD cards view every new card is ticked
            for cam in self.cameras:
                keys = [c.key for c in cam.cards]
                if cards_mode:
                    self.checked.update(k for k in keys if k not in self.seen)
                elif not any(k in self.seen for k in keys):
                    self.checked.add(keys[0])
                self.seen.update(keys)
        shown = self.cameras
        hidden = [c for cam in self.cameras for c in cam.cards if self._is_empty(c)]
        if hidden and not self.empty_check.isChecked():
            shown = [Camera(cam.identity, cam.model, cam.default_name, cam.name,
                            [c for c in cam.cards if not self._is_empty(c)]) for cam in self.cameras]
            shown = [cam for cam in shown if cam.cards]
            self.checked -= {c.key for c in hidden}
        self.empty_note.setText(f"{len(hidden)} empty card{'s' if len(hidden) != 1 else ''} hidden"
                                if hidden and not self.empty_check.isChecked() else "")
        self.view = split_per_card(shown) if cards_mode else shown
        self.cameras_heading.setText("Connected SD cards" if cards_mode else "Connected devices")
        for row in range(self.camera_list.rowCount()):
            self.camera_list.setRowStretch(row, 0)
        while self.camera_list.count():
            widget = self.camera_list.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.panels = []
        for index, cam in enumerate(self.view):
            panel = CameraPanel(cam, self._cam_of(cam), self._cam_count(self._kind_of(cam)),
                                self.settings["camera_pictures"].get(cam.identity, ""), self.checked,
                                self._kind_of(cam), self.settings["kind_folders"],
                                self.card_cam if cards_mode else None, self._options(),
                                self._kind_off(cam))
            panel.card_cam_chosen.connect(self._on_card_cam_chosen)
            panel.card_toggled.connect(self._on_card_toggled)
            panel.cam_chosen.connect(self._on_cam_chosen)
            panel.kind_chosen.connect(self._on_kind_chosen)
            panel.rename_requested.connect(self._rename_camera)
            panel.picture_requested.connect(self._set_picture)
            panel.set_locked(self.copying)
            self.panels.append(panel)
            self.camera_list.addWidget(panel, index // 2, index % 2, Qt.AlignTop)   # _flow_cameras() settles the columns
        if not self.view:
            empty = QLabel("No devices found yet.\nSet each camera's USB mode to Mass Storage and plug it in "
                           "(recorders and card readers just appear); it will show up here by itself.")
            empty.setStyleSheet(f"color: {TEXT_SOFT}; padding: 30px;")
            self.camera_list.addWidget(empty, 0, 0, 1, 2)
        self.camera_list.setRowStretch((len(self.view) + 1) // 2 + 1, 1)   # pack rows to the top
        self._flow_cameras(force=True)
        self._update_preview()

    def _flow_cameras(self, force: bool = False) -> None:
        """Two cameras per row while two fit side by side, otherwise one: nothing is ever cut off at the right."""
        if not self.panels:
            return
        widest = max(p.minimumSizeHint().width() for p in self.panels)
        room = self.camera_scroll.viewport().width() - 8
        columns = 2 if 2 * widest + self.camera_list.spacing() <= room else 1
        if columns == self.camera_columns and not force:
            return
        self.camera_columns = columns
        for row in range(self.camera_list.rowCount()):
            self.camera_list.setRowStretch(row, 0)
        for panel in self.panels:
            self.camera_list.removeWidget(panel)
        for index, panel in enumerate(self.panels):
            if columns == 2:
                self.camera_list.addWidget(panel, index // 2, index % 2, Qt.AlignTop)
            else:
                self.camera_list.addWidget(panel, index, 0, 1, 2, Qt.AlignTop)
        rows = (len(self.panels) + columns - 1) // columns
        self.camera_list.setRowStretch(rows + 1, 1)

    def eventFilter(self, watched, event):
        if watched is self.camera_scroll.viewport() and event.type() == QEvent.Resize:
            self._flow_cameras()
        return super().eventFilter(watched, event)

    def _option(self, key: str) -> CardOption | None:
        for panel in self.panels:
            if key in panel.options:
                return panel.options[key]
        return None

    def _refresh_rows(self) -> None:
        off = {c.key: self._kind_off(cam) for cam in self.cameras for c in cam.cards}
        for card in self.cards:
            option = self._option(card.key)
            if option is not None:
                option.update_card(card, self._options(), off.get(card.key, ""))

    def _on_card_toggled(self, key: str, on: bool) -> None:
        if on:
            self.checked.add(key)
        else:
            self.checked.discard(key)
        if self._cam_counts() != self._auto_counts:
            # ticking the last card of a camera changes how many Cam folders there are, which the
            # tiles' own drop-downs have to follow; redraw once this signal has returned
            self._auto_counts = self._cam_counts()
            QTimer.singleShot(0, self._rebuild_cameras)
        self._update_preview()

    def _on_cam_chosen(self, identity: str, number: int) -> None:
        self.settings["cam_assign"][identity] = number
        self._after_choice()

    def _on_card_cam_chosen(self, key: str, number: int) -> None:
        self.card_cam[key] = number
        self._update_preview()

    def _cam_for(self, card: Card, cam: Camera) -> int:
        """Cam folder for one card: its own pick in the SD cards view, else the camera's."""
        if self.settings["mode"] == "cards" and card.key in self.card_cam:
            return min(self.card_cam[card.key], self._cam_count(self._kind_of(cam)))
        return self._cam_of(cam)

    def _on_kind_chosen(self, identity: str, kind: str) -> None:
        self.settings["cam_kind"][identity] = kind
        self._after_choice()

    def _after_choice(self) -> None:
        self._save_settings()
        self._update_preview()
        if self.settings["mode"] == "cards":
            # the same body can be on several tiles: redraw them, once this signal has returned
            QTimer.singleShot(0, self._rebuild_cameras)

    def _set_mode(self, mode: str) -> None:
        if mode == self.settings["mode"]:
            return
        self.settings["mode"] = mode
        self._save_settings()
        # cards view copies everything (the backup card's duplicates are skipped);
        # camera view starts from one card per body
        if mode == "cards":
            self.checked = {c.key for c in self.cards}
        else:
            self.checked = {cam.cards[0].key for cam in self.cameras}
        self._rebuild_cameras()

    def _on_cam_count_changed(self) -> None:
        self._rebuild_cameras()

    def _on_all_clicked(self, checked: bool) -> None:
        for w in (self.photo_check, self.video_check, self.audio_check):
            w.setChecked(checked)

    def _sync_all_check(self) -> None:
        self.all_check.setChecked(self.photo_check.isChecked() and self.video_check.isChecked()
                                  and self.audio_check.isChecked())

    def _on_kinds_changed(self) -> None:
        self._sync_all_check()
        self._refresh_rows()          # the cards of a switched-off kind stop claiming they will copy
        self._update_preview()

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder to copy from")
        if path:
            path = os.path.normpath(path)
            if path not in self.settings["folders"]:
                self.settings["folders"].append(path)
            self.refresh()

    def _rename_camera(self, identity: str) -> None:
        cam = next((c for c in self.cameras if c.identity == identity), None)
        if cam is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename device",
            f"Name for {cam.default_name}\n(only how it is listed here; remembered for next time, blank = reset)",
            text=cam.name)
        if not ok:
            return
        names = self.settings["camera_names"]
        if name.strip():
            names[identity] = name.strip()
        else:
            names.pop(identity, None)
        self._save_settings()
        self._rebuild_cameras()

    def _set_picture(self, identity: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Picture of this device", "", PICTURE_FILTER)
        if not path:
            return
        # remembered per camera body; the picture file itself is only read
        self.settings["camera_pictures"][identity] = os.path.normpath(path)
        self._save_settings()
        self._rebuild_cameras()

    # ------------------------------------------------------------- project

    def _on_spill_changed(self) -> None:
        # the folder box only exists once the switch is on: off, there is nothing to say about it
        self.spill_row.setVisible(self.spill_check.isChecked())
        self._save_settings()
        self._update_preview()

    def _browse_spill(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Backup folder to use when the Raw folder fills up",
                                                  self.spill_edit.text().strip() or self.base_edit.text().strip())
        if folder:
            self.spill_edit.setText(os.path.normpath(folder))
            self._save_settings()

    def _spill_base(self) -> str:
        """The backup folder, or '' when there is nothing usable to fall back to."""
        if not self.spill_check.isChecked():
            return ""
        return self.spill_edit.text().strip()

    def _spill_to(self, dst: str) -> str | None:
        """Where a planned file goes instead once the Raw folder is full."""
        return spill_path(dst, self.base_edit.text().strip(), self._spill_base())

    def _browse_base(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Raw folder (holds Raw Photo and Raw Video)", self.base_edit.text())
        if path:
            self.base_edit.setText(os.path.normpath(path))

    def _selected(self) -> list[tuple[Card, Camera]]:
        return [(card, cam) for cam in self.cameras for card in cam.cards
                if card.key in self.checked and self._kind_of(cam) in self._kinds()]

    def _plan(self) -> Plan | None:
        project = self.project_edit.text().strip()
        base = self.base_edit.text().strip()
        if not project or not base or not self._kinds():
            return None
        plan = build_plan(base, project, self._kinds(), self._cam_counts(), self.settings["kind_folders"])
        # a name made only of illegal characters would target Raw Photo itself
        return plan if project_path(project) else None

    def _update_preview(self) -> None:
        self._update_open_buttons()
        plan = self._plan()
        if plan is None:
            self.preview.setPlainText(
                "Enter a project name, pick the Raw folder, and tick what you are uploading\n"
                "(Photo, Video, Audio).\n\n"
                "The folders CardCopy will create show up here, with the cards that feed each one.")
            return
        notes: dict[str, list[str]] = {}
        for card, cam in self._selected():
            size = f" {human(self._size_of(card))}" if card.info.scanned else ""
            files = f" {card.info.selected(self._options())[0]:,} files" if card.info.scanned else ""
            notes.setdefault(plan.dest(self._kind_of(cam), self._cam_for(card, cam)).lower(), []).append(
                f"{card.volume.letter or card.volume.label} {cam.name} {card.slot}{files}{size}")
        text = render_plan(plan, self.base_edit.text().strip(), notes)
        total = sum(self._size_of(card) for card, _ in self._selected())
        if total:
            text += f"\n\nTo copy: {human(total)} from {len(self._selected())} card(s)"
        if self._spill_base():
            spare, spare_drive = gdrive.effective_free_space(self._spill_base())
            text += (f"\n\nIf this folder fills up, the rest goes to\n    {self._spill_base()}"
                     f"   ({human(spare)} free on {spare_drive})\nin the same Raw ... \\project\\Cam layout.")
        self.preview.setPlainText(text)

    def _open_targets(self) -> dict:
        """Button -> folder it opens ('' when it cannot be worked out yet)."""
        base = self.base_edit.text().strip()
        names = self.settings["kind_folders"]
        project = project_path(self.project_edit.text().strip())
        photo, video = os.path.join(base, names["photo"]), os.path.join(base, names["video"])
        audio = os.path.join(base, names.get("audio", "Raw Audio"))
        return {self.open_raw_btn: base,
                self.open_photo_btn: photo if base else "",
                self.open_video_btn: video if base else "",
                self.open_audio_btn: audio if base else "",
                self.open_project_photo_btn: os.path.join(photo, project) if base and project else "",
                self.open_project_video_btn: os.path.join(video, project) if base and project else "",
                self.open_project_audio_btn: os.path.join(audio, project) if base and project else ""}

    def _update_open_buttons(self) -> None:
        """A button is live only while its folder exists (a project's folders appear once they are created)."""
        for button, path in self._open_targets().items():
            exists = bool(path) and os.path.isdir(path)
            button.setEnabled(exists)
            button.setToolTip(path if exists else (f"Not there yet: {path}" if path else "Enter a project name first"))

    def _open_folder(self, button) -> None:
        path = self._open_targets().get(button, "")
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self._update_open_buttons()

    # ------------------------------------------------------------- copying

    def _start(self, copy: bool) -> None:
        if self.copying or self.checking:      # one job at a time, whatever calls this
            return
        base = self.base_edit.text().strip()
        if not self._kinds():
            QMessageBox.warning(self, "CardCopy", "Tick Photo, Video or both.")
            return
        plan = self._plan()
        if plan is None:
            QMessageBox.warning(self, "CardCopy", "Enter a project name.")
            return
        if not os.path.isdir(base):
            QMessageBox.warning(self, "CardCopy", f"This folder does not exist:\n{base}")
            return
        if self.spill_check.isChecked():
            spill = self.spill_edit.text().strip()
            if not spill or not os.path.isdir(spill):
                QMessageBox.warning(self, "CardCopy", "Pick a backup folder that exists, or switch "
                                                      "\"Use a backup folder when this one fills up\" off.")
                return
            if overlapping(base, spill):
                QMessageBox.warning(self, "CardCopy", "The backup folder cannot be inside the Raw folder, or the "
                                                      "other way round.\n\nPick a folder on another drive: the "
                                                      "point of it is somewhere to go when this drive runs out of "
                                                      "room, and one folder inside the other runs out at the very "
                                                      "same moment.")
                return
            if os.path.splitdrive(os.path.abspath(spill))[0].lower() == \
                    os.path.splitdrive(os.path.abspath(base))[0].lower():
                drive = os.path.splitdrive(os.path.abspath(base))[0] or "that drive"
                if QMessageBox.question(
                        self, "CardCopy",
                        f"The backup folder is on {drive}, the same drive as the Raw folder.\n\n"
                        "It will run out of room at the same moment, so it would not actually catch "
                        "anything. A folder on another drive would.\n\nUse it anyway?") != QMessageBox.Yes:
                    return
        selected = self._selected()
        if copy:
            if not selected:
                QMessageBox.warning(self, "CardCopy", "Tick at least one card to copy.\n(A photo camera's cards only "
                                                      "count while Photo is on, a video camera's while Video is on, "
                                                      "a recorder's while Audio is on.)")
                return
            if self.scanning or any(card.files is None for card, _ in selected):
                QMessageBox.information(self, "CardCopy", "Still reading the cards. Try again in a moment.")
                return
            total = sum(self._size_of(card) for card, _ in selected)
            if not total:
                QMessageBox.information(self, "CardCopy", "Nothing to copy from the ticked cards with the current \"Also copy\" choices (RAW photos and video clips only by default).")
                return
            free, drive = gdrive.effective_free_space(base)
            where = f"on {drive}"
            if gdrive.is_drive_path(base):
                # files wait in Drive's local cache until they are uploaded: that drive needs the room
                where = f"on {drive}, where Google Drive keeps files until they are uploaded"
            if free and free < total:
                if self._spill_base():
                    spare, spare_drive = gdrive.effective_free_space(self._spill_base())
                    plan_b = (f"\n\nWhen it fills up the copy carries straight on in {self._spill_base()} "
                              f"({human(spare)} free on {spare_drive}), without pausing.")
                else:
                    plan_b = ("\n\nYou can still start: if it fills up, CardCopy pauses and carries on by itself "
                              "as space frees up. Nothing is lost either way.")
                if QMessageBox.question(
                        self, "CardCopy",
                        f"The cards hold {human(total)} but only {human(free)} is free {where}.{plan_b}"
                        "\n\nStart copying?"
                ) != QMessageBox.Yes:
                    return
        self._save_settings()
        try:
            made = create_folders(plan)
        except OSError as exc:
            QMessageBox.critical(self, "CardCopy", f"Could not create the folders:\n{exc}")
            return
        self.last_roots = list(plan.roots.values())
        self._update_open_buttons()
        for root in self.last_roots:
            self._log(f"Project folder: {root}")
        self._log(f"{made} new folder(s) created")
        if not copy:
            return

        jobs = []
        self.run_info, self.run_results, self.run_started = {}, {}, dt.datetime.now()
        for card, cam in selected:
            kind = self._kind_of(cam)
            files = copy_jobs(card.files, plan, self._cam_for(card, cam), kind, self._options())
            if files:
                jobs.append((card, files))
                self.run_info[card.key] = (card.volume.root, cam.name, card.slot,
                                           plan.dest(kind, self._cam_for(card, cam)), len(files))
                self._log(f"{card.volume.root} ({cam.name} {card.slot}) -> {self.settings['kind_folders'][kind]}\\"
                          f"{cam_folder(self._cam_for(card, cam))}: {len(files)} files")
        self.copying = True
        self._update_awake()
        self.run_failed = False
        self.spilled_to = ""
        self.cancel.clear()
        if self._spill_base():
            self._log(f"If {base} fills up, the rest goes to {self._spill_base()} instead of waiting.")
        self.progress = {card.key: 0 for card, _ in jobs}
        self.totals = {card.key: sum(e.size for e, _ in files) for card, files in jobs}
        self.run_progress = Progress(sum(self.totals.values()))
        self.card_progress = {key: Progress(total) for key, total in self.totals.items()}
        self._set_busy(True)
        threading.Thread(target=self._copy_worker, args=(jobs, self.verify_check.isChecked()), daemon=True).start()

    def _copy_worker(self, jobs: list, verify: bool) -> None:
        claims = Claims()

        def run(job) -> None:
            card, files = job
            total = self.totals[card.key]
            last = [0.0]

            def on_progress(done: int, rel: str) -> None:
                now = time.monotonic()
                if now - last[0] >= 0.1 or done >= total:
                    last[0] = now
                    self.signals.card_progress.emit(card.key, done, rel)

            try:
                result = copy_files(card.volume.root, files, verify=verify, cancel=self.cancel,
                                    wait_for_space=self._wait_for_space, spill_to=self._spill_for_copy,
                                    claims=claims, on_progress=on_progress)
            except Exception as exc:
                result = CopyResult(errors=[str(exc)])
            self.signals.card_done.emit(card.key, result)

        # the cards are separate devices, so copy them side by side
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            list(pool.map(run, jobs))
        self.signals.all_done.emit()

    def _on_card_progress(self, key: str, done: int, rel: str) -> None:
        self.progress[key] = done
        total = self.totals.get(key, 0)
        option = self._option(key)
        if option is not None and total:
            bits = [f"{100 * done / total:.0f}%"]
            card = self.card_progress.get(key)
            if card is not None:
                card.update(done)
                if card.speed():                 # nothing is claimed until there is enough to measure
                    bits.append(f"{human(card.speed())}/s")
            bits.append(os.path.basename(rel))
            option.set_status("  ·  ".join(bits))
        grand = sum(self.totals.values())
        if grand:
            so_far = sum(self.progress.values())
            self.bar.setValue(int(1000 * so_far / grand))
            if self.run_progress is not None:
                self.run_progress.update(so_far)
                self.bar.setFormat(self.run_progress.text())
            else:
                self.bar.setFormat(f"{human(so_far)} of {human(grand)}")

    def _on_card_done(self, key: str, result: CopyResult) -> None:
        option = self._option(key)
        name = key.split("|")[0]
        self.run_results[key] = result
        if result.cancelled or result.errors:
            self.run_failed = True
        if result.cancelled:
            status = "cancelled"
        elif result.errors:
            status = f"{len(result.errors)} error(s)"
        else:
            status = "done" + (f" ({result.skipped} already there)" if result.skipped else "")
        if option is not None:
            option.set_status(status)
        self._log(f"{name}: {status}; {result.copied} copied ({human(result.bytes_copied)}), {result.skipped} skipped")
        for err in result.errors[:50]:
            self._log(f"   ERROR {err}")
        if result.aborted:
            self._log("   " + result.aborted)

    def _on_all_done(self) -> None:
        self.copying = False
        self.run_progress = None
        self.card_progress = {}
        self._set_busy(False)
        self._update_awake()
        self._log("Cancelled. Run again to continue where it stopped." if self.cancel.is_set()
                  else "Finished. Google Drive keeps uploading in the background; leave the PC on until it is done.")
        if self.spilled_to:
            self._log(f"Part of this copy went to the backup folder {self.spilled_to} because the Raw folder "
                      "filled up. Move it across once there is room; until then this shoot lives in two places.")
        QApplication.alert(self)
        self._write_receipts()
        if self.eject_check.isChecked() and not self.run_failed:
            self._eject_all(then=self._after_copy_for_shutdown)
        else:
            if self.eject_check.isChecked():
                self._log("Cards NOT ejected: the copy had errors or was cancelled, so they stay connected for another try.")
            self._after_copy_for_shutdown()

    def _spill_for_copy(self, dst: str) -> str | None:
        """Called from a copy thread the moment a destination fills up, before any waiting.

        Returns the same file's place in the backup folder, and says so in the log the first time —
        the copy quietly moving to another drive is exactly the kind of thing you want to be told.
        """
        alt = self._spill_to(dst)
        if not alt:
            return None
        with self._spill_lock:
            if not self.spilled_to:
                self.spilled_to = self._spill_base()
                self.signals.log.emit(
                    f"The Raw folder is full. Carrying on in the backup folder instead: {self.spilled_to}. "
                    "Nothing is lost and nothing waits; what is already copied stays where it is.")
                self.signals.space_wait.emit(f"main folder full — copying into {self.spilled_to}")
        return alt

    def _wait_for_space(self, needed: int, rel: str, dst: str) -> bool:
        """Called from a copy thread when a destination has filled up and there is no backup folder
        to fall back to (or the backup filled up too): hold this card's copy until there is room
        again. False means the run was cancelled while waiting.

        Copying into Google Drive fills its local cache far faster than Drive can upload, so running
        out of room mid-offload is normal rather than exceptional. Waiting costs time; the alternative
        (failing every remaining file in seconds) costs the whole night.
        """
        base = os.path.dirname(dst) or self.settings["base"]     # whichever folder is in use now
        margin = 2 * 1024 ** 3          # don't restart the instant it is free: leave Drive some room
        told = False
        while not self.cancel.is_set():
            free, drive = gdrive.effective_free_space(base)
            if free >= needed + margin:
                if told:
                    self.signals.log.emit(f"{human(free)} free on {drive} again: carrying on.")
                return True
            if not told:
                told = True
                self.signals.log.emit(
                    f"No room on {drive}: {human(free)} free, {human(needed)} needed for "
                    f"{os.path.basename(rel)}. Paused — nothing is lost, and copying carries on by "
                    "itself as space frees up. Cancel whenever you like.")
            self.signals.space_wait.emit(f"paused — waiting for room on {drive} ({human(free)} free)")
            self.cancel.wait(20)
        return False

    def _write_receipts(self) -> None:
        """One receipt per project folder that cards were copied into (photo and video projects are separate)."""
        if not self.receipt_check.isChecked():
            return
        by_project: dict[str, list] = {}
        for key, (source, camera, slot, destination, planned) in self.run_info.items():
            report = receipt.CardReport(source, camera, slot, destination, planned,
                                        self.run_results.get(key) or CopyResult(cancelled=True))
            by_project.setdefault(os.path.dirname(destination), []).append(report)
        options = self._options()
        also = (", JPG/HEIF photos" if options.jpeg else "") + (", clip XML files" if options.xml else "")
        finished = dt.datetime.now()
        for folder, reports in by_project.items():
            text = receipt.build(self.project_edit.text().strip(), self.run_started, finished, reports,
                                 verified=self.verify_check.isChecked(), also_copied=also, version=__version__)
            try:
                self._log("Receipt: " + receipt.write(folder, text, finished))
            except OSError as exc:
                self._log(f"Could not save the receipt in {folder}: {exc}")

    # ------------------------------------------------ what is not copied yet

    def _check_missing(self) -> None:
        """List every file on the ticked cards that is not in this project's folders.

        Reads only: nothing is copied, ejected, changed or deleted, whatever the answer turns out
        to be. Never while a copy is running.
        """
        if self.copying or self.checking:
            return
        plan = self._plan()
        if plan is None:
            QMessageBox.warning(self, "CardCopy", "Enter the project name and Raw folder these cards should be in.")
            return
        selected = self._selected()
        if not selected:
            QMessageBox.warning(self, "CardCopy", "Tick the cards to check.")
            return
        if self.scanning or any(card.files is None for card, _ in selected):
            QMessageBox.information(self, "CardCopy", "Still reading the cards. Try again in a moment.")
            return
        jobs = []
        for card, cam in selected:
            kind = self._kind_of(cam)
            files = copy_jobs(card.files, plan, self._cam_for(card, cam), kind, self._options())
            if files:
                jobs.append((card, cam, plan.dest(kind, self._cam_for(card, cam)), files))
        if not jobs:
            QMessageBox.information(self, "CardCopy", "Nothing on the ticked cards would be copied, so there is "
                                                      "nothing to check.")
            return
        deep = self.verify_check.isChecked()
        self.checking = True
        self.cancel.clear()
        self.progress = {card.key: 0 for card, _, _, _ in jobs}
        self.totals = {card.key: sum(e.size for e, _ in files) for card, _, _, files in jobs}
        self.run_progress = Progress(sum(self.totals.values()))
        self.card_progress = {key: Progress(total) for key, total in self.totals.items()}
        self._set_busy(True)
        self._log(f"Checking {len(jobs)} card(s) against {', '.join(sorted(set(plan.roots.values())))} — "
                  + ("reading every file back byte for byte (Verify is on); this takes as long as a copy."
                     if deep else "comparing name, size and date. Tick Verify to compare the contents too."))
        threading.Thread(target=self._missing_worker, args=(jobs, deep), daemon=True).start()

    def _missing_worker(self, jobs: list, deep: bool) -> None:
        def run(job):
            card, cam, destination, files = job
            total = self.totals[card.key]
            last = [0.0]

            def on_progress(done: int, rel: str) -> None:
                now = time.monotonic()
                if now - last[0] >= 0.1 or done >= total:
                    last[0] = now
                    self.signals.card_progress.emit(card.key, done, rel)

            where = card.volume.letter or os.path.basename(card.volume.root.rstrip(os.sep))
            label = f"{cam.name} {card.slot} ({where})".strip()
            try:
                gap = missing_mod.check_jobs(card.volume.root, files, deep=deep, label=label,
                                             destination=destination, cancel=self.cancel,
                                             spill_to=self._spill_to, on_progress=on_progress)
            except Exception as exc:                  # a card pulled out mid-check, say
                gap = missing_mod.Gap(label=label, source=card.volume.root, destination=destination,
                                      total=len(files), different=[(str(exc), 0)])
            self.signals.card_gap.emit(card.key, gap)
            return gap

        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            gaps = list(pool.map(run, jobs))
        self.signals.gaps_done.emit(gaps)

    def _on_card_gap(self, key: str, gap) -> None:
        option = self._option(key)
        if option is not None:
            option.set_status("all copied" if gap.all_copied() else f"{gap.short:,} not copied")
        self._log(f"{gap.label}: {gap.summary()}")

    def _on_gaps_done(self, gaps: list) -> None:
        self.checking = False
        self._set_busy(False)
        self.run_progress = None
        self.card_progress = {}
        self.bar.setValue(0)
        self.bar.setFormat("")
        QApplication.alert(self)
        short = sum(g.short for g in gaps)
        text = missing_mod.report(self.project_edit.text().strip(), gaps, version=__version__)

        box = QDialog(self)
        box.setWindowTitle("CardCopy")
        box.setModal(True)
        if any(g.cancelled for g in gaps):
            head = "The check was cancelled, so this list is incomplete."
        elif short:
            head = (f"{short:,} file(s) are not copied yet — {missing_mod.human(sum(g.size for g in gaps))} "
                    f"across {len([g for g in gaps if g.short])} card(s).\n"
                    "Running the copy again brings across exactly these; what is already there is skipped.")
        else:
            head = f"Everything on {len(gaps)} card(s) is already in the project folders."
        title = QLabel(head)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 12pt;")
        listing = QPlainTextEdit()
        listing.setReadOnly(True)
        listing.setFont(QFont("Consolas", 9))
        listing.setLineWrapMode(QPlainTextEdit.NoWrap)
        listing.setPlainText(text)
        listing.setMinimumSize(760, 380)
        save = PillButton("Save list")
        copy_now = PillButton("Copy these now", primary=True)
        close = PillButton("Close")
        copy_now.setVisible(bool(short) and not any(g.cancelled for g in gaps))
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(copy_now)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(24, 20, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(title)
        lay.addWidget(well_text(listing), 1)
        lay.addLayout(buttons)
        save.clicked.connect(lambda: self._save_missing_list(text, gaps, save))
        close.clicked.connect(box.reject)
        copy_now.clicked.connect(lambda: box.done(1))
        if box.exec() == 1:
            self._start(copy=True)

    def _save_missing_list(self, text: str, gaps: list, button) -> None:
        """Write the list into the project folder the cards were checked against."""
        folders = [os.path.dirname(g.destination) for g in gaps if g.destination]
        folder = folders[0] if folders else self.settings["base"]
        try:
            path = missing_mod.save(folder, text)
        except OSError as exc:
            QMessageBox.warning(self, "CardCopy", f"Could not save the list:\n{exc}")
            return
        self._log("List of files not copied: " + path)
        button.setText("Saved")
        button.setEnabled(False)

    def _cancel(self) -> None:
        self.cancel.set()
        self._log("Cancelling…")

    # ------------------------------------------------------------- shutdown

    def _on_shutdown_changed(self) -> None:
        mode = self.shutdown_mode.currentData()
        self.shutdown_minutes.setVisible(mode == "time")
        self.shutdown_at.setVisible(mode == "at")
        self.shutdown_clock = None
        self.shutdown_deadline = None
        self.drive_watcher = None
        self.drive_online = True
        if self.shutdown_check.isChecked():
            if mode == "time":
                self.shutdown_deadline = time.monotonic() + self.shutdown_minutes.value() * 60
            elif mode == "at":
                # wall-clock time, so it still holds if the PC sleeps in between
                at = self.shutdown_at.time()
                self.shutdown_clock = power.next_occurrence(at.hour(), at.minute())
            elif mode == "drive" and not self.copying:
                self.drive_watcher = power.DriveWatcher()      # nothing to copy first: start listening now
            self._log("Shutdown armed: " + self.shutdown_mode.currentText() + ".")
        self._save_settings()
        self._power_tick()

    def _after_copy_for_shutdown(self) -> None:
        if not self.shutdown_check.isChecked():
            return
        mode = self.shutdown_mode.currentData()
        if mode in ("copy", "drive") and self.run_failed:
            self.shutdown_check.setChecked(False)
            self._log("NOT shutting down: the copy had errors or was cancelled. Check the log above.")
        elif mode == "copy":
            self._begin_shutdown("Copying has finished.")
        elif mode == "drive":
            self.drive_watcher, self.drive_online = power.DriveWatcher(), True
        self._power_tick()

    def _update_awake(self) -> None:
        """No sleeping while cards are copying, or while a shutdown is waiting for its moment
        (a sleeping PC neither uploads to Google Drive nor reaches a timer)."""
        wanted = self.copying or self.shutdown_check.isChecked()
        if wanted != self.awake:
            self.awake = wanted
            self.keep_awake(wanted)
            self._log("Keeping the PC awake until this is done (the screen may still turn off)." if wanted
                      else "The PC may sleep again.")

    def _power_tick(self) -> None:
        self._update_awake()
        if not self.shutdown_check.isChecked():
            self.shutdown_status.setText("")
            return
        mode = self.shutdown_mode.currentData()
        if mode == "time" and self.shutdown_deadline is not None:
            left = self.shutdown_deadline - time.monotonic()
            if left > 0:
                self.shutdown_status.setText(f"in {int(left // 60)} min {int(left % 60):02d} s")
            elif self.copying:
                self.shutdown_status.setText("time is up: waiting for the copy to finish first")
            else:
                self._begin_shutdown("The set time is up.")
        elif mode == "at" and self.shutdown_clock is not None:
            left = (self.shutdown_clock - dt.datetime.now()).total_seconds()
            when = self.shutdown_clock.strftime("%I:%M %p").lstrip("0")
            if self.shutdown_clock.date() != dt.date.today():
                when += " tomorrow"
            if left > 0:
                self.shutdown_status.setText(f"at {when}  (in {int(left // 3600)} h {int(left % 3600 // 60):02d} min)")
            elif self.copying:
                self.shutdown_status.setText(f"{when} has passed: waiting for the copy to finish first")
            else:
                self._begin_shutdown(f"It is {when}.")
        elif mode == "drive" and self.drive_watcher is not None:
            w = self.drive_watcher
            w.poll()
            if w.online != self.drive_online:
                self.drive_online = w.online
                self._log("The internet connection has dropped. Google Drive cannot upload without it, so the "
                          "shutdown waits: quiet Drive traffic right now would not mean your footage is safe."
                          if not w.online else "The connection is back: waiting for Google Drive again.")
            if w.quiet():
                self._begin_shutdown("Google Drive has been quiet for a few minutes, so it looks fully synced.")
            elif not w.running:
                self.shutdown_status.setText("Google Drive is not running: shutting down shortly")
            elif not w.online:
                self.shutdown_status.setText("no internet: waiting for the connection to come back")
            elif w.quiet_since is None:
                self.shutdown_status.setText(f"Google Drive is syncing ({human(w.rate)}/s)")
            else:
                self.shutdown_status.setText(f"Google Drive quiet for {int(w.quiet_for())} of {int(w.quiet_seconds)} s")
        elif mode in ("copy", "drive"):
            self.shutdown_status.setText("after this copy" if self.copying else "after the next copy")

    def _begin_shutdown(self, reason: str) -> None:
        """Last chance: 60 seconds on screen with a Cancel button, then an ordinary (not forced) shutdown."""
        self.shutdown_check.setChecked(False)          # disarm first: this can only ever fire once
        self._log(f"{reason} Shutting down in 60 seconds unless cancelled.")
        dialog = QDialog(self)
        dialog.setWindowTitle("CardCopy")
        dialog.setModal(True)
        text = QLabel()
        text.setStyleSheet("font-size: 12pt;")
        cancel = PillButton("Cancel shutdown", primary=True)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(28, 22, 28, 18)
        lay.addWidget(text)
        lay.addWidget(cancel, 0, Qt.AlignRight)
        left = [60]

        def tick() -> None:
            left[0] -= 1
            if left[0] <= 0:
                timer.stop()
                dialog.accept()
            else:
                text.setText(f"{reason}\nThe PC shuts down in {left[0]} seconds.")

        timer = QTimer(dialog)
        timer.timeout.connect(tick)
        cancel.clicked.connect(dialog.reject)
        text.setText(f"{reason}\nThe PC shuts down in 60 seconds.")
        timer.start(1000)
        QApplication.alert(self)
        if dialog.exec() == QDialog.Accepted:
            self._save_settings()
            if self.eject_check.isChecked() and self._real_cards():
                self._eject_all(then=self._shut_down_now)
            else:
                self._shut_down_now()
        else:
            timer.stop()
            self._log("Shutdown cancelled.")

    def _shut_down_now(self) -> None:
        self._log("Shutting down now.")
        self.shut_down_pc()

    # -------------------------------------------------------------- updates

    def _check_for_update(self) -> None:
        """On launch, in the background; silent unless there really is a newer version."""
        if not self.update_check.isChecked():
            return

        def work() -> None:
            found = updates.check(__version__)
            if found is not None and found.version != self.settings.get("skipped_version"):
                self.signals.update_found.emit(found)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_found(self, update) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("CardCopy")
        dialog.setModal(True)
        title = QLabel(f"CardCopy {update.version} is available")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        body = QLabel(f"You have {__version__}." + (f"\n\nWhat's new:\n{update.notes}" if update.notes else ""))
        body.setWordWrap(True)
        body.setMinimumWidth(420)
        in_place = update.can_self_install() and selfupdate.is_installed()
        download = PillButton("Update now" if in_place else "Download", primary=True)
        if in_place:
            download.setToolTip("Downloads the update, checks it, then closes CardCopy, installs it and opens it again")
        later = PillButton("Later")
        skip = PillButton("Skip this version")
        buttons = QHBoxLayout()
        buttons.addWidget(skip)
        buttons.addStretch(1)
        buttons.addWidget(later)
        buttons.addWidget(download)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(28, 22, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(title)
        lay.addWidget(body)
        lay.addLayout(buttons)
        download.clicked.connect(lambda: dialog.done(1))
        later.clicked.connect(lambda: dialog.done(0))
        skip.clicked.connect(lambda: dialog.done(2))
        choice = dialog.exec()
        if choice == 1 and in_place:
            self._install_update(update)
        elif choice == 1:
            # the browser downloads it; running the Setup over this install upgrades it and keeps the settings
            QDesktopServices.openUrl(QUrl(update.url))
            self._log(f"Opened the download for CardCopy {update.version}. Close CardCopy before running the Setup.")
        elif choice == 2:
            self.settings["skipped_version"] = update.version
            self._save_settings()

    def _install_update(self, update) -> None:
        """Download the update, check it, then hand over to the installer and quit.

        Never while cards are being copied: the point of the shutdown and eject switches is that a
        night's offload finishes unattended, and restarting the app underneath that would ruin it.
        """
        if self.copying:
            QMessageBox.information(self, "CardCopy", "CardCopy is busy with the cards right now.\n\n"
                                                      "The update will still be offered next time you open it.")
            return
        box = QDialog(self)
        box.setWindowTitle("CardCopy")
        box.setModal(True)
        label = QLabel(f"Downloading CardCopy {update.version}…")
        bar = ProgressBar()
        bar.setRange(0, 1000)
        bar.setMinimumWidth(420)
        stop = PillButton("Cancel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(28, 22, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(label)
        lay.addWidget(bar)
        lay.addWidget(stop, 0, Qt.AlignRight)
        cancel = threading.Event()
        stop.clicked.connect(cancel.set)
        stop.clicked.connect(box.reject)
        outcome: dict = {}

        def work() -> None:
            try:
                folder = os.path.join(selfupdate.staging_dir(), "download")
                zip_path = updates.download(
                    update, folder, cancel=cancel,
                    on_progress=lambda done, total: self.signals.update_progress.emit(done, total))
                outcome["runner"] = selfupdate.apply(zip_path)
            except Exception as exc:
                outcome["error"] = exc
            self.signals.update_ready.emit(outcome)

        self._update_box = (box, label, bar)
        threading.Thread(target=work, daemon=True).start()
        try:
            result = box.exec()
        finally:
            self._update_box = None
        if result == 1:
            self._log(f"CardCopy {update.version} is ready. Closing now; it will open again in a moment.")
            QTimer.singleShot(150, QApplication.quit)     # let the log line paint before we go
        elif result == 2:
            reason = outcome.get("error")
            self._log(f"Could not install CardCopy {update.version} by itself: {reason}. "
                      "Opening the download page instead; nothing on this PC was changed.")
            QMessageBox.warning(self, "CardCopy",
                                f"CardCopy could not update itself:\n{reason}\n\n"
                                "Nothing was changed. The download page will open so you can install it by hand.")
            QDesktopServices.openUrl(QUrl(update.url))
        else:
            self._log("Update cancelled. Nothing was changed.")

    def _on_update_ready(self, outcome: dict) -> None:
        """The download thread has finished, one way or the other: close the progress dialog.

        A real slot connected once, not a lambda connected per attempt: Qt cannot tell two lambdas
        apart, so connecting one with UniqueConnection quietly does nothing and the dialog would
        then sit there for ever while the app waited on it.
        """
        if self._update_box:
            self._update_box[0].done(1 if "runner" in outcome else 2)

    def _on_update_progress(self, done: int, total: int) -> None:
        if not self._update_box:
            return
        _, label, bar = self._update_box
        if total:
            bar.setValue(int(1000 * done / total))
            bar.setFormat(f"{human(done)} of {human(total)}")
        else:
            bar.setFormat(human(done))
        if done >= total > 0:
            label.setText("Checking the download…")

    # ---------------------------------------------------------------- eject

    def _real_cards(self) -> list[Card]:
        return [c for c in self.cards if c.volume.letter]          # folders added by hand are not devices

    def _eject_all(self, then=None) -> None:
        """Eject every connected card in the background; `then` runs afterwards on the GUI thread."""
        roots = [c.volume.root for c in self._real_cards()]
        if self.copying:
            return
        if not roots:
            self._log("No cards to eject.")
            if then is not None:
                then()
            return
        self._after_eject = then
        self.eject_btn.setEnabled(False)
        self._log("Ejecting " + ", ".join(r[:2] for r in roots) + "…")

        def work() -> None:
            self.signals.ejected.emit([(root, *self.eject_volume(root)) for root in roots])

        threading.Thread(target=work, daemon=True).start()

    def _on_ejected(self, results: list) -> None:
        for root, ok, message in results:
            self._log(f"{root[:2]}  {message}" if ok else f"{root[:2]}  NOT ejected: {message}")
        self.eject_btn.setEnabled(not self.copying)
        self.refresh()
        then, self._after_eject = self._after_eject, None
        if then is not None:
            then()

    def _set_busy(self, busy: bool) -> None:
        for w in (self.copy_btn, self.folders_btn, self.missing_btn, self.refresh_btn, self.add_folder_btn, self.eject_btn, self.mode_cameras_btn, self.mode_cards_btn,
                  self.project_edit, self.base_edit, self.base_btn, *self.cam_spins.values(), self.jpeg_check, self.xml_check, self.receipt_check, self.eject_check, self.all_check, self.photo_check,
                  self.video_check, self.audio_check, self.verify_check, self.spill_check, self.spill_edit, self.spill_btn):
            w.setEnabled(not busy)
        for panel in self.panels:
            panel.set_locked(busy)
        self.cancel_btn.setEnabled(busy)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            code = hit_test_border(self, message)
            if code is not None:
                return True, code
        return super().nativeEvent(event_type, message)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._blur_tried:                 # needs the native window, so not before the first show
            self._blur_tried = True
            self.workspace.see_through = enable_blur_behind(self)
            self.workspace.update()

    def closeEvent(self, event) -> None:
        if self.copying:
            if QMessageBox.question(self, "CardCopy", "A copy is running. Stop it and quit?") != QMessageBox.Yes:
                event.ignore()
                return
            self.cancel.set()
        self._save_settings()
        if self.awake:
            self.keep_awake(False)
        event.accept()


def main() -> int:
    if os.name == "nt":
        # our own taskbar identity: without it Windows groups the window under python's icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FramedHorizon.CardCopy")
    app = QApplication([])
    app.setWindowIcon(QIcon(f"{ASSETS}/cardcopy.ico"))
    app.setApplicationName("CardCopy")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()
