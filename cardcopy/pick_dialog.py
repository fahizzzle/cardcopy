"""Choose which recordings come off an audio card (a field recorder's, a wireless mic's).

Every recording is listed with when it was made, how long it runs and its size; the ticked ones are
copied, the rest stay on the card. Double-click plays one in the computer's own player, straight from
the card -- nothing on the card is changed, and nothing is copied until the copy itself runs.
"""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from .copier import FileEntry
from .identify import wav_seconds
from .progress import human
from .theme import STYLE, PillButton

_SORT = Qt.UserRole + 1


def length(seconds: float | None) -> str:
    """'3:42', '1:02:15', or '' when it is not known."""
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


class _Row(QTreeWidgetItem):
    """Sorts each column by what it means (time, seconds, bytes), not by its text."""

    def __lt__(self, other) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        return (self.data(column, _SORT), self.text(0)) < (other.data(column, _SORT), other.text(0))


class RecordingsDialog(QDialog):
    def __init__(self, parent, title: str, root: str, files: list[FileEntry], chosen: set[str] | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose recordings")
        self.setModal(True)
        self.root = root
        self.sizes = {f.rel: f.size for f in files}
        heading = QLabel(title)
        heading.setStyleSheet(STYLE["dialog_title"])
        hint = QLabel("Tick the recordings to copy; the rest stay on the card. Double-click one to listen to it.")
        hint.setStyleSheet(STYLE["soft"])
        hint.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Recording", "Recorded", "Length", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        for f in files:
            seconds = wav_seconds(os.path.join(root, f.rel)) if f.rel.lower().endswith((".wav", ".bwf")) else None
            when = dt.datetime.fromtimestamp(f.mtime)
            row = _Row([os.path.basename(f.rel), f"{when:%d %b %Y  %H:%M:%S}", length(seconds), human(f.size)])
            for column, key in enumerate((os.path.basename(f.rel).lower(), f.mtime, seconds or 0.0, f.size)):
                row.setData(column, _SORT, key)
            row.setData(0, Qt.UserRole, f.rel)
            row.setToolTip(0, f.rel)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked if chosen is None or f.rel in chosen else Qt.Unchecked)
            for column in (2, 3):
                row.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
            self.tree.addTopLevelItem(row)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.AscendingOrder)                 # in the order they were recorded
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.tree.setMinimumSize(640, 340)

        every, nothing, play = PillButton("All", small=True), PillButton("None", small=True), PillButton("Play", small=True)
        self.summary = QLabel("")
        self.summary.setStyleSheet(STYLE["soft"])
        cancel, use = PillButton("Cancel"), PillButton("Copy These", primary=True)
        tools = QHBoxLayout()
        for button in (every, nothing, play):
            tools.addWidget(button)
        tools.addSpacing(10)
        tools.addWidget(self.summary, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(use)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(heading)
        lay.addWidget(hint)
        lay.addWidget(self.tree, 1)
        lay.addLayout(tools)
        lay.addLayout(buttons)

        every.clicked.connect(lambda: self._tick_all(True))
        nothing.clicked.connect(lambda: self._tick_all(False))
        play.clicked.connect(self._play_selected)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._play(item))
        self.tree.itemChanged.connect(lambda *_: self._summarise())
        cancel.clicked.connect(self.reject)
        use.clicked.connect(self.accept)
        self.use_button = use
        self._summarise()

    def _rows(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _tick_all(self, on: bool) -> None:
        for row in self._rows():
            row.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _play(self, row: QTreeWidgetItem) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.root, row.data(0, Qt.UserRole))))

    def _play_selected(self) -> None:
        rows = self.tree.selectedItems() or ([self.tree.currentItem()] if self.tree.currentItem() else [])
        if rows:
            self._play(rows[0])

    def chosen(self) -> set[str]:
        return {row.data(0, Qt.UserRole) for row in self._rows() if row.checkState(0) == Qt.Checked}

    def _summarise(self) -> None:
        picked = self.chosen()
        total = len(self._rows())
        size = sum(self.sizes[rel] for rel in picked)
        self.summary.setText(f"{len(picked):,} of {total:,} recordings  ·  {human(size)}")
        self.use_button.setEnabled(bool(picked))


def choose(parent, title: str, root: str, files: list[FileEntry], chosen: set[str] | None) -> set[str] | None | bool:
    """Ask. Returns the chosen recordings, None for "all of them" (so recordings made later count too),
    or False when the dialog was cancelled."""
    dialog = RecordingsDialog(parent, title, root, files, chosen)
    if dialog.exec() != QDialog.Accepted:
        return False
    picked = dialog.chosen()
    return None if len(picked) == len(files) else picked
