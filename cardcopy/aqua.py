"""The Mac look: native window chrome, a translucent sidebar, light and dark mode, CardCopy's coral.

It follows macOS rather than restyling the Windows glass: the system font, popup menus and steppers
drawn by macOS itself, quiet rounded groups on a plain background, and the controls that carry the
brand -- switches, check boxes, buttons, the sidebar selection -- painted here in coral (Qt's own would
come out in the system blue). Offers the same names as glass.py; theme.py picks one.

Colours follow the system appearance live: install() sets a palette for light or dark and swaps it when
macOS switches, and everything here reads its colours at paint time. Label styles name palette roles
(palette(placeholder-text) ...) rather than colours, so they follow too.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .glass import ASSETS, Glide, _icon, mix  # noqa: F401  (ASSETS is part of the shared names)

NAME = "aqua"
ON_MAC = sys.platform == "darwin"
ACCENT = QColor("#F5532F")
M = 2                           # room around buttons for the focus ring


def _c(value) -> QColor:
    return value if isinstance(value, QColor) else QColor(value)


LIGHT = SimpleNamespace(
    window=_c("#F2F2F5"), panel=_c("#FFFFFF"), inner=_c("#F6F6F8"), text=_c("#1D1D1F"), soft=_c("#6E6E73"),
    faint=_c("#AEAEB2"), border=QColor(0, 0, 0, 22), field=_c("#FFFFFF"), field_border=QColor(0, 0, 0, 40),
    sidebar=_c("#E9E9ED"), separator=QColor(0, 0, 0, 26), well=_c("#FAFAFB"), green=_c("#1E8C3E"),
    button=_c("#FFFFFF"), track=QColor(0, 0, 0, 30), hover=QColor(0, 0, 0, 14), link=_c("#D8431F"),
    tint=QColor(245, 83, 47, 18), tool=QColor(255, 255, 255, 215), tile=(_c("#F7F8FA"), _c("#E2E4E9")))
DARK = SimpleNamespace(
    window=_c("#1E1E20"), panel=_c("#2A2A2D"), inner=_c("#333337"), text=_c("#F5F5F7"), soft=_c("#9A9AA0"),
    faint=_c("#5E5E64"), border=QColor(255, 255, 255, 20), field=_c("#2C2C30"), field_border=QColor(255, 255, 255, 34),
    sidebar=_c("#262629"), separator=QColor(0, 0, 0, 120), well=_c("#19191B"), green=_c("#34C759"),
    button=QColor(255, 255, 255, 34), track=QColor(255, 255, 255, 48), hover=QColor(255, 255, 255, 18),
    link=_c("#FF7A5C"), tint=QColor(245, 83, 47, 34), tool=QColor(255, 255, 255, 22),
    tile=(_c("#DADCE1"), _c("#C2C5CC")))

# Colours for stylesheets, as palette roles so they change with the appearance (see make_palette).
TEXT = "palette(window-text)"
TEXT_SOFT = "palette(placeholder-text)"
GREEN = "palette(link-visited)"          # the palette's visited-link slot carries the "done" green

STYLE = {
    "bold": "font-weight: 600;",
    "soft": f"color: {TEXT_SOFT};",
    "detail": f"color: {TEXT_SOFT}; font-size: 12px;",
    "count": f"color: {TEXT}; font-size: 13px; font-weight: 600;",
    "count_off": f"color: {TEXT_SOFT}; font-size: 13px; font-weight: 600;",
    "status": f"color: {GREEN}; font-size: 12px; font-weight: 600;",
    "camera_name": f"color: {TEXT}; font-size: 15px; font-weight: 600;",
    "link": ("QPushButton { border: none; background: transparent; color: palette(link); padding: 0 2px;"
             " font-size: 12px; } QPushButton:hover { text-decoration: underline; }"
             f" QPushButton:disabled {{ color: {TEXT_SOFT}; }}"),
    "scan": f"color: {TEXT_SOFT}; font-size: 11px;",
    "empty": f"color: {TEXT_SOFT}; padding: 30px; font-size: 13px;",
    "dialog_text": "font-size: 13px;",
    "dialog_title": "font-size: 17px; font-weight: 600;",
}


def is_dark() -> bool:
    app = QApplication.instance()
    return app is not None and app.palette().color(QPalette.Window).lightness() < 128


def colors() -> SimpleNamespace:
    return DARK if is_dark() else LIGHT


def make_palette(dark: bool) -> QPalette:
    c = DARK if dark else LIGHT
    pal = QPalette()
    roles = {QPalette.Window: c.window, QPalette.WindowText: c.text, QPalette.Base: c.field,
             QPalette.AlternateBase: c.inner, QPalette.Text: c.text, QPalette.Button: c.panel,
             QPalette.ButtonText: c.text, QPalette.PlaceholderText: c.soft, QPalette.Highlight: ACCENT,
             QPalette.HighlightedText: QColor("white"), QPalette.Accent: ACCENT, QPalette.Link: c.link,
             QPalette.LinkVisited: c.green, QPalette.ToolTipBase: c.panel, QPalette.ToolTipText: c.text,
             QPalette.BrightText: QColor("white"), QPalette.Light: c.panel, QPalette.Midlight: c.inner,
             QPalette.Mid: c.faint, QPalette.Dark: c.soft, QPalette.Shadow: QColor(0, 0, 0, 90)}
    for role, color in roles.items():
        pal.setColor(QPalette.All, role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c.faint)
    return pal


def install(app: QApplication) -> None:
    """Fonts, palette and styles for the Mac look; follows light/dark as macOS switches.

    CARDCOPY_APPEARANCE=light|dark pins one (screenshots of both, whatever the machine is set to).
    """
    if not ON_MAC:                          # the Windows preview of this look: the closest Qt has
        app.setStyle("Fusion")
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        app.setFont(font)
    apply_appearance(app)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_appearance(app))


def apply_appearance(app: QApplication) -> None:
    pinned = os.environ.get("CARDCOPY_APPEARANCE", "").lower()
    if pinned in ("light", "dark"):
        # macOS then draws its own controls (popups, steppers) in that appearance too
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if pinned == "dark" else Qt.ColorScheme.Light)
        dark = pinned == "dark"
    else:
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    app.setPalette(make_palette(dark))
    # a changed sheet repolishes every widget, which re-reads the palette(...) roles in their own styles
    app.setStyleSheet(app_stylesheet() + ("/* dark */" if dark else "/* light */"))
    for widget in app.allWidgets():
        widget.update()


def app_stylesheet() -> str:
    return """
    QScrollArea { background: transparent; border: none; }
    QScrollArea > QWidget > QWidget { background: transparent; }
    QPlainTextEdit { background: transparent; border: none; color: palette(text);
                     selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }
    """


def ink() -> str:
    """The main text colour right now, for the odd bit of rich text that has to name it."""
    return QApplication.palette().color(QPalette.WindowText).name()


def mono_font(size: int) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPixelSize(size + 2)
    return font


def _fill_font(widget: QWidget, px: int, weight=QFont.Normal) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


# ------------------------------------------------------------------ window

def setup_window(window: QWidget) -> None:
    if ON_MAC:
        window.setAttribute(Qt.WA_TranslucentBackground)       # lets the sidebar's vibrancy through
        window.setWindowFlag(Qt.ExpandedClientAreaHint, True)   # the sidebar runs up under the traffic lights
        window.setWindowFlag(Qt.NoTitleBarBackgroundHint, True)


def after_first_show(window) -> None:
    """Native touches that need the real NSWindow: the unified title bar and the sidebar's vibrancy."""
    if not ON_MAC:
        return
    from .mac import native
    native.unify_titlebar(window)
    window.sidebar.see_through = native.add_vibrancy(window, window.sidebar.width())
    window.sidebar.update()


def progress_badge(percent: int | None) -> None:
    """The copy's progress on the Dock icon ("42%"); None clears it."""
    if ON_MAC:
        from .mac import native
        native.dock_badge("" if percent is None else f"{percent}%")


def hit_test_border(widget: QWidget, message) -> int | None:
    return None                             # a Mac window keeps its own frame


class _Draggable(QWidget):
    """Empty parts of this widget move the window (they sit where a title bar would); double-click zooms."""

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.LeftButton and handle is not None:
            handle.startSystemMove()

    def mouseDoubleClickEvent(self, event) -> None:
        win = self.window()
        win.showNormal() if win.isMaximized() else win.showMaximized()


class TitleStrip(QWidget):
    """Windows-only caption; a Mac window has its own."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(0)


class Sidebar(_Draggable):
    """Translucent like Finder's once the window's vibrancy is on (see_through); a solid tint otherwise."""
    see_through = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        c = colors()
        if not self.see_through:
            p.fillRect(self.rect(), c.sidebar)
        p.setPen(QPen(c.separator, 1))
        p.drawLine(QPointF(self.width() - 0.5, 0), QPointF(self.width() - 0.5, self.height()))
        p.end()


class Backdrop(QWidget):
    """The content side of the window: one quiet, opaque colour."""
    see_through = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), colors().window)
        p.end()


class Toolbar(_Draggable):
    """The strip along the top of the content: the page's title, what is going on, and the actions.

    It sits where the title bar is (the window's content runs up under it), so its empty parts drag
    the window like a title bar would.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(52)


class ToolGroup(QFrame):
    """A capsule holding a few toolbar buttons, the way macOS groups toolbar items."""

    def __init__(self, buttons: list[QWidget]) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)
        for button in buttons:
            lay.addWidget(button)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(c.border, 1))
        p.setBrush(c.tool)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.end()


class Subtitle(QLabel):
    """A line of small print that takes no room while it has nothing to say."""

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


# ------------------------------------------------------------------ panels

class Panel(QFrame):
    """A rounded group. well=True is a recessed text box; light=True the bright tile behind a camera picture.

    One Panel inside another (a card inside its camera) is drawn a shade apart from its parent."""

    def __init__(self, radius: int = 18, well: bool = False, light: bool = False) -> None:
        super().__init__()
        self.radius = 8 if well else (12 if radius >= 18 else 10)
        self.well, self.light, self.selected = well, light, False
        self.setContentsMargins(1, 1, 1, 1)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def _nested(self) -> bool:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, Panel):
                return True
            parent = parent.parentWidget()
        return False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.light:
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0, c.tile[0])
            fill.setColorAt(1, c.tile[1])
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
        elif self.well:
            p.setPen(QPen(c.border, 1))
            p.setBrush(c.well)
        else:
            p.setPen(QPen(c.border, 1))
            p.setBrush(c.inner if self._nested() else c.panel)
        p.drawRoundedRect(rect, self.radius, self.radius)
        if self.selected:
            p.setPen(QPen(ACCENT, 1.5))
            p.setBrush(c.tint)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        p.end()


def well_text(edit: QPlainTextEdit, radius: int = 14) -> Panel:
    """Sit a text box in a recessed well."""
    edit.setFrameShape(QFrame.NoFrame)
    well = Panel(radius, well=True)
    lay = QVBoxLayout(well)
    lay.setContentsMargins(10, 6, 4, 6)
    lay.addWidget(edit)
    return well


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 600; padding: 2px 2px;")
    return label


def nav_caption(text: str) -> QLabel:
    """A sidebar section title, in title case like Finder's ("Copy From")."""
    label = QLabel(" ".join(word[:1].upper() + word[1:] for word in text.split()))
    label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px; font-weight: 700; padding: 12px 10px 3px 10px;")
    return label


# ---------------------------------------------------------------- controls

class PillButton(QPushButton):
    """A push button, capsule-shaped as on current macOS; primary=True is the filled coral one."""

    def __init__(self, text: str, primary: bool = False, small: bool = False) -> None:
        super().__init__(text)
        self.primary, self.small = primary, small
        self.setFont(_fill_font(self, 13, QFont.DemiBold if primary else QFont.Medium))

    def sizeHint(self) -> QSize:
        w = int(self.fontMetrics().horizontalAdvance(self.text()) * 1.05) + (24 if self.small else 34)
        return QSize(w + 2 * M, (24 if self.small else 28) + 2 * M)

    minimumSizeHint = sizeHint

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        rect = QRectF(self.rect()).adjusted(M + 0.5, M + 0.5, -M - 0.5, -M - 0.5)
        radius = rect.height() / 2
        if not self.isEnabled():
            p.setOpacity(0.45)
        down = self.isDown() or self.isChecked()
        if self.primary:
            p.setPen(Qt.NoPen)
            p.setBrush(ACCENT.darker(115) if down else ACCENT)
            p.drawRoundedRect(rect, radius, radius)
            color = QColor("white")
        else:
            p.setPen(QPen(c.field_border, 1))
            p.setBrush(mix(_c(c.button), c.text, 0.10) if down else _c(c.button))
            p.drawRoundedRect(rect, radius, radius)
            color = c.link if self.isChecked() else c.text
        if self.hasFocus() and self.isEnabled():
            p.setPen(QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 110), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), radius + 1.5, radius + 1.5)
        p.setPen(color)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignCenter, self.text())
        p.end()


class LineEdit(QLineEdit):
    """A rounded text field with a coral focus ring."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setFrame(False)
        self.setStyleSheet("QLineEdit { background: transparent; border: none; color: palette(text);"
                           " selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }")
        self.setTextMargins(10, 0, 10, 0)
        self.setMinimumHeight(30)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        rect = QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 95), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 8, 8)
        p.setPen(QPen(ACCENT if self.hasFocus() else c.field_border, 1))
        p.setBrush(c.field)
        p.drawRoundedRect(rect, 7, 7)
        p.end()
        super().paintEvent(event)


class Toggle(QCheckBox):
    """A switch, as in System Settings; coral when on. Same calls as the glass one, set_muted included."""
    TRACK_W, TRACK_H, GAP = 32, 18, 8

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.muted = False
        self._knob = Glide(self, value=1.0 if self.isChecked() else 0.0, ms=160)
        self.toggled.connect(lambda on: self._knob.to(1.0 if on else 0.0))

    def setChecked(self, on: bool) -> None:
        # settings are loaded with signals blocked, so toggled cannot be the only thing that moves it
        super().setChecked(on)
        self._knob.to(1.0 if on else 0.0)

    def _text_width(self) -> int:
        return int(self.fontMetrics().horizontalAdvance(self.text()) * 1.08) if self.text() else 0

    def sizeHint(self) -> QSize:
        text_w = self._text_width()
        return QSize(self.TRACK_W + 3 + (self.GAP + text_w if text_w else 0) + 2,
                     max(self.TRACK_H, self.fontMetrics().height()) + 8)

    minimumSizeHint = sizeHint

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def set_muted(self, muted: bool) -> None:
        """Ticked underneath but switched off by something else: drawn off (see glass.Toggle.set_muted)."""
        if muted != self.muted:
            self.muted = muted
            self.update()

    def _amount(self) -> float:
        if self.muted:
            return 0.0
        return self._knob.value if self.isEnabled() else (1.0 if self.isChecked() else 0.0)

    def _draw_text(self, p: QPainter, left: float) -> None:
        if self.text():
            p.setPen(colors().text)
            p.setFont(self.font())
            p.drawText(QRectF(left, 0, self.width() - left, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        if not self.isEnabled():
            p.setOpacity(0.45)
        on = self._amount()
        track = QRectF(1.5, (self.height() - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)
        p.setPen(Qt.NoPen)
        p.setBrush(mix(c.track, ACCENT, on))
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        d = self.TRACK_H - 4
        x = track.left() + 2 + (track.width() - d - 4) * on
        knob = QRectF(x, track.center().y() - d / 2, d, d)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(knob.translated(0, 0.6))
        p.setBrush(QColor("white"))
        p.drawEllipse(knob)
        self._draw_text(p, track.right() + self.GAP)
        p.end()


class Check(Toggle):
    """A check box: what macOS uses for picking several things (Photo / Video / Audio, which cards)."""
    BOX = 15
    GAP = 7

    def sizeHint(self) -> QSize:
        text_w = self._text_width()
        return QSize(self.BOX + 3 + (self.GAP + text_w if text_w else 0) + 2,
                     max(self.BOX, self.fontMetrics().height()) + 8)

    minimumSizeHint = sizeHint

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        if not self.isEnabled():
            p.setOpacity(0.45)
        on = self._amount()
        box = QRectF(1.5, (self.height() - self.BOX) / 2, self.BOX, self.BOX)
        p.setPen(QPen(mix(c.field_border, ACCENT, on), 1))
        p.setBrush(mix(_c(c.field), ACCENT, on))
        p.drawRoundedRect(box, 4, 4)
        if on > 0.01:
            pen = QPen(QColor(255, 255, 255, int(255 * on)), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            x, y, s = box.x(), box.y(), box.width()
            p.drawPolyline([QPointF(x + s * 0.26, y + s * 0.53), QPointF(x + s * 0.44, y + s * 0.71),
                            QPointF(x + s * 0.76, y + s * 0.31)])
        self._draw_text(p, box.right() + self.GAP)
        p.end()


class ProgressBar(QWidget):
    """Same calls as the QProgressBar it replaces: a thin coral bar, the numbers underneath."""

    def __init__(self) -> None:
        super().__init__()
        self._min, self._max, self._value, self._text = 0, 100, 0, ""
        self.setFixedHeight(32)

    def setRange(self, lo: int, hi: int) -> None:
        self._min, self._max = lo, max(hi, lo + 1)

    def setValue(self, value: int) -> None:
        self._value = value
        self.update()

    def setFormat(self, text: str) -> None:
        self._text = text
        self.update()

    def format(self) -> str:
        return self._text

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        track = QRectF(1, 5, self.width() - 2, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(c.track)
        p.drawRoundedRect(track, 3, 3)
        frac = min(max((self._value - self._min) / (self._max - self._min), 0), 1)
        if frac > 0:
            p.setBrush(ACCENT)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(track.width() * frac, 6), track.height()), 3, 3)
        if frac or self._text:
            p.setPen(c.soft)
            p.setFont(_fill_font(self, 11))
            p.drawText(QRectF(0, 15, self.width(), 16), Qt.AlignCenter,
                       f"{frac * 100:.0f}%" + (f"   ·   {self._text}" if self._text else ""))
        p.end()


# ------------------------------------------------------------------ sidebar

class NavButton(QPushButton):
    """A sidebar row: a coral line icon and a label. A checked one is the current page."""

    def __init__(self, text: str, icon: str, checkable: bool = False) -> None:
        super().__init__(text)
        self.icon_name = icon
        self.setCheckable(checkable)
        self.setFixedHeight(28)
        self._active = Glide(self, value=1.0 if self.isChecked() else 0.0, ms=150)
        self.toggled.connect(lambda on: self._active.to(1.0 if on else 0.0))

    def setChecked(self, on: bool) -> None:
        super().setChecked(on)
        self._active.to(1.0 if on else 0.0)

    def sizeHint(self) -> QSize:
        return QSize(180, 28)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        enabled = self.isEnabled()
        row = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        active = self._active.value if enabled else 0.0
        if active > 0.01:
            p.setPen(Qt.NoPen)
            tint = QColor(c.tint)
            tint.setAlpha(int(tint.alpha() * 1.6 * active))
            p.setBrush(tint)
            p.drawRoundedRect(row, 7, 7)
        elif self.isDown() and enabled:
            p.setPen(Qt.NoPen)
            p.setBrush(c.hover)
            p.drawRoundedRect(row, 7, 7)
        icon = QRectF(10, (self.height() - 16) / 2, 16, 16)
        p.setPen(QPen(ACCENT if enabled else c.faint, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        _icon(p, self.icon_name, icon.adjusted(1, 1, -1, -1))
        p.setPen(c.text if enabled else c.faint)
        p.setFont(_fill_font(self, 13, QFont.DemiBold if self.isChecked() else QFont.Normal))
        p.drawText(QRectF(icon.right() + 9, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   self.text())
        p.end()


class ActionButton(QPushButton):
    """A toolbar button: just its icon (the label is its tooltip and what VoiceOver reads)."""

    def __init__(self, text: str, icon: str) -> None:
        super().__init__(text)
        self.icon_name = icon
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setFixedSize(34, 28)
        self._hover = Glide(self, ms=120)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = colors()
        enabled = self.isEnabled()
        lit = max(self._hover.value, 1.0 if self.isDown() else 0.0) if enabled else 0.0
        if lit > 0.01:
            shade = QColor(c.hover)
            shade.setAlpha(int(shade.alpha() * (1.6 if self.isDown() else 1.0) * lit))
            p.setPen(Qt.NoPen)
            p.setBrush(shade)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        p.setPen(QPen(c.text if enabled else c.faint, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        _icon(p, self.icon_name, QRectF((self.width() - 16) / 2, (self.height() - 16) / 2, 16, 16))
        p.end()

    def enterEvent(self, event) -> None:
        self._hover.to(1.0 if self.isEnabled() else 0.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)


class Logo(QWidget):
    """The app's mark and name (the Settings window's header)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.setFixedHeight(44)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        chip = QRectF(2, 4, 36, 36)
        path = QPainterPath()
        path.addRoundedRect(chip, 9, 9)
        fill = QLinearGradient(chip.topLeft(), chip.bottomLeft())
        fill.setColorAt(0, QColor("#FF7A4D"))
        fill.setColorAt(1, ACCENT)
        p.fillPath(path, fill)
        p.setPen(QPen(QColor("white"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        _icon(p, "card", chip.adjusted(10, 8, -10, -8))
        p.setPen(colors().text)
        p.setFont(_fill_font(self, 17, QFont.Bold))
        p.drawText(QRectF(chip.right() + 12, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()
