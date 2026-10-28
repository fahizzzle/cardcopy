"""One panel per connected device (camera or recorder): what it is, its name, and its cards.

Compact on purpose: a coloured badge says Photo, Video or Audio (and is the control that changes it),
and each card is two lines -- what will be copied, and what is on it.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from . import theme
from .cameras import Camera, Card
from .glass import _icon
from .identify import CopyOptions
from .progress import human          # still importable from here: ui.py and the tests use it
from .theme import STYLE, Check, Panel, ink
from .structure import cam_folder

KIND_ICONS = {"photo": "camera", "video": "film", "audio": "audio"}
# (on a light background, on a dark one): blue for stills, coral for footage, purple for sound
KIND_COLORS = {"photo": ("#2F6FEB", "#7DB2FF"), "video": ("#E2462A", "#FF8466"), "audio": ("#8A3FD6", "#C79BFF")}


def _dark() -> bool:
    if theme.NAME == "glass":                # the Windows look is always dark
        return True
    from .aqua import is_dark
    return is_dark()


class KindBadge(QComboBox):
    """What a device is -- Photo, Video or Audio -- as a coloured pill. It is also the menu that sends the
    device's files to another Raw folder, so it keeps the drop-down's calls (currentIndexChanged ...)."""

    def __init__(self, kinds: list[str], labels: list[str], kind: str) -> None:
        super().__init__()
        self.kinds = kinds
        self.addItems(labels)
        self.setCurrentIndex(kinds.index(kind) if kind in kinds else 0)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Photo, video or audio device: everything from it goes into this Raw folder. Click to change.")

    def kind(self) -> str:
        i = self.currentIndex()
        return self.kinds[i] if 0 <= i < len(self.kinds) else "photo"

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.DemiBold)
        return font

    def sizeHint(self) -> QSize:
        from PySide6.QtGui import QFontMetrics
        text = QFontMetrics(self._font()).horizontalAdvance(self.kind().capitalize())
        return QSize(9 + 14 + 6 + text + 8 + 8 + 9, 24)

    minimumSizeHint = sizeHint

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        kind = self.kind()
        color = QColor(KIND_COLORS.get(kind, KIND_COLORS["photo"])[1 if _dark() else 0])
        if not self.isEnabled():
            p.setOpacity(0.5)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(color)
        fill.setAlpha(48 if _dark() else 30)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        pen = QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        _icon(p, KIND_ICONS.get(kind, "camera"), QRectF(9, (self.height() - 14) / 2, 14, 14))
        p.setFont(self._font())
        p.drawText(QRectF(29, 0, self.width() - 29, self.height()), Qt.AlignVCenter | Qt.AlignLeft, kind.capitalize())
        cx, cy = self.width() - 13.5, self.height() / 2 + 1       # a small chevron: it opens a menu
        p.drawLine(QPointF(cx - 3, cy - 1.5), QPointF(cx, cy + 1.5))
        p.drawLine(QPointF(cx, cy + 1.5), QPointF(cx + 3, cy - 1.5))
        p.end()


class CardOption(Panel):
    """One SD card: a tick box, what will be copied, what is on it, and its copy status.

    An audio device's card also has "Choose recordings…": which of its recordings are copied (pick_dialog).
    """
    toggled = Signal(str, bool)
    cam_chosen = Signal(str, int)
    choose_requested = Signal(str)

    def __init__(self, card: Card, checked: bool, cam_number: int = 0, cam_count: int = 0,
                 options: CopyOptions | None = None, kind_off: str = "",
                 cam_names: list[str] | None = None, choose: bool = False) -> None:
        super().__init__(radius=16)
        self.key = card.key
        self.setCursor(Qt.PointingHandCursor)
        self.check = Check()
        self.check.setStyleSheet(STYLE["bold"])
        self.check.setChecked(checked)
        self.count = QLabel()                     # "1,284 files · 58.2 GB"
        self.count.setStyleSheet(STYLE["count"])
        self.count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.contents = QLabel()
        self.contents.setWordWrap(True)
        self.contents.setTextFormat(Qt.RichText)
        self.contents.setStyleSheet(STYLE["detail"])
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(STYLE["status"])
        self.status.setVisible(False)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.check)
        top.addStretch(1)
        top.addWidget(self.count)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(1)
        lay.addLayout(top)
        lay.addWidget(self.contents)
        self.combo = None
        if cam_count:                             # SD cards view: each card picks its own Cam folder
            self.combo = QComboBox()
            self.combo.addItems(cam_names or [cam_folder(n) for n in range(1, cam_count + 1)])
            self.combo.setCurrentIndex(min(max(cam_number, 1), cam_count) - 1)
            self.combo.currentIndexChanged.connect(lambda i: self.cam_chosen.emit(self.key, i + 1))
            into = QHBoxLayout()
            into.setContentsMargins(0, 4, 0, 0)
            into.addWidget(QLabel("Copy into"))
            into.addWidget(self.combo, 1)
            lay.addLayout(into)
        self.choose_btn = None
        if choose:                                # a recorder's card: pick the recordings to copy
            self.choose_btn = _link("Choose recordings…")
            self.choose_btn.setToolTip("Pick which recordings are copied; the others stay on the card")
            self.choose_btn.clicked.connect(lambda: self.choose_requested.emit(self.key))
            row = QHBoxLayout()
            row.setContentsMargins(0, 3, 0, 0)
            row.addWidget(self.choose_btn)
            row.addStretch(1)
            lay.addLayout(row)
        self._pick = ""
        lay.addWidget(self.status)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
            self.count.setStyleSheet(STYLE["count_off" if kind_off else "count"])
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
            self.count.setText(f"Not copying: {self.kind_off} is off")
        elif self._pick:
            self.count.setText(self._pick)        # some of the recordings, chosen by hand
        else:
            self.count.setText(f"{media:,} file{'' if media == 1 else 's'}  ·  {human(size)}" if media
                               else "Nothing to copy")
        copied, left = [], []
        for count, nbytes, label, wanted in ((info.raws, info.raw_size, "RAW", True),
                                             (info.jpegs, info.jpeg_size, "JPG/HEIF", options.jpeg),
                                             (info.videos, info.video_size, "video" if info.videos == 1 else "videos", True),
                                             (info.audios, info.audio_size,
                                              "recording" if info.audios == 1 else "recordings", True),
                                             (info.xmls, info.xml_size, "clip XML", options.xml)):
            if count and wanted:
                copied.append(f"{count:,} {label} ({human(nbytes)})")
            elif count:
                left.append(f"{count:,} {label}")
        lines = [f"<span style='color:{ink()}'>{'  ·  '.join(copied)}</span>"] if copied else []
        more = []
        if left:
            more.append("not copied: " + ", ".join(left))
        if not (copied or left):
            more.append("no photos, videos or recordings on this card")
        if info.newest:
            more.append(f"last shot {dt.datetime.fromtimestamp(info.newest):%d %b %H:%M}")
        if more:
            lines.append("  ·  ".join(more))
        self.contents.setText("<br>".join(lines))

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_pick(self, text: str) -> None:
        """'12 of 40 recordings · 1.2 GB' while only some are chosen; '' for all of them."""
        self._pick = text
        if text and not self.kind_off:
            self.count.setText(text)
        if self.choose_btn is not None:
            self.choose_btn.setText("Change recordings…" if text else "Choose recordings…")

    def _apply_enabled(self) -> None:
        self.check.setEnabled(not self._locked and not self.kind_off)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._apply_enabled()
        if self.combo is not None:
            self.combo.setEnabled(not locked)
        if self.choose_btn is not None:
            self.choose_btn.setEnabled(not locked)


def _link(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setFlat(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(STYLE["link"])
    return button


class CameraPanel(Panel):
    card_toggled = Signal(str, bool)
    cam_chosen = Signal(str, int)
    kind_chosen = Signal(str, str)
    card_cam_chosen = Signal(str, int)
    rename_requested = Signal(str)
    choose_requested = Signal(str)          # a card key: pick which of its recordings are copied

    def __init__(self, cam: Camera, cam_number: int, cam_count: int, checked: set[str],
                 kind: str = "photo", kind_labels: dict[str, str] | None = None,
                 card_cams: dict[str, int] | None = None, options: CopyOptions | None = None,
                 kind_off: str = "", cam_names: list[str] | None = None) -> None:
        super().__init__(radius=22)
        self.identity = cam.identity
        self.options: dict[str, CardOption] = {}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        labels = kind_labels or {"photo": "Raw Photo", "video": "Raw Video", "audio": "Raw Audio"}
        self.kinds = list(labels)
        self.kind_combo = KindBadge(self.kinds, [labels[k] for k in self.kinds], kind)
        name = QLabel(cam.name)
        name.setStyleSheet(STYLE["camera_name"])
        detail = cam.default_name if cam.name != cam.default_name else cam.model
        sub = QLabel(detail if detail != cam.name else "")
        sub.setStyleSheet(STYLE["soft"])
        name.setToolTip(detail or cam.model)
        self.rename_btn = _link("Rename")
        self.combo = QComboBox()
        self.combo.addItems(cam_names or [cam_folder(n) for n in range(1, cam_count + 1)])   # Cam 1 … or Audio
        self.combo.setCurrentIndex(cam_number - 1)
        self.combo.setToolTip("The folder this device's files go into")
        self.combo.setVisible(card_cams is None)   # SD cards view chooses per card instead
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(self.kind_combo)
        head.addWidget(name)
        head.addWidget(sub)
        head.addWidget(self.rename_btn)
        head.addStretch(1)
        head.addWidget(self.combo)

        row = QHBoxLayout()
        row.setSpacing(8)
        for card in cam.cards:
            recorder = kind == "audio"                # its recordings can be chosen one by one
            if card_cams is None:
                option = CardOption(card, card.key in checked, options=options, kind_off=kind_off, choose=recorder)
            else:
                option = CardOption(card, card.key in checked, card_cams.get(card.key, cam_number), cam_count,
                                    options, kind_off=kind_off, cam_names=cam_names, choose=recorder)
                option.cam_chosen.connect(self.card_cam_chosen)
            option.toggled.connect(self.card_toggled)
            option.choose_requested.connect(self.choose_requested)
            self.options[card.key] = option
            row.addWidget(option, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        lay.addLayout(head)
        lay.addLayout(row)

        self.combo.currentIndexChanged.connect(lambda i: self.cam_chosen.emit(self.identity, i + 1))
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.rename_btn.clicked.connect(lambda: self.rename_requested.emit(self.identity))

    def _on_kind_changed(self, index: int) -> None:
        self.kind_combo.updateGeometry()          # "Audio" and "Photo" are not the same width
        self.kind_chosen.emit(self.identity, self.kinds[index])

    def set_locked(self, locked: bool) -> None:
        for w in (self.combo, self.kind_combo, self.rename_btn):
            w.setEnabled(not locked)
        for option in self.options.values():
            option.set_locked(locked)
