"""
Lecteur de musique : la fenêtre qui s'ouvre d'un clic sur le widget
« Musique en cours », au milieu de la barre.

Grande pochette, titre, artiste et album, frise du morceau (cliquer ou
glisser pour s'y déplacer, si l'application le permet), précédent /
lecture-pause / suivant, et un bouton pour afficher l'application qui joue
(Spotify, Deezer, le navigateur…).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from core.media import MediaInfo, format_time
from ui import icons, styles
from ui.popup import Popup
from ui.widgets.base import IconButton

TICK_MS = 250                 # avancée de la frise pendant la lecture


class CoverArt(QWidget):
    """Pochette carrée aux coins arrondis ; une note de musique s'il n'y en a pas."""

    SIZE = 24

    def __init__(self, size: int = 0, radius: float = 5.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._data = b""
        self._radius = radius
        side = size or self.SIZE
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_cover(self, data: bytes) -> None:
        if data == self._data and (not data or not self._pixmap.isNull()):
            return                      # même pochette : rien à recharger
        self._data = data
        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data)
        self._pixmap = pixmap
        self.update()

    @property
    def has_cover(self) -> bool:
        return not self._pixmap.isNull()

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(clip)
        if self._pixmap.isNull():
            painter.fillRect(rect, QColor(styles.BUTTON_BG))
            inset = rect.width() * 0.22
            icons.draw(painter, "music", rect.adjusted(inset, inset, -inset, -inset),
                       styles.accent("media", styles.MASTER_SCOPE))
            return
        side = min(self._pixmap.width(), self._pixmap.height())      # recadrage carré, centré
        source = QRectF((self._pixmap.width() - side) / 2, (self._pixmap.height() - side) / 2,
                        side, side)
        painter.drawPixmap(rect, self._pixmap, source)


class SeekBar(QWidget):
    """Frise du morceau : clic ou glisser pour s'y déplacer."""

    seeked = Signal(float)       # position choisie (secondes)
    HEIGHT = 18
    TRACK = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.position = 0.0
        self.duration = 0.0
        self.seekable = False
        self._drag: float | None = None          # position pendant un glisser
        self._hover = False
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(120)

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    def set_state(self, position: float, duration: float, seekable: bool) -> None:
        self.position, self.duration = position, duration
        if seekable != self.seekable:
            self.seekable = seekable
            self.setCursor(Qt.CursorShape.PointingHandCursor if seekable
                           else Qt.CursorShape.ArrowCursor)
        self.update()

    def _fraction(self, position: float) -> float:
        return max(0.0, min(1.0, position / self.duration)) if self.duration > 0 else 0.0

    def _position_at(self, x: float) -> float:
        inset = self.HEIGHT / 2
        width = max(1.0, self.width() - 2 * inset)
        return max(0.0, min(1.0, (x - inset) / width)) * self.duration

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.seekable and self.duration > 0 and event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._position_at(event.position().x())
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = self._position_at(event.position().x())
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.button() == Qt.MouseButton.LeftButton:
            target = self._position_at(event.position().x())
            self._drag = None
            self.position = target
            self.seeked.emit(target)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self.HEIGHT / 2
        y = (self.height() - self.TRACK) / 2
        track = QRectF(inset, y, self.width() - 2 * inset, self.TRACK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(styles.BORDER_COLUMN))
        painter.drawRoundedRect(track, 2, 2)
        if self.duration <= 0:
            return
        shown = self._drag if self._drag is not None else self.position
        done = QRectF(track.left(), y, track.width() * self._fraction(shown), self.TRACK)
        painter.setBrush(QColor(styles.GREEN_NEON))
        painter.drawRoundedRect(done, 2, 2)
        if self.seekable and (self._hover or self._drag is not None):
            painter.setBrush(QColor(styles.TEXT_PRIMARY))
            painter.drawEllipse(QRectF(done.right() - 6, self.height() / 2 - 6, 12, 12))


class MediaPopup(Popup):
    """Le lecteur : pochette, morceau, frise et commandes."""

    COVER = 168

    def __init__(self, media, windows=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media = media
        self._windows = windows
        self._info: MediaInfo | None = None
        self.body.setSpacing(8)
        self.setMinimumWidth(self.COVER + 28)

        self.cover = CoverArt(self.COVER, radius=10)
        cover_row = QHBoxLayout()
        cover_row.addStretch(1)
        cover_row.addWidget(self.cover)
        cover_row.addStretch(1)
        self.body.addLayout(cover_row)
        self.body.addSpacing(4)

        self.title = QLabel()
        self.title.setObjectName("title")
        self.artist = QLabel()
        self.artist.setObjectName("secondary")
        self.album = QLabel()
        self.album.setObjectName("muted")
        for label in (self.title, self.artist, self.album):
            label.setWordWrap(True)
            label.setMaximumWidth(self.COVER + 120)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.body.addWidget(label)

        self.seek = SeekBar()
        self.seek.seeked.connect(self._seek)
        self.body.addWidget(self.seek)
        times = QHBoxLayout()
        times.setContentsMargins(4, 0, 4, 0)
        self.elapsed = QLabel("0:00")
        self.elapsed.setObjectName("muted")
        self.total = QLabel("")
        self.total.setObjectName("muted")
        times.addWidget(self.elapsed)
        times.addStretch(1)
        times.addWidget(self.total)
        self.body.addLayout(times)

        self.previous = IconButton("previous", "Précédent", size=36, icon_size=18)
        self.play = IconButton("play", "Lecture / pause", filled=True, size=46, icon_size=20)
        self.next = IconButton("next", "Suivant", size=36, icon_size=18)
        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addStretch(1)
        for button in (self.previous, self.play, self.next):
            controls.addWidget(button)
        controls.addStretch(1)
        self.body.addLayout(controls)
        self.previous.clicked.connect(self._media.previous)
        self.play.clicked.connect(self._media.play_pause)
        self.next.clicked.connect(self._media.next)

        self.open_app = QPushButton("")
        self.open_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_app.clicked.connect(self.show_app)
        self.body.addWidget(self.open_app)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._media.changed.connect(self._show)
        self._show(self._media.current)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(max(hint.width(), self.COVER + 120), hint.height())

    def _show(self, info: MediaInfo | None) -> None:
        self._info = info
        playing = info is not None
        for widget in (self.artist, self.album, self.seek, self.elapsed, self.total,
                       self.previous, self.play, self.next):
            widget.setVisible(playing)
        if info is None:
            self.cover.set_cover(b"")
            self.title.setText("Rien en lecture")
            self.open_app.setVisible(False)
            self._timer.stop()
            return
        self.cover.set_cover(info.cover)
        self.title.setText(info.title)
        self.artist.setText(info.artist)
        self.artist.setVisible(bool(info.artist))
        self.album.setText(info.album)
        self.album.setVisible(bool(info.album))
        self.play.set_icon("pause" if info.playing else "play")
        self.previous.setEnabled(info.can_previous)
        self.next.setEnabled(info.can_next)
        self.play.setEnabled(info.can_play_pause)
        has_timeline = info.duration > 0
        for widget in (self.seek, self.elapsed, self.total):
            widget.setVisible(has_timeline)
        self.open_app.setText(f"Afficher {info.app}" if info.app else "")
        self.open_app.setVisible(bool(info.app) and self._windows is not None
                                 and getattr(self._windows, "available", False))
        self._tick()
        if info.playing and has_timeline:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        info = self._info
        if info is None or info.duration <= 0 or self.seek.dragging:
            return
        position = info.position_at()
        self.seek.set_state(position, info.duration, info.can_seek)
        self.elapsed.setText(format_time(position))
        self.total.setText(format_time(info.duration))

    def _seek(self, seconds: float) -> None:
        self.elapsed.setText(format_time(seconds))
        self._media.seek(seconds)

    def show_app(self) -> bool:
        """Affiche la fenêtre de l'application qui joue ; False si introuvable."""
        if self._info is None or self._windows is None:
            return False
        window = self._windows.find_app(self._info.app)
        if window is None:
            self.open_app.setText(f"{self._info.app} : fenêtre introuvable")
            return False
        self._windows.activate(window.hwnd)
        self.close()
        return True
