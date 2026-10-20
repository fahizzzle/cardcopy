"""One panel per connected device (camera or recorder): its picture, its name, and its cards."""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout)

from .cameras import Camera, Card
from .identify import CopyOptions
from .progress import human          # still importable from here: ui.py and the tests use it
from .glass import ACCENT, GREEN, TEXT, TEXT_SOFT, Panel, Toggle
from .structure import cam_folder

PICTURE_W, PICTURE_H = 132, 96


def camera_icon(kind: str, label: str) -> QPixmap:
    """The picture for a device: a stills camera for photo bodies, a cinema camera for video bodies,
    a field recorder for audio. Drawn here, so it works for every make and model and there is
    nothing to license."""
    pix = QPixmap(PICTURE_W, PICTURE_H)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    body, dark, glass, shine = QColor("#2B2F36"), QColor("#14161A"), QColor("#3D5A80"), QColor("#A9CBE0")
    p.setPen(Qt.NoPen)
    if kind == "audio":
        for side in (-1, 1):                                             # two mic capsules in an X
            p.save()
            p.translate(66 + side * 17, 22)
            p.rotate(side * 26)
            p.setBrush(dark)
            p.drawRoundedRect(QRectF(-5, -14, 10, 30), 5, 5)
            p.setBrush(glass)
            p.drawEllipse(QRectF(-4, -13, 8, 10))
            p.restore()
        p.setBrush(body)
        p.drawRoundedRect(QRectF(45, 30, 42, 48), 7, 7)                  # recorder body, standing up
        p.setBrush(dark)
        p.drawRoundedRect(QRectF(51, 36, 30, 17), 3, 3)                  # screen
        p.setBrush(glass)
        for i in range(4):                                               # level meter climbing the screen
            p.drawRect(QRectF(54 + i * 7, 48 - i * 2.5, 4, 3 + i * 2.5))
        p.setBrush(QColor("#4A505B"))
        p.drawEllipse(QRectF(57, 57, 18, 18))                            # transport wheel
        p.setBrush(QColor("#FF5B3A"))
        p.drawEllipse(QRectF(63, 63, 6, 6))                              # record button
    elif kind == "video":
        p.setBrush(body)
        p.drawRoundedRect(QRectF(40, 30, 62, 44), 8, 8)                  # body
        p.drawRoundedRect(QRectF(50, 11, 44, 8), 4, 4)                   # top handle
        p.drawRect(QRectF(54, 17, 6, 14))
        p.drawRect(QRectF(84, 17, 6, 14))
        p.drawRoundedRect(QRectF(100, 36, 20, 17), 4, 4)                 # monitor / viewfinder at the back
        p.setBrush(dark)
        p.drawRoundedRect(QRectF(16, 36, 28, 32), 5, 5)                  # lens barrel, pointing left
        p.drawRoundedRect(QRectF(9, 32, 10, 40), 4, 4)                   # lens hood
        p.setBrush(glass)
        p.drawEllipse(QRectF(10, 40, 8, 24))                             # front element, seen from the side
        p.setBrush(QColor("#FF5B3A"))
        p.drawEllipse(QRectF(87, 36, 8, 8))                              # record light
        p.setBrush(QColor("#4A505B"))
        p.drawRoundedRect(QRectF(48, 52, 30, 14), 3, 3)                  # side panel
    else:
        p.setBrush(body)
        p.drawRoundedRect(QRectF(14, 24, 104, 54), 9, 9)                 # body
        p.drawRoundedRect(QRectF(48, 12, 36, 16), 4, 4)                  # viewfinder hump
        p.drawRoundedRect(QRectF(96, 17, 16, 9), 3, 3)                   # shutter button / dial
        p.setBrush(QColor("#22252B"))
        p.drawRoundedRect(QRectF(14, 24, 24, 54), 9, 9)                  # grip
        p.setBrush(dark)
        p.drawEllipse(QRectF(42, 27, 48, 48))                            # lens barrel
        p.setBrush(glass)
        p.drawEllipse(QRectF(52, 37, 28, 28))                            # glass
        p.setBrush(shine)
        p.drawEllipse(QRectF(58, 42, 8, 8))                              # highlight
    p.setPen(QColor("#555B66"))
    font = QFont()
    font.setPointSize(8)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 80, PICTURE_W, 16), Qt.AlignCenter, label[:22])
    p.end()
    return pix


def load_picture(path: str, label: str, kind: str = "photo") -> QPixmap:
    """The user's own picture of this body when they set one, otherwise the drawn icon for its kind."""
    pix = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
    if pix.isNull():
        return camera_icon(kind, label)
    pix = pix.scaled(PICTURE_W, PICTURE_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    rounded = QPixmap(pix.size())
    rounded.fill(Qt.transparent)
    p = QPainter(rounded)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, pix.width(), pix.height()), 8, 8)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, pix)
    p.end()
    return rounded


class CardOption(Panel):
    """One SD card: a tick box, what is on it, and its copy status."""
    toggled = Signal(str, bool)
    cam_chosen = Signal(str, int)

    def __init__(self, card: Card, checked: bool, cam_number: int = 0, cam_count: int = 0,
                 options: CopyOptions | None = None, kind_off: str = "") -> None:
        super().__init__(radius=16)
        self.key = card.key
        self.setCursor(Qt.PointingHandCursor)
        self.check = Toggle()
        self.check.setStyleSheet("font-weight: 600;")
        self.check.setChecked(checked)
        self.count = QLabel()                     # "1,284 files · 58.2 GB"
        self.count.setStyleSheet(f"color: {TEXT}; font-size: 11pt; font-weight: 600;")
        self.count.setWordWrap(True)             # two cards side by side leave little width
        self.contents = QLabel()
        self.contents.setWordWrap(True)
        self.contents.setTextFormat(Qt.RichText)
        self.contents.setStyleSheet(f"color: {TEXT_SOFT};")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {GREEN}; font-weight: 600;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(1)
        lay.addWidget(self.check)
        lay.addWidget(self.count)
        lay.addWidget(self.contents)
        self.combo = None
        if cam_count:                             # SD cards view: each card picks its own Cam folder
            self.combo = QComboBox()
            self.combo.addItems([cam_folder(n) for n in range(1, cam_count + 1)])
            self.combo.setCurrentIndex(min(max(cam_number, 1), cam_count) - 1)
            self.combo.currentIndexChanged.connect(lambda i: self.cam_chosen.emit(self.key, i + 1))
            into = QHBoxLayout()
            into.setContentsMargins(0, 4, 0, 0)
            into.addWidget(QLabel("Copy into"))
            into.addWidget(self.combo, 1)
            lay.addLayout(into)
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.setMinimumWidth(186)
        self.setMaximumWidth(340)
        self.setMinimumHeight(PICTURE_H + 20)
        self.kind_off = kind_off
        self._locked = False
        self.check.toggled.connect(self._on_toggled)
        self.update_card(card, options, kind_off)
        self._restyle()

    def _on_toggled(self, on: bool) -> None:
        self._restyle()
        self.toggled.emit(self.key, on)

    def _restyle(self) -> None:
        # the ring means "this is being copied", so a card whose kind is switched off does not get one
        self.set_selected(self.check.isChecked() and not self.kind_off)

    def mousePressEvent(self, event) -> None:
        if self.check.isEnabled():               # the whole tile is the switch
            self.check.toggle()

    def update_card(self, card: Card, options: CopyOptions | None = None, kind_off: str | None = None) -> None:
        options = options or CopyOptions()
        if kind_off is not None:
            self.kind_off = kind_off
            # the tick stays, but nothing follows from it: mute the switch and the count with it,
            # so the only coral on screen belongs to cards that really are being copied
            self.check.set_muted(bool(kind_off))
            self._apply_enabled()        # nothing to tick or untick while its kind is off
            self.count.setStyleSheet(f"color: {TEXT_SOFT if kind_off else TEXT}; "
                                     "font-size: 11pt; font-weight: 600;")
            self._restyle()
        v, info = card.volume, card.info
        where = f"{v.letter}" if v.letter else "folder"
        label = f"  [{v.label}]" if v.label else ""
        self.check.setText(f"SD {card.slot}  ·  {where}")
        self.check.setToolTip(f"{v.root}{label}")
        self.setToolTip(v.root)
        if not info.scanned:
            self.count.setText("counting…")
            self.contents.setText("")
            return
        media, size = info.selected(options)
        if self.kind_off:
            # the Uploading row decides this, not the card: say so rather than promise a copy
            self.count.setText(f"Not copying\n{self.kind_off} is switched off")
        else:
            self.count.setText(f"Will copy {media:,} file{'' if media == 1 else 's'}\n{human(size)}" if media
                               else "Nothing to copy")
        copied, left = [], []
        for count, nbytes, label, wanted in ((info.raws, info.raw_size, "RAW", True),
                                             (info.jpegs, info.jpeg_size, "JPG/HEIF", options.jpeg),
                                             (info.videos, info.video_size, "video" if info.videos == 1 else "videos", True),
                                             (info.audios, info.audio_size,
                                              "recording" if info.audios == 1 else "recordings", True),
                                             (info.xmls, info.xml_size, "clip XML", options.xml)):
            if count and wanted:
                copied.append(f"{count:,} {label}  ·  {human(nbytes)}")
            elif count:
                left.append(f"{count:,} {label}")
        rows = [f"<span style='color:{TEXT}'>{row}</span>" for row in copied]
        if left:
            rows.append("Not copied: " + ", ".join(left))
        if not (copied or left):
            rows.append("no photos, videos or recordings on this card")
        if info.newest:
            rows.append(f"last shot {dt.datetime.fromtimestamp(info.newest):%d %b %H:%M}")
        self.contents.setText("<br>".join(rows))

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _apply_enabled(self) -> None:
        self.check.setEnabled(not self._locked and not self.kind_off)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._apply_enabled()
        if self.combo is not None:
            self.combo.setEnabled(not locked)


def _link(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setFlat(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; color: {TEXT_SOFT}; padding: 0;"
        f" text-decoration: underline; }} QPushButton:hover {{ color: {ACCENT.name()}; }}"
        f" QPushButton:disabled {{ color: rgba(255,255,255,0.25); }}")
    return button


class CameraPanel(Panel):
    card_toggled = Signal(str, bool)
    cam_chosen = Signal(str, int)
    kind_chosen = Signal(str, str)
    card_cam_chosen = Signal(str, int)
    rename_requested = Signal(str)
    picture_requested = Signal(str)

    def __init__(self, cam: Camera, cam_number: int, cam_count: int, picture: str, checked: set[str],
                 kind: str = "photo", kind_labels: dict[str, str] | None = None,
                 card_cams: dict[str, int] | None = None, options: CopyOptions | None = None,
                 kind_off: str = "") -> None:
        super().__init__(radius=22)
        self.identity = cam.identity
        self.options: dict[str, CardOption] = {}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.picture = QLabel()
        self.picture.setFixedSize(PICTURE_W, PICTURE_H)
        self.picture.setAlignment(Qt.AlignCenter)
        self._picture_path, self._label = picture, cam.default_name
        self.picture.setPixmap(load_picture(picture, cam.default_name, kind))
        tile = Panel(radius=16, light=True)      # dark camera bodies need a bright tile to show up
        tile_lay = QVBoxLayout(tile)
        tile_lay.setContentsMargins(8, 8, 8, 8)
        tile_lay.addWidget(self.picture)

        name = QLabel(cam.name)
        name.setStyleSheet(f"color: {TEXT}; font-size: 13pt; font-weight: 600;")
        sub = QLabel(cam.default_name if cam.name != cam.default_name else cam.model)
        sub.setStyleSheet(f"color: {TEXT_SOFT};")
        self.combo = QComboBox()
        self.combo.addItems([cam_folder(n) for n in range(1, cam_count + 1)])
        self.combo.setCurrentIndex(cam_number - 1)
        self.rename_btn = _link("Rename")
        self.picture_btn = _link("Picture")
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 2, 6)
        head.setSpacing(8)
        head.addWidget(name)
        name.setToolTip(sub.text() or cam.model)
        head.addWidget(self.rename_btn)
        head.addWidget(self.picture_btn)
        head.addStretch(1)
        self.kind_combo = QComboBox()
        self.kinds = list(kind_labels or {"photo": "Raw Photo", "video": "Raw Video", "audio": "Raw Audio"})
        self.kind_combo.addItems([(kind_labels or {}).get(k, k) for k in self.kinds])
        self.kind_combo.setCurrentIndex(self.kinds.index(kind) if kind in self.kinds else 0)
        self.kind_combo.setToolTip("Everything from this device goes into this Raw folder")
        head.addWidget(self.kind_combo)
        head.addWidget(self.combo)
        self.combo.setVisible(card_cams is None)   # SD cards view chooses per card instead

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(tile, 0, Qt.AlignTop)
        for card in cam.cards:
            if card_cams is None:
                option = CardOption(card, card.key in checked, options=options, kind_off=kind_off)
            else:
                option = CardOption(card, card.key in checked, card_cams.get(card.key, cam_number), cam_count,
                                    options, kind_off=kind_off)
                option.cam_chosen.connect(self.card_cam_chosen)
            option.toggled.connect(self.card_toggled)
            self.options[card.key] = option
            row.addWidget(option, 1)
        if len(cam.cards) == 1:
            row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addLayout(row)

        self.combo.currentIndexChanged.connect(lambda i: self.cam_chosen.emit(self.identity, i + 1))
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.rename_btn.clicked.connect(lambda: self.rename_requested.emit(self.identity))
        self.picture_btn.clicked.connect(lambda: self.picture_requested.emit(self.identity))

    def _on_kind_changed(self, index: int) -> None:
        self.picture.setPixmap(load_picture(self._picture_path, self._label, self.kinds[index]))   # the icon follows the role
        self.kind_chosen.emit(self.identity, self.kinds[index])

    def set_locked(self, locked: bool) -> None:
        for w in (self.combo, self.kind_combo, self.rename_btn, self.picture_btn):
            w.setEnabled(not locked)
        for option in self.options.values():
            option.set_locked(locked)
