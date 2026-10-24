"""The Windows look: a dark sidebar, and a glass workspace (translucent panels over a glowing dark backdrop).

Everything is painted by hand: Qt stylesheets can do neither translucent gradients
with hairline borders on arbitrary containers nor the backdrop glows. A Mac gets aqua.py instead, which
offers the same names (theme.py picks one).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

SIDEBAR = QColor("#131416")
ACCENT = QColor("#FF5B3A")
ACCENT_2 = QColor("#FFA53A")
GREEN = "#4ADE80"
TEXT = "#F2F2F4"
TEXT_SOFT = "#BEC0C9"
M = 4                           # breathing room around buttons

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
NAME = "glass"

# Label styles the window and the camera tiles share with the Mac look (aqua.STYLE has the same keys).
STYLE = {
    "bold": "font-weight: 600;",
    "soft": f"color: {TEXT_SOFT};",
    "detail": f"color: {TEXT_SOFT};",
    "count": f"color: {TEXT}; font-size: 11pt; font-weight: 600;",
    "count_off": f"color: {TEXT_SOFT}; font-size: 11pt; font-weight: 600;",
    "status": f"color: {GREEN}; font-weight: 600;",
    "camera_name": f"color: {TEXT}; font-size: 13pt; font-weight: 600;",
    "link": (f"QPushButton {{ border: none; background: transparent; color: {TEXT_SOFT}; padding: 0;"
             f" text-decoration: underline; }} QPushButton:hover {{ color: {ACCENT.name()}; }}"
             f" QPushButton:disabled {{ color: rgba(255,255,255,0.25); }}"),
    "scan": "color: rgba(255,255,255,0.45); padding: 0 6px;",
    "empty": f"color: {TEXT_SOFT}; padding: 30px;",
    "dialog_text": "font-size: 12pt;",
    "dialog_title": "font-size: 14pt; font-weight: 600;",
}


def ink() -> str:
    """The main text colour, for the odd bit of rich text that has to name it."""
    return TEXT


def mono_font(size: int) -> QFont:
    return QFont("Consolas", size)


def setup_window(window: QWidget) -> None:
    window.setAttribute(Qt.WA_TranslucentBackground)   # the workspace is glass over the desktop
    # frameless: Windows smears the native caption once blur-behind is on, so TitleStrip replaces it
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint)


def after_first_show(window) -> None:
    """Needs the native window, so not before the first show."""
    window.workspace.see_through = enable_blur_behind(window)
    window.workspace.update()


def progress_badge(percent: int | None) -> None:
    """The Dock shows a copy's progress on a Mac; the Windows taskbar is left alone."""


def install(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())


class Glide:
    """A number between 0 and 1 that eases towards whatever it is set to, repainting as it moves.

    Everything here is painted by hand, so there is no stylesheet transition to lean on: a hover or
    a switch is a value the paintEvent reads, and this is what moves that value over a few frames
    instead of snapping it. CARDCOPY_NO_ANIMATION=1 makes every change instant.
    """

    def __init__(self, widget: QWidget, value: float = 0.0, ms: int = 130,
                 curve: QEasingCurve.Type = QEasingCurve.OutCubic) -> None:
        self.value = float(value)
        self.ms = 0 if os.environ.get("CARDCOPY_NO_ANIMATION") else ms
        self._widget = widget
        self._anim = QVariantAnimation(widget)
        self._anim.setDuration(self.ms)
        self._anim.setEasingCurve(curve)
        self._anim.valueChanged.connect(self._step)

    def _step(self, value) -> None:
        self.value = float(value)
        self._widget.update()

    def to(self, target: float) -> None:
        target = float(target)
        if abs(target - self.value) < 0.002 and self._anim.state() != QVariantAnimation.Running:
            return
        self._anim.stop()
        if not self.ms:
            self._step(target)
            return
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """a at t=0, b at t=1."""
    t = max(0.0, min(1.0, t))
    return QColor(*(int(round(getattr(a, part)() + (getattr(b, part)() - getattr(a, part)()) * t))
                    for part in ("red", "green", "blue", "alpha")))


def white(alpha: float) -> QColor:
    return QColor(255, 255, 255, int(255 * alpha))


def _glass(p: QPainter, rect: QRectF, radius: float, top: float = 0.11, bottom: float = 0.05,
           border: float = 0.16) -> None:
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    fill.setColorAt(0, white(top))
    fill.setColorAt(1, white(bottom))
    p.setPen(QPen(white(border), 1))
    p.setBrush(fill)
    p.drawRoundedRect(rect, radius, radius)


def enable_blur_behind(widget: QWidget) -> bool:
    """Ask Windows to blur whatever is behind this (translucent) window. False if it cannot."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class AccentPolicy(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class CompositionData(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.POINTER(AccentPolicy)),
                    ("SizeOfData", ctypes.c_size_t)]

    try:
        call = ctypes.windll.user32.SetWindowCompositionAttribute
        call.argtypes = [wintypes.HWND, ctypes.POINTER(CompositionData)]
        call.restype = ctypes.c_int
        # 3 = ACCENT_ENABLE_BLURBEHIND. (4, acrylic, blurs harder but makes Windows 10 lag while dragging.)
        policy = AccentPolicy(3, 0, 0, 0)
        data = CompositionData(19, ctypes.pointer(policy), ctypes.sizeof(policy))   # 19 = WCA_ACCENT_POLICY
        return bool(call(int(widget.winId()), ctypes.byref(data)))
    except (AttributeError, OSError):
        return False


class _Draggable(QWidget):
    """Empty parts of this widget move the (frameless) window; double-click maximises."""

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.LeftButton and handle is not None:
            handle.startSystemMove()          # the real thing: Aero snap and edge-tiling keep working

    def mouseDoubleClickEvent(self, event) -> None:
        win = self.window()
        win.showNormal() if win.isMaximized() else win.showMaximized()


class Sidebar(_Draggable):
    """Solid, so the navigation stays readable over any desktop."""

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), SIDEBAR)
        p.end()


class _WindowButton(QPushButton):
    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind
        self.setFixedSize(46, 32)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse()
        if hover:
            p.fillRect(self.rect(), QColor("#E5484D") if self.kind == "close" else white(0.12))
        p.setPen(QPen(QColor("white") if hover else white(0.7), 1.3))
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.kind == "min":
            p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
        elif self.kind == "max":
            p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
        else:
            p.drawLine(QPointF(c.x() - 5, c.y() - 5), QPointF(c.x() + 5, c.y() + 5))
            p.drawLine(QPointF(c.x() + 5, c.y() - 5), QPointF(c.x() - 5, c.y() + 5))
        p.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


class TitleStrip(_Draggable):
    """Our own caption (the native one smears under blur-behind): drag area plus window buttons."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(32)
        from PySide6.QtWidgets import QHBoxLayout
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(1)
        for kind, action in (("min", lambda: self.window().showMinimized()),
                             ("max", lambda: self.mouseDoubleClickEvent(None)),
                             ("close", lambda: self.window().close())):
            button = _WindowButton(kind)
            button.clicked.connect(action)
            lay.addWidget(button)


def hit_test_border(widget: QWidget, message) -> int | None:
    """WM_NCHITTEST for a frameless window: the outer 7 px resize it, like a native frame."""
    import ctypes
    from ctypes import wintypes
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != 0x0084 or widget.isMaximized():
        return None
    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(int(widget.winId()), ctypes.byref(rect))
    b = int(7 * widget.devicePixelRatioF())
    left, right = x < rect.left + b, x >= rect.right - b
    top, bottom = y < rect.top + b, y >= rect.bottom - b
    codes = {(True, False, True, False): 13, (False, True, True, False): 14,      # top-left, top-right
             (True, False, False, True): 16, (False, True, False, True): 17,      # bottom-left, bottom-right
             (True, False, False, False): 10, (False, True, False, False): 11,    # left, right
             (False, False, True, False): 12, (False, False, False, True): 15}    # top, bottom
    return codes.get((left, right, top, bottom))


class Backdrop(QWidget):
    """The workspace behind the panels, rounded where it meets the sidebar.

    see_through=True: a dark tint with soft glows over the blurred desktop (the window must be
    translucent and enable_blur_behind() must have worked). Otherwise the same thing, opaque.
    """
    see_through = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        pane = QPainterPath()
        pane.addRoundedRect(r.adjusted(0, 0, 40, 0), 28, 28)    # only the left corners end up visible
        corners = QPainterPath()
        corners.addRect(r)
        p.fillPath(corners.subtracted(pane), SIDEBAR)           # the wedges outside the rounded corners
        p.setClipPath(pane)
        base = QLinearGradient(r.topLeft(), r.bottomRight())
        alpha = 205 if self.see_through else 255   # dark enough to read over a white window
        base.setColorAt(0, QColor(42, 43, 48, alpha))
        base.setColorAt(1, QColor(24, 22, 22, alpha + (25 if self.see_through else 0)))
        p.fillRect(r, base)
        strength = 0.6 if self.see_through else 1.0
        for fx, fy, radius, color in ((0.88, 0.05, 0.55, QColor(255, 110, 60, 85)),
                                      (0.08, 0.95, 0.50, QColor(45, 212, 191, 50)),
                                      (0.55, 0.60, 0.45, QColor(120, 110, 255, 28))):
            centre = QPointF(r.width() * fx, r.height() * fy)
            glow = QRadialGradient(centre, max(r.width(), r.height()) * radius)
            glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), int(color.alpha() * strength)))
            glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.fillRect(r, glow)
        if self.see_through:                                    # a hairline where the glass starts
            p.setClipping(False)
            p.setPen(QPen(white(0.10), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(pane)
        p.end()


class Panel(QFrame):
    """A glass panel. well=True is a darker recessed box; light=True a bright product tile."""

    def __init__(self, radius: int = 18, well: bool = False, light: bool = False) -> None:
        super().__init__()
        self.radius, self.well, self.light, self.selected = radius, well, light, False
        self.setContentsMargins(2, 2, 2, 2)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.light:
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            fill.setColorAt(0, QColor("#F4F5F8"))
            fill.setColorAt(1, QColor("#C4C8D2"))
            p.setPen(QPen(white(0.5), 1))
            p.setBrush(fill)
            p.drawRoundedRect(rect, self.radius, self.radius)
        elif self.well:
            p.setPen(QPen(white(0.08), 1))
            p.setBrush(QColor(0, 0, 0, 75))
            p.drawRoundedRect(rect, self.radius, self.radius)
        else:
            _glass(p, rect, self.radius)
        if self.selected:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(QColor(255, 91, 58, 30))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        p.end()


class PillButton(QPushButton):
    """Glass pill; primary=True is the solid coral call to action. Checkable ones stay lit."""

    def __init__(self, text: str, primary: bool = False, small: bool = False) -> None:
        super().__init__(text)
        self.primary, self.small = primary, small
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("font-weight: 600;")
        self._hover = Glide(self, ms=130)

    def sizeHint(self) -> QSize:
        w = int(self.fontMetrics().horizontalAdvance(self.text()) * 1.1) + (30 if self.small else 46)
        return QSize(w + 2 * M, (30 if self.small else 40) + 2 * M)

    minimumSizeHint = sizeHint

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(M, M, -M, -M)
        radius = rect.height() / 2
        enabled = self.isEnabled()
        hover = self._hover.value if enabled else 0.0        # eased by enter/leaveEvent
        pressed = self.isDown() or self.isChecked()
        if self.primary and enabled:
            fill = QLinearGradient(rect.topLeft(), rect.topRight())
            fill.setColorAt(0, mix(ACCENT, ACCENT.lighter(112), hover))
            fill.setColorAt(1, mix(QColor("#FF7A45"), QColor("#FF7A45").lighter(112), hover))
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect.translated(0, 1 if self.isDown() else 0), radius, radius)
            color = QColor("white")
        else:
            level = 0.04 if pressed else 0.09 + 0.07 * hover
            _glass(p, rect, radius, top=level + 0.03, bottom=level, border=0.18 if enabled else 0.07)
            color = QColor(ACCENT if pressed and enabled else QColor(TEXT)) if enabled else white(0.28)
        p.setPen(color)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignCenter, self.text())
        p.end()

    def enterEvent(self, event) -> None:
        self._hover.to(1.0 if self.isEnabled() else 0.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)


class LineEdit(QLineEdit):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setFrame(False)
        self.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {TEXT};"
                           f" selection-background-color: {ACCENT.name()}; selection-color: white; }}")
        self.setTextMargins(16, 0, 16, 0)
        self.setMinimumHeight(40)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(ACCENT if self.hasFocus() else white(0.14), 1.2 if self.hasFocus() else 1))
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.end()
        super().paintEvent(event)


class Toggle(QCheckBox):
    """A check box drawn as a switch; coral when on."""
    TRACK_W, TRACK_H, GAP = 42, 22, 10

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.muted = False
        self.setCursor(Qt.PointingHandCursor)
        # the knob slides and the track colours across; hover lifts the track very slightly
        self._knob = Glide(self, value=1.0 if self.isChecked() else 0.0, ms=170)
        self._hover = Glide(self, ms=110)
        self.toggled.connect(lambda on: self._knob.to(1.0 if on else 0.0))

    def setChecked(self, on: bool) -> None:
        # settings are loaded with signals blocked, so toggled cannot be the only thing that moves it
        super().setChecked(on)
        self._knob.to(1.0 if on else 0.0)

    def sizeHint(self) -> QSize:
        text_w = int(self.fontMetrics().horizontalAdvance(self.text()) * 1.12)   # room for a bold style
        return QSize(self.TRACK_W + 4 + (self.GAP + text_w if self.text() else 0) + 6, self.TRACK_H + 10)

    minimumSizeHint = sizeHint

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def set_muted(self, muted: bool) -> None:
        """Ticked underneath, but switched off by something else, so it is drawn off.

        A switch whose knob sits to the right reads as on however it is coloured, so a muted one is
        drawn in the off position: nothing is happening, and nothing should look as if it is. The
        tick itself is untouched, and comes back the moment whatever muted it is switched on again.
        """
        if muted != self.muted:
            self.muted = muted
            self.update()

    def enterEvent(self, event) -> None:
        self._hover.to(1.0 if self.isEnabled() else 0.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(2, (self.height() - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)
        on, enabled = self.isChecked(), self.isEnabled()
        slid = 0.0 if self.muted else (self._knob.value if enabled else (1.0 if on else 0.0))
        lift = self._hover.value * (1.0 - slid) * 0.06        # only the off half needs lifting
        p.setPen(QPen(white(0.16 * (1.0 - slid)), 1))
        p.setBrush(mix(white(0.10 + lift), ACCENT if enabled else ACCENT.darker(160), slid))
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        d = self.TRACK_H - 6
        left, right = track.left() + 3, track.right() - d - 3
        x = left + (right - left) * slid
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white") if enabled else white(0.45))
        p.drawEllipse(QRectF(x, track.center().y() - d / 2, d, d))
        if self.text():
            p.setPen(QColor(TEXT) if enabled else white(0.35))
            p.setFont(self.font())
            p.drawText(QRectF(track.right() + self.GAP, 0, self.width(), self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


Check = Toggle          # the Mac look draws ticks as check boxes; here every on/off is a switch


class ProgressBar(QWidget):
    """Same calls as the QProgressBar it replaces."""

    def __init__(self) -> None:
        super().__init__()
        self._min, self._max, self._value, self._text = 0, 100, 0, ""
        self.setFixedHeight(40)

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
        track = QRectF(2, 6, self.width() - 4, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(white(0.10))
        p.drawRoundedRect(track, 5, 5)
        frac = min(max((self._value - self._min) / (self._max - self._min), 0), 1)
        if frac > 0:
            fill = QRectF(track.left(), track.top(), max(track.width() * frac, 10), track.height())
            g = QLinearGradient(fill.topLeft(), fill.topRight())
            g.setColorAt(0, ACCENT)
            g.setColorAt(1, ACCENT_2)
            p.setBrush(g)
            p.drawRoundedRect(fill, 5, 5)
        if frac or self._text:
            p.setPen(QColor(TEXT_SOFT))
            p.drawText(QRectF(0, 20, self.width(), 18), Qt.AlignCenter,
                       f"{frac * 100:.0f}%" + (f"   ·   {self._text}" if self._text else ""))
        p.end()


# ------------------------------------------------------------------ sidebar

def _icon(p: QPainter, name: str, r: QRectF) -> None:
    """Line icons, drawn inside r (about 18 px square)."""
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    if name == "camera":
        p.drawRoundedRect(QRectF(x, y + h * 0.22, w, h * 0.66), 3, 3)
        p.drawRoundedRect(QRectF(x + w * 0.30, y + h * 0.06, w * 0.40, h * 0.18), 1.5, 1.5)
        p.drawEllipse(QPointF(x + w / 2, y + h * 0.56), w * 0.19, w * 0.19)
    elif name == "card":
        path = QPainterPath(QPointF(x + w * 0.18, y))
        for px, py in ((0.62, 0), (0.85, 0.24), (0.85, 1), (0.18, 1), (0.18, 0)):
            path.lineTo(x + w * px, y + h * py)
        p.drawPath(path)
        for i in range(3):
            cx = x + w * (0.34 + i * 0.13)
            p.drawLine(QPointF(cx, y + h * 0.14), QPointF(cx, y + h * 0.36))
    elif name == "refresh":
        p.drawArc(QRectF(x + 1, y + 1, w - 2, h - 2), 40 * 16, 280 * 16)
        tip = QPointF(x + w * 0.90, y + h * 0.18)
        p.drawLine(tip, QPointF(tip.x() - w * 0.30, tip.y() + h * 0.02))
        p.drawLine(tip, QPointF(tip.x() - w * 0.02, tip.y() + h * 0.30))
    elif name == "folder":
        path = QPainterPath(QPointF(x, y + h * 0.16))
        for px, py in ((0.38, 0.16), (0.50, 0.32), (1, 0.32), (1, 0.90), (0, 0.90), (0, 0.16)):
            path.lineTo(x + w * px, y + h * py)
        p.drawPath(path)
    elif name == "eject":
        path = QPainterPath(QPointF(x + w / 2, y + h * 0.05))
        path.lineTo(x + w * 0.95, y + h * 0.58)
        path.lineTo(x + w * 0.05, y + h * 0.58)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(x + w * 0.05, y + h * 0.90), QPointF(x + w * 0.95, y + h * 0.90))
    elif name == "image":
        p.drawRoundedRect(QRectF(x, y + h * 0.12, w, h * 0.76), 3, 3)
        p.drawEllipse(QPointF(x + w * 0.30, y + h * 0.38), w * 0.08, w * 0.08)
        p.drawPolyline([QPointF(x + w * 0.08, y + h * 0.80), QPointF(x + w * 0.42, y + h * 0.52),
                        QPointF(x + w * 0.60, y + h * 0.68), QPointF(x + w * 0.74, y + h * 0.56),
                        QPointF(x + w * 0.94, y + h * 0.80)])
    elif name == "audio":
        p.drawRoundedRect(QRectF(x + w * 0.34, y + h * 0.04, w * 0.32, h * 0.50), w * 0.16, w * 0.16)   # capsule
        p.drawArc(QRectF(x + w * 0.16, y + h * 0.26, w * 0.68, h * 0.52), 200 * 16, 140 * 16)           # cradle
        p.drawLine(QPointF(x + w / 2, y + h * 0.78), QPointF(x + w / 2, y + h * 0.95))
    elif name == "film":
        p.drawRoundedRect(QRectF(x, y + h * 0.20, w * 0.68, h * 0.60), 3, 3)
        path = QPainterPath(QPointF(x + w * 0.68, y + h * 0.42))
        path.lineTo(x + w, y + h * 0.24)
        path.lineTo(x + w, y + h * 0.76)
        path.lineTo(x + w * 0.68, y + h * 0.58)
        p.drawPath(path)
    elif name == "open":
        p.drawRoundedRect(QRectF(x, y + h * 0.25, w * 0.75, h * 0.75), 3, 3)
        p.drawLine(QPointF(x + w * 0.45, y + h * 0.55), QPointF(x + w, y))
        p.drawLine(QPointF(x + w, y), QPointF(x + w * 0.62, y))
        p.drawLine(QPointF(x + w, y), QPointF(x + w, y + h * 0.38))


class NavButton(QPushButton):
    """Sidebar entry: an icon chip and a label. A checked one is the current page."""

    def __init__(self, text: str, icon: str, checkable: bool = False) -> None:
        super().__init__(text)
        self.icon_name = icon
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        self._hover = Glide(self, ms=130)
        self._active = Glide(self, value=1.0 if self.isChecked() else 0.0, ms=180)
        self.toggled.connect(lambda on: self._active.to(1.0 if on else 0.0))

    def setChecked(self, on: bool) -> None:
        super().setChecked(on)
        self._active.to(1.0 if on else 0.0)

    def sizeHint(self) -> QSize:
        return QSize(190, 42)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        hover = max(self._hover.value, 1.0 if self.isDown() else 0.0) if enabled else 0.0
        active = self._active.value if enabled else (1.0 if self.isChecked() else 0.0)
        chip = QRectF(4, (self.height() - 32) / 2, 32, 32)
        p.setPen(Qt.NoPen)
        p.setBrush(mix(white(0.08 + 0.08 * hover), ACCENT, active))
        p.drawRoundedRect(chip, 10, 10)
        ink = mix(white(0.6 + 0.25 * hover), QColor("white"), active) if enabled else white(0.2)
        p.setPen(QPen(ink, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        _icon(p, self.icon_name, chip.adjusted(8, 8, -8, -8))
        p.setPen(mix(QColor(TEXT_SOFT), QColor("white"), max(hover, active)) if enabled else white(0.22))
        font = QFont(self.font())
        font.setWeight(QFont.DemiBold if self.isChecked() else QFont.Normal)
        p.setFont(font)
        p.drawText(QRectF(chip.right() + 12, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()

    def enterEvent(self, event) -> None:
        self._hover.to(1.0 if self.isEnabled() else 0.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)


ActionButton = NavButton    # Refresh / Add folder / Eject: sidebar entries here, toolbar buttons on a Mac


class Logo(QWidget):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.setFixedHeight(44)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        chip = QRectF(4, 5, 34, 34)
        p.setPen(Qt.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(chip, 11, 11)
        p.setPen(QPen(QColor("white"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        _icon(p, "card", chip.adjusted(9, 8, -9, -8))
        font = QFont(self.font())
        font.setPointSize(14)
        font.setWeight(QFont.Bold)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRectF(chip.right() + 12, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()


def nav_caption(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet("color: rgba(255,255,255,0.32); font-size: 8pt; font-weight: 600; padding: 14px 6px 4px 6px;")
    return label


# ------------------------------------------------------------------ helpers

def well_text(edit: QPlainTextEdit, radius: int = 14) -> Panel:
    """Sit a text box in a recessed well."""
    edit.setFrameShape(QFrame.NoFrame)
    well = Panel(radius, well=True)
    lay = QVBoxLayout(well)
    lay.setContentsMargins(12, 8, 6, 8)
    lay.addWidget(edit)
    return well


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {TEXT}; font-size: 15pt; font-weight: 600; padding: 2px 2px;")
    return label


def app_stylesheet() -> str:
    text, accent = TEXT, ACCENT.name()
    return f"""
    QWidget {{ background: transparent; color: {text}; font-family: "Segoe UI Variable Text", "Segoe UI";
               font-size: 10pt; }}
    QMainWindow {{ background: transparent; }}
    QDialog {{ background: #24252A; }}
    QToolTip {{ background: #2C2D33; color: {text}; border: 1px solid #44464F; padding: 4px 8px; }}
    QPlainTextEdit {{ background: transparent; border: none; color: {text};
                      selection-background-color: {accent}; selection-color: white; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: rgba(255,255,255,0.22); border-radius: 3px; min-height: 30px; min-width: 30px; }}
    QScrollBar::handle:hover {{ background: rgba(255,255,255,0.38); }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QComboBox, QSpinBox, QTimeEdit {{ background: rgba(255,255,255,0.09); border: 1px solid rgba(255,255,255,0.16);
                           border-radius: 12px; padding: 4px 10px; min-height: 22px; color: {text}; }}
    QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {{ border-color: rgba(255,255,255,0.34); }}
    QComboBox:disabled, QSpinBox:disabled, QTimeEdit:disabled {{ color: rgba(255,255,255,0.3); }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{ASSETS}/chevron-down-light.png"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: #2C2D33; color: {text}; border: 1px solid #44464F; outline: none;
                                   selection-background-color: {accent}; selection-color: white; }}
    QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{ border: none; width: 20px; background: transparent; }}
    QSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url("{ASSETS}/chevron-up-light.png"); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url("{ASSETS}/chevron-down-light.png"); width: 10px; height: 10px; }}
    QDialog QLabel {{ color: {text}; }}
    QDialog QPushButton {{ background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18);
                           border-radius: 12px; padding: 6px 18px; min-width: 60px; color: {text}; }}
    QDialog QPushButton:hover {{ border-color: {accent}; }}
    QDialog QPushButton:default {{ background: {accent}; border-color: {accent}; color: white; }}
    QDialog QLineEdit {{ background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.18); border-radius: 10px;
                         padding: 6px 10px; color: {text}; }}
    QTreeWidget {{ background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
                   color: {text}; outline: none; selection-background-color: rgba(255,91,58,0.35);
                   selection-color: white; }}
    QTreeWidget::item {{ padding: 3px 2px; }}
    QTreeWidget::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.45);
                              background: rgba(255,255,255,0.06); }}
    QTreeWidget::indicator:checked {{ background: {accent}; border-color: {accent};
                                      image: url("{ASSETS}/check-white.png"); }}
    QHeaderView::section {{ background: transparent; color: {TEXT_SOFT}; border: none;
                            border-bottom: 1px solid rgba(255,255,255,0.12); padding: 5px 8px; }}
    """
