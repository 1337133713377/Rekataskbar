"""
Briques communes des widgets de la barre : la « pill » (cadre arrondi), le
texte, l'icône, le bouton-icône et le petit VU-mètre.

Tout est dessiné à la main et lit les couleurs de ui.styles à chaque dessin :
un changement de thème (dans REKA ou dans les réglages) n'a qu'à redessiner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QSizePolicy, QWidget

from ui import icons, styles

PILL_RADIUS = 8
PILL_PADDING = 9
ICON_SIZE = 16
VU_FLOOR_DB = -60.0
VU_YELLOW_DB = -9.0          # au-dessus : jaune
VU_RED_DB = 0.0              # au-dessus : rouge


@dataclass
class Context:
    """Ce dont les widgets ont besoin : la config et les services de la barre."""

    cfg: dict
    vm: object                # core.voicemeeter.VoicemeeterLink
    reka: object              # core.reka_link.RekaLink
    media: object             # core.media.MediaBackend
    system: object            # core.system.SystemMonitor
    windows: object           # core.windows.WindowBackend
    weather: object           # core.weather.WeatherService
    save: Callable[[], None]
    open_settings: Callable[[str], None]
    open_mixer: Callable[[QWidget], None]
    open_reka: Callable[[], None]
    quit: Callable[[], None]

    def widget_cfg(self, key: str) -> dict:
        value = self.cfg.setdefault("widgets", {}).setdefault(key, {})
        return value if isinstance(value, dict) else {}


def level_fraction(db: float) -> float:
    """Niveau en dB → part de la barre du VU-mètre (0 à 1)."""
    return max(0.0, min(1.0, (float(db) - VU_FLOOR_DB) / (6.0 - VU_FLOOR_DB)))


def level_color(db: float, base: str) -> str:
    if db >= VU_RED_DB:
        return styles.VU_RED
    if db >= VU_YELLOW_DB:
        return styles.VU_YELLOW
    return base


def format_db(db: float) -> str:
    """« +2,0 dB », « -9,0 dB », « 0,0 dB »."""
    text = f"{db:+.1f}" if abs(db) >= 0.05 else "0.0"
    return text.replace(".", ",") + " dB"


class Pill(QWidget):
    """Cadre arrondi d'un widget ; ses éléments s'alignent dans une rangée."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, *, clickable: bool = False,
                 framed: bool = True) -> None:
        super().__init__(parent)
        self._clickable = clickable
        self._framed = framed
        self._hover = False
        self._pressed = False
        self.tint: str | None = None          # fond coloré (micro coupé…)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(PILL_PADDING, 0, PILL_PADDING, 0)
        self.row.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_shown(self, shown: bool) -> None:
        """Affiche ou cache le widget dans la barre. Hors de la barre (pas encore
        de parent), on ne l'affiche pas : Qt en ferait une fenêtre à part."""
        if shown and self.parentWidget() is None:
            return
        self.setVisible(shown)

    def set_tint(self, value: str | None) -> None:
        if value != self.tint:
            self.tint = value
            self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
        else:
            event.ignore()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._framed and not (self._clickable and self._hover) and not self.tint:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.tint:
            background, border = self.tint, styles.mix(self.tint, styles.WHITE, 0.18)
        else:
            background = styles.BUTTON_HOVER if self._clickable and self._hover else styles.BG_COLUMN
            border = styles.BORDER_COLUMN
        painter.setBrush(QColor(background))
        painter.setPen(QColor(border))
        painter.drawRoundedRect(rect, PILL_RADIUS, PILL_RADIUS)


class Text(QWidget):
    """Texte d'une ligne ; `role` est le nom d'une couleur de ui.styles."""

    def __init__(self, text: str = "", role: str = "TEXT_PRIMARY", size: int = 12,
                 weight: QFont.Weight = QFont.Weight.Medium, max_width: int = 0,
                 min_chars: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.role = role
        self._size = size
        self._weight = weight
        self._max_width = max_width
        self._min_chars = min_chars
        self.color: str | None = None          # couleur imposée (passe avant `role`)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def set_color(self, color: str | None) -> None:
        if color != self.color:
            self.color = color
            self.update()

    def _metrics(self) -> QFontMetrics:
        return QFontMetrics(styles.font(self._size, self._weight))

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self._metrics()
        width = metrics.horizontalAdvance(self._text) + 2
        if self._min_chars:
            width = max(width, metrics.horizontalAdvance("0" * self._min_chars) + 2)
        if self._max_width:
            width = min(width, self._max_width)
        return QSize(width, metrics.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(styles.font(self._size, self._weight))
        painter.setPen(QColor(self.color or getattr(styles, self.role)))
        text = self._metrics().elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         text)


class Icon(QWidget):
    """Icône au trait (ui.icons) ; `role` est le nom d'une couleur de ui.styles."""

    def __init__(self, name: str, role: str = "TEXT_SECONDARY", size: int = ICON_SIZE,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.role = role
        self.color: str | None = None
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_icon(self, name: str) -> None:
        if name != self.name:
            self.name = name
            self.update()

    def set_color(self, color: str | None) -> None:
        if color != self.color:
            self.color = color
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        icons.draw(painter, self.name, QRectF(self.rect()), self.color or getattr(styles, self.role))


class IconButton(QAbstractButton):
    """Bouton rond avec une icône ; fond au survol."""

    def __init__(self, name: str, tooltip: str = "", role: str = "TEXT_PRIMARY",
                 size: int = 26, icon_size: int = ICON_SIZE, filled: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.role = role
        self._icon_size = icon_size
        self._filled = filled                   # pastille à la couleur d'accent
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon(self, name: str) -> None:
        if name != self.name:
            self.name = name
            self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        color = getattr(styles, self.role)
        if not self.isEnabled():
            color = styles.TEXT_MUTED
        painter.setPen(Qt.PenStyle.NoPen)
        if self._filled and self.isEnabled():
            fill = styles.GREEN_BRIGHT if self.underMouse() else styles.GREEN_NEON
            painter.setBrush(QColor(fill))
            painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
            color = styles.ink_on(fill)
        elif self.underMouse() and self.isEnabled():
            painter.setBrush(QColor(styles.BUTTON_HOVER if not self.isDown() else styles.PILL_BORDER))
            painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
        inset = (rect.width() - self._icon_size) / 2
        icons.draw(painter, self.name, rect.adjusted(inset, inset, -inset, -inset), color)


class LevelMeter(QWidget):
    """Petit VU-mètre stéréo : deux barres, horizontales ou verticales."""

    def __init__(self, horizontal: bool = True, length: int = 30, thickness: int = 2,
                 element: str = "vu", scope: int | str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._horizontal = horizontal
        self._thickness = thickness
        self._levels = (VU_FLOOR_DB - 40, VU_FLOOR_DB - 40)
        self.element, self.scope = element, scope
        self.dimmed = False
        across = thickness * 2 + 1
        self.setFixedSize(length, across) if horizontal else self.setFixedSize(across, length)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @property
    def levels(self) -> tuple[float, float]:
        return self._levels

    def set_levels(self, left: float, right: float) -> None:
        if (left, right) != self._levels:
            self._levels = (left, right)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        base = styles.accent(self.element, self.scope)
        track = QColor(styles.GREEN_SCALE if not self.dimmed else styles.BORDER_COLUMN)
        t = self._thickness
        for n, db in enumerate(self._levels):
            offset = n * (t + 1)
            fraction = 0.0 if self.dimmed else level_fraction(db)
            if self._horizontal:
                painter.fillRect(QRectF(0, offset, self.width(), t), track)
                if fraction > 0:
                    painter.fillRect(QRectF(0, offset, self.width() * fraction, t),
                                     QColor(level_color(db, base)))
            else:
                painter.fillRect(QRectF(offset, 0, t, self.height()), track)
                if fraction > 0:
                    filled = self.height() * fraction
                    painter.fillRect(QRectF(offset, self.height() - filled, t, filled),
                                     QColor(level_color(db, base)))
