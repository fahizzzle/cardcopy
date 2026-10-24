"""Draw the Mac app icon: mac/AppIcon.png, 1024 x 1024, on Apple's icon grid.

    python scripts/make_icon.py

The CardCopy mark (a white SD card on coral) as a macOS icon: an 824 pt rounded square centred on the
1024 canvas with a soft drop shadow, as Big Sur and later expect. The Mac build turns it into
AppIcon.icns with sips and iconutil. Run again only when the design changes; the PNG is committed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QRadialGradient  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mac", "AppIcon.png")
SIZE, BODY, RADIUS = 1024, 824, 186


def card_path(x: float, y: float, w: float, h: float, notch: float, r: float) -> QPainterPath:
    """An SD card: rounded corners, the top-right corner cut off."""
    path = QPainterPath(QPointF(x + r, y))
    path.lineTo(x + w - notch, y)
    path.lineTo(x + w, y + notch)
    path.lineTo(x + w, y + h - r)
    path.quadTo(x + w, y + h, x + w - r, y + h)
    path.lineTo(x + r, y + h)
    path.quadTo(x, y + h, x, y + h - r)
    path.lineTo(x, y + r)
    path.quadTo(x, y, x + r, y)
    path.closeSubpath()
    return path


def main() -> int:
    app = QGuiApplication(sys.argv[:1])  # noqa: F841  (QPainter text/AA needs one)
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    body = QRectF((SIZE - BODY) / 2, (SIZE - BODY) / 2 - 6, BODY, BODY)

    for i in range(36, 0, -1):                    # soft shadow, darker near the edge
        spread = i * 1.1
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(3 * (1 - i / 37)) + 1))
        p.drawRoundedRect(body.adjusted(-spread * 0.25, -spread * 0.1 + 12, spread * 0.25, spread * 0.6 + 12),
                          RADIUS + spread * 0.4, RADIUS + spread * 0.4)

    shape = QPainterPath()
    shape.addRoundedRect(body, RADIUS, RADIUS)
    fill = QLinearGradient(body.topLeft(), body.bottomLeft())
    fill.setColorAt(0, QColor("#FF8456"))
    fill.setColorAt(0.55, QColor("#F8592F"))
    fill.setColorAt(1, QColor("#E5401F"))
    p.fillPath(shape, fill)
    glow = QRadialGradient(QPointF(body.center().x(), body.top() + 60), BODY * 0.75)
    glow.setColorAt(0, QColor(255, 255, 255, 70))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(shape, glow)
    p.setClipPath(shape)
    p.setPen(QColor(255, 255, 255, 60))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS - 1.5, RADIUS - 1.5)

    w, h = 392, 492
    x, y = (SIZE - w) / 2, body.center().y() - h / 2 + 4
    for i in range(18, 0, -1):                    # the card's own shadow on the coral
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 20, 0, 4))
        p.drawPath(card_path(x - i * 0.5, y + 14 + i * 0.3, w + i, h + i * 0.5, 120, 44))
    card = card_path(x, y, w, h, 120, 44)
    white = QLinearGradient(QPointF(x, y), QPointF(x, y + h))
    white.setColorAt(0, QColor("#FFFFFF"))
    white.setColorAt(1, QColor("#FFF1EC"))
    p.fillPath(card, white)
    contacts = QLinearGradient(QPointF(x, y + 70), QPointF(x, y + 210))
    contacts.setColorAt(0, QColor("#FF7A4D"))
    contacts.setColorAt(1, QColor("#EE4B26"))
    for n in range(4):
        slot = QPainterPath()
        slot.addRoundedRect(QRectF(x + 62 + n * 64, y + 66, 38, 128), 16, 16)
        p.fillPath(slot, contacts)
    label = QPainterPath()
    label.addRoundedRect(QRectF(x + 62, y + h - 168, w - 124, 96), 26, 26)
    p.fillPath(label, QColor(240, 70, 35, 38))
    p.end()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
