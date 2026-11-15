"""
Icônes de la barre, dessinées au trait avec QPainter (aucune image à livrer,
nettes à toutes les tailles et recolorées avec le thème).

Chaque icône est décrite dans une grille de 24 × 24, puis mise à l'échelle
dans le rectangle demandé.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

GRID = 24.0


def draw(painter: QPainter, name: str, rect: QRectF, color: QColor | str,
         stroke: float = 1.8) -> None:
    """Dessine l'icône `name` centrée dans `rect`."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side / GRID, side / GRID)
    color = QColor(color)
    pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _ICONS.get(name, _unknown)(painter, color)
    painter.restore()


def _fill(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)


def _unknown(p: QPainter, _c: QColor) -> None:
    p.drawEllipse(QRectF(6, 6, 12, 12))


def _windows(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    for x, y in ((3.5, 3.5), (12.6, 3.5), (3.5, 12.6), (12.6, 12.6)):
        p.drawRoundedRect(QRectF(x, y, 7.9, 7.9), 1.2, 1.2)


def _mic(p: QPainter, _c: QColor) -> None:
    p.drawRoundedRect(QRectF(9, 3, 6, 11), 3, 3)
    path = QPainterPath()
    path.moveTo(5.5, 11)
    path.cubicTo(5.5, 19.5, 18.5, 19.5, 18.5, 11)
    p.drawPath(path)
    p.drawLine(QPointF(12, 17.5), QPointF(12, 21))
    p.drawLine(QPointF(8.5, 21), QPointF(15.5, 21))


def _mic_off(p: QPainter, c: QColor) -> None:
    _mic(p, c)
    p.drawLine(QPointF(4, 3.5), QPointF(20, 20.5))


def _headphones(p: QPainter, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(4.5, 15)
    path.lineTo(4.5, 12)
    path.cubicTo(4.5, 1.5, 19.5, 1.5, 19.5, 12)
    path.lineTo(19.5, 15)
    p.drawPath(path)
    _fill(p, c)
    p.drawRoundedRect(QRectF(3.2, 13, 4.6, 7.5), 1.8, 1.8)
    p.drawRoundedRect(QRectF(16.2, 13, 4.6, 7.5), 1.8, 1.8)


def _sliders(p: QPainter, c: QColor) -> None:
    for x, knob in ((6, 14.5), (12, 8), (18, 13)):
        p.drawLine(QPointF(x, 4), QPointF(x, 20))
    _fill(p, c)
    for x, knob in ((6, 14.5), (12, 8), (18, 13)):
        p.drawRoundedRect(QRectF(x - 2.4, knob - 1.8, 4.8, 3.6), 1.2, 1.2)


def _play(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))


def _pause(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(6.5, 5, 4, 14), 1, 1)
    p.drawRoundedRect(QRectF(13.5, 5, 4, 14), 1, 1)


def _next(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(6, 6), QPointF(15, 12), QPointF(6, 18)]))
    p.drawRoundedRect(QRectF(15.5, 6, 2.6, 12), 0.8, 0.8)


def _previous(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(18, 6), QPointF(9, 12), QPointF(18, 18)]))
    p.drawRoundedRect(QRectF(5.9, 6, 2.6, 12), 0.8, 0.8)


def _cpu(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2, 2)
    for t in (9.5, 14.5):
        p.drawLine(QPointF(t, 3), QPointF(t, 6.5))
        p.drawLine(QPointF(t, 17.5), QPointF(t, 21))
        p.drawLine(QPointF(3, t), QPointF(6.5, t))
        p.drawLine(QPointF(17.5, t), QPointF(21, t))
    _fill(p, c)
    p.drawRoundedRect(QRectF(10, 10, 4, 4), 0.8, 0.8)


def _memory(p: QPainter, _c: QColor) -> None:
    p.drawRoundedRect(QRectF(3, 7, 18, 9), 1.6, 1.6)
    for x in (7.5, 12, 16.5):
        p.drawLine(QPointF(x, 10), QPointF(x, 13))
    for x in (6, 10, 14, 18):
        p.drawLine(QPointF(x, 16), QPointF(x, 19))


def _down(p: QPainter, _c: QColor) -> None:
    p.drawLine(QPointF(12, 4.5), QPointF(12, 19))
    p.drawPolyline(QPolygonF([QPointF(6.5, 13.5), QPointF(12, 19), QPointF(17.5, 13.5)]))


def _up(p: QPainter, _c: QColor) -> None:
    p.drawLine(QPointF(12, 19.5), QPointF(12, 5))
    p.drawPolyline(QPolygonF([QPointF(6.5, 10.5), QPointF(12, 5), QPointF(17.5, 10.5)]))


def _gear(p: QPainter, _c: QColor) -> None:
    p.drawEllipse(QRectF(8.5, 8.5, 7, 7))
    p.save()
    p.translate(12, 12)
    for _ in range(8):
        p.drawLine(QPointF(0, -7.2), QPointF(0, -9.6))
        p.rotate(45)
    p.restore()
    p.drawEllipse(QRectF(4.8, 4.8, 14.4, 14.4))


def _music(p: QPainter, c: QColor) -> None:
    p.drawLine(QPointF(9.5, 17), QPointF(9.5, 5.5))
    p.drawLine(QPointF(9.5, 5.5), QPointF(18.5, 4))
    p.drawLine(QPointF(18.5, 4), QPointF(18.5, 15.5))
    _fill(p, c)
    p.drawEllipse(QRectF(5, 14.5, 5.4, 4.6))
    p.drawEllipse(QRectF(14, 13, 5.4, 4.6))


def _power(p: QPainter, _c: QColor) -> None:
    p.drawLine(QPointF(12, 3.5), QPointF(12, 11.5))
    p.drawArc(QRectF(4.5, 5.5, 15, 15), 130 * 16, -260 * 16)


def _calendar(p: QPainter, _c: QColor) -> None:
    p.drawRoundedRect(QRectF(4, 5.5, 16, 14.5), 2, 2)
    p.drawLine(QPointF(4, 10), QPointF(20, 10))
    p.drawLine(QPointF(8.5, 3.5), QPointF(8.5, 7))
    p.drawLine(QPointF(15.5, 3.5), QPointF(15.5, 7))


# --- Météo --------------------------------------------------------------------
def _cloud_path(dx: float = 0.0, dy: float = 0.0) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(7.5 + dx, 18 + dy)
    path.cubicTo(2.5 + dx, 18 + dy, 2.5 + dx, 11.5 + dy, 7.3 + dx, 11.4 + dy)
    path.cubicTo(8.2 + dx, 6.2 + dy, 15.8 + dx, 6.2 + dy, 16.6 + dx, 10.6 + dy)
    path.cubicTo(21.6 + dx, 10.4 + dy, 21.6 + dx, 18 + dy, 17 + dx, 18 + dy)
    path.closeSubpath()
    return path


def _sun_at(p: QPainter, cx: float, cy: float, radius: float, rays: float) -> None:
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    p.save()
    p.translate(cx, cy)
    for _ in range(8):
        p.drawLine(QPointF(0, -(radius + 1.8)), QPointF(0, -(radius + 1.8 + rays)))
        p.rotate(45)
    p.restore()


def _sun(p: QPainter, _c: QColor) -> None:
    _sun_at(p, 12, 12, 4.2, 2.4)


def _moon(p: QPainter, _c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(19.5, 14.5)
    path.cubicTo(13, 17, 7.5, 11, 10.5, 4.5)
    path.cubicTo(3.5, 6.5, 3.5, 17, 10.5, 19.5)
    path.cubicTo(14.5, 20.8, 18.5, 18.5, 19.5, 14.5)
    p.drawPath(path)


def _cloud(p: QPainter, _c: QColor) -> None:
    p.drawPath(_cloud_path())


def _partly(p: QPainter, _c: QColor) -> None:
    p.save()
    p.setClipRect(QRectF(0, 0, 24, 9.6))
    _sun_at(p, 16.5, 8, 3.2, 1.6)
    p.restore()
    p.drawPath(_cloud_path(-1.0, 2.0))


def _rain(p: QPainter, _c: QColor) -> None:
    p.drawPath(_cloud_path(0, -3))
    for x in (8, 12, 16):
        p.drawLine(QPointF(x, 18), QPointF(x - 1.2, 21.5))


def _snow(p: QPainter, c: QColor) -> None:
    p.drawPath(_cloud_path(0, -3))
    _fill(p, c)
    for x, y in ((8, 19), (12, 21), (16, 19)):
        p.drawEllipse(QPointF(x, y), 1.1, 1.1)


def _storm(p: QPainter, _c: QColor) -> None:
    p.drawPath(_cloud_path(0, -3))
    p.drawPolyline(QPolygonF([QPointF(13, 16.5), QPointF(10.5, 19.5), QPointF(13.5, 19.5),
                              QPointF(11, 22.5)]))


def _fog(p: QPainter, _c: QColor) -> None:
    for y, x1, x2 in ((7, 5, 19), (11, 3, 17), (15, 7, 21), (19, 5, 15)):
        p.drawLine(QPointF(x1, y), QPointF(x2, y))


_ICONS = {
    "windows": _windows, "mic": _mic, "mic_off": _mic_off, "headphones": _headphones,
    "sliders": _sliders, "play": _play, "pause": _pause, "next": _next, "previous": _previous,
    "cpu": _cpu, "memory": _memory, "down": _down, "up": _up, "gear": _gear, "music": _music,
    "power": _power, "calendar": _calendar, "sun": _sun, "moon": _moon, "cloud": _cloud,
    "partly": _partly, "rain": _rain, "snow": _snow, "storm": _storm, "fog": _fog,
}
NAMES = tuple(_ICONS)


def draw_battery(painter: QPainter, rect: QRectF, level: float, color: QColor | str,
                 fill: QColor | str, charging: bool = False) -> None:
    """Pile avec son niveau (0 à 100) ; un éclair quand elle se recharge."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side / GRID, side / GRID)
    color = QColor(color)
    painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 7, 17, 10), 2.4, 2.4)
    painter.drawLine(QPointF(21.6, 10.5), QPointF(21.6, 13.5))
    _fill(painter, QColor(fill))
    width = 13.4 * max(0.0, min(100.0, level)) / 100
    if width > 0.5:
        painter.drawRoundedRect(QRectF(4.3, 8.8, width, 6.4), 1.2, 1.2)
    if charging:
        _fill(painter, color)
        painter.drawPolygon(QPolygonF([QPointF(12.2, 8.2), QPointF(8.6, 12.6), QPointF(11, 12.6),
                                       QPointF(9.8, 15.8), QPointF(13.4, 11.4),
                                       QPointF(11, 11.4)]))
    painter.restore()
