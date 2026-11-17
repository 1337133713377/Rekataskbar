"""
Lecteur de musique : la fenêtre qui s'ouvre d'un clic sur le widget
« Musique en cours », au milieu de la barre.

Grande pochette, titre, artiste et album, frise du morceau (cliquer ou
glisser pour s'y déplacer, si l'application le permet), précédent /
lecture-pause / suivant, et un bouton pour afficher l'application qui joue
(Spotify, Deezer, le navigateur…).
"""

from __future__ import annotations

import math
import time

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


# --------------------------------------------------------------------------- #
# Vague d'audio
# --------------------------------------------------------------------------- #
WAVE_FPS = 30
SILENCE_FALLBACK_S = 2.0      # canal muet alors que ça joue : vague simulée


class AudioWave(QWidget):
    """Petite vague d'audio (barres qui dansent) : elle suit le niveau du canal
    Musique de REKA quand Voicemeeter le donne ; sinon, pendant la lecture,
    elle s'anime seule. En pause, elle se pose."""

    BARS = 7
    BAR_W = 3
    GAP = 2
    FLOOR_DB, FULL_DB = -48.0, -6.0     # échelle de la musique : -6 dB remplit la vague

    def __init__(self, height: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.playing = False
        self._target = 0.0            # niveau voulu (0 à 1), venu de Voicemeeter
        self._level = 0.0             # niveau affiché, lissé
        self._real_at = -1e9          # dernier niveau non muet reçu (time.monotonic)
        self._phase = 0.0
        self.heights = [0.12] * self.BARS
        self.setFixedSize(self.BARS * self.BAR_W + (self.BARS - 1) * self.GAP + 2, height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // WAVE_FPS)
        self._timer.timeout.connect(self.step)

    @property
    def simulated(self) -> bool:
        """La vague s'anime seule (pas de niveau réel récent)."""
        return time.monotonic() - self._real_at > SILENCE_FALLBACK_S

    def set_playing(self, playing: bool) -> None:
        self.playing = playing
        if playing or self._level > 0.01:
            self._timer.start()

    def set_level_db(self, db: float) -> None:
        """Niveau du canal Musique (dB, post-fader)."""
        fraction = max(0.0, min(1.0, (float(db) - self.FLOOR_DB) / (self.FULL_DB - self.FLOOR_DB)))
        self._target = fraction ** 0.6          # la musique douce bouge encore bien
        if db > -55.0:
            self._real_at = time.monotonic()

    def step(self, dt: float = 1.0 / WAVE_FPS) -> None:
        """Une image de l'animation (appelée par la minuterie)."""
        if not self.playing:
            target = 0.0
        elif self.simulated:
            target = 0.55 + 0.2 * math.sin(self._phase * 0.9)
        else:
            target = self._target
        speed = 0.45 if target > self._level else 0.12          # monte vite, retombe doucement
        self._level += (target - self._level) * speed
        self._phase += dt * 6.0
        middle = (self.BARS - 1) / 2            # plus haute au centre, comme une onde
        self.heights = [max(0.12, self._level * (1.0 - 0.35 * abs(n - middle) / middle)
                            * (0.5 + 0.5 * abs(math.sin(self._phase * (1.0 + 0.37 * n) + n * 1.3))))
                        for n in range(self.BARS)]
        if not self.playing and self._level < 0.01:
            self.heights = [0.12] * self.BARS
            self._timer.stop()
        window = self.window()
        if window is not None and window.updatesEnabled():       # derrière un jeu : rien
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(styles.GREEN_NEON if self.playing else styles.TEXT_MUTED))
        usable = self.height() - 2
        for n, fraction in enumerate(self.heights):
            h = max(self.BAR_W, usable * fraction)
            x = 1 + n * (self.BAR_W + self.GAP)
            painter.drawRoundedRect(QRectF(x, (self.height() - h) / 2, self.BAR_W, h),
                                    self.BAR_W / 2, self.BAR_W / 2)


class AppBadge(QWidget):
    """Icône de l'application qui joue (Spotify, Deezer, navigateur…)."""

    def __init__(self, size: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.source = ""
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_pixmap(self, pixmap: QPixmap, source: str) -> None:
        if source != self.source or pixmap.isNull() != self._pixmap.isNull():
            self.source, self._pixmap = source, pixmap
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        if self._pixmap.isNull():
            icons.draw(painter, "music", rect.adjusted(2, 2, -2, -2),
                       styles.accent("media", styles.MASTER_SCOPE))
            return
        clip = QPainterPath()
        clip.addRoundedRect(rect, 4, 4)
        painter.setClipPath(clip)
        painter.drawPixmap(rect, self._pixmap, QRectF(self._pixmap.rect()))
