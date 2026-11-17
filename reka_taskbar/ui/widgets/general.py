"""
Widgets d'usage courant : Démarrer, raccourcis, musique en cours, processeur
et mémoire, réseau, météo, batterie, horloge et calendrier.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QLocale, QRectF, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractButton, QCalendarWidget, QLabel, QSizePolicy, QToolButton,
                               QWidget)

from core import shell
from core.media import MediaInfo
from core.system import SystemStats, format_bytes, format_duration, format_rate
from core.weather import Weather
from ui import icons, styles
from ui.media_player import CoverArt
from ui.popup import Popup
from ui.widgets.appicon import app_pixmap
from ui.widgets.base import PILL_RADIUS, Context, Icon, IconButton, Pill, Text

LOAD_WARN, LOAD_HIGH = 75.0, 90.0
BATTERY_LOW = 20.0


def load_color(percent: float) -> str | None:
    """Couleur d'une charge : ambre quand ça chauffe, rouge quand c'est saturé."""
    if percent >= LOAD_HIGH:
        return styles.VU_RED
    if percent >= LOAD_WARN:
        return styles.STATUS_WARN
    return None


# --------------------------------------------------------------------------- #
# Démarrer
# --------------------------------------------------------------------------- #
class StartWidget(Pill):
    """Ouvre le menu Démarrer de Windows."""

    key = "start"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self.row.addWidget(Icon("windows", role="GREEN_NEON", size=17))
        self.setToolTip("Menu Démarrer")
        self.clicked.connect(shell.open_start_menu)

    def menu_actions(self) -> list:
        return [("Explorateur de fichiers", lambda: shell.run("explorer")),
                ("Gestionnaire des tâches", lambda: shell.run("taskmgr")),
                ("Paramètres de Windows", lambda: shell.run("ms-settings:")),
                ("Verrouiller la session", shell.lock_session)]


# --------------------------------------------------------------------------- #
# Raccourcis
# --------------------------------------------------------------------------- #
class ShortcutButton(QAbstractButton):
    SIZE, ICON = 30, 20

    def __init__(self, name: str, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name, self.path = name, path
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(name)

    def enterEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(styles.BUTTON_HOVER))
            painter.drawRoundedRect(QRectF(self.rect()), 7, 7)
        inset = (self.SIZE - self.ICON) / 2
        pixmap = app_pixmap(self.path, self.name, self.ICON, self.devicePixelRatioF())
        painter.drawPixmap(QRectF(inset, inset, self.ICON, self.ICON), pixmap,
                           QRectF(pixmap.rect()))


class ShortcutsWidget(Pill):
    """Tes programmes, dossiers et liens préférés, à un clic (réglages → Raccourcis)."""

    key = "shortcuts"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.row.setContentsMargins(4, 0, 4, 0)
        self.row.setSpacing(2)
        self.buttons: list[ShortcutButton] = []
        for item in ctx.cfg.get("shortcuts") or []:
            if not isinstance(item, dict) or not str(item.get("path") or "").strip():
                continue
            path = str(item["path"]).strip()
            button = ShortcutButton(str(item.get("name") or path), path)
            button.clicked.connect(lambda _checked=False, p=path: shell.run(p))
            self.row.addWidget(button)
            self.buttons.append(button)
        self.set_shown(bool(self.buttons))

    def menu_actions(self) -> list:
        return [("Modifier les raccourcis…", lambda: self._ctx.open_settings("shortcuts"))]


# --------------------------------------------------------------------------- #
# Musique en cours
# --------------------------------------------------------------------------- #
class TrackText(QWidget):
    """Titre et artiste : sur deux lignes quand la barre est assez haute, sur
    une seule (« Titre — Artiste ») sinon."""

    TWO_LINES_MIN = 26            # hauteur (px) à partir de laquelle on passe à deux lignes

    def __init__(self, max_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = ""
        self._artist = ""
        self._max_width = max_width
        self.idle = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    @property
    def text(self) -> str:
        return f"{self._title} — {self._artist}" if self._artist else self._title

    @property
    def two_lines(self) -> bool:
        return bool(self._artist) and self.height() >= self.TWO_LINES_MIN

    def set_track(self, title: str, artist: str = "", idle: bool = False) -> None:
        if (title, artist, idle) != (self._title, self._artist, self.idle):
            self._title, self._artist, self.idle = title, artist, idle
            self.updateGeometry()
            self.update()

    @staticmethod
    def _fonts() -> tuple[QFont, QFont]:
        return styles.font(12, QFont.Weight.Medium), styles.font(11)

    def sizeHint(self) -> QSize:  # noqa: N802
        title_font, artist_font = self._fonts()
        if self.two_lines:
            width = max(QFontMetrics(title_font).horizontalAdvance(self._title),
                        QFontMetrics(artist_font).horizontalAdvance(self._artist))
        else:
            width = QFontMetrics(title_font).horizontalAdvance(self.text)
        return QSize(min(width + 4, self._max_width), QFontMetrics(title_font).height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        was = bool(self._artist) and event.oldSize().height() >= self.TWO_LINES_MIN
        if was != self.two_lines:
            self.updateGeometry()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        title_font, artist_font = self._fonts()
        width = self.width()
        left = Qt.AlignmentFlag.AlignLeft
        if not self.two_lines:
            painter.setFont(title_font)
            painter.setPen(QColor(styles.TEXT_MUTED if self.idle else styles.TEXT_PRIMARY))
            painter.drawText(self.rect(), left | Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(title_font).elidedText(
                                 self.text, Qt.TextElideMode.ElideRight, width))
            return
        title_h = QFontMetrics(title_font).height()
        artist_h = QFontMetrics(artist_font).height()
        top = (self.height() - title_h - artist_h) / 2
        painter.setFont(title_font)
        painter.setPen(QColor(styles.TEXT_PRIMARY))
        painter.drawText(QRectF(0, top, width, title_h), left | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(title_font).elidedText(self._title,
                                                             Qt.TextElideMode.ElideRight, width))
        painter.setFont(artist_font)
        painter.setPen(QColor(styles.TEXT_SECONDARY))
        painter.drawText(QRectF(0, top + title_h - 2, width, artist_h),
                         left | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(artist_font).elidedText(self._artist,
                                                              Qt.TextElideMode.ElideRight, width))


class MediaWidget(Pill):
    """Le lecteur de musique de la barre (au milieu, par défaut) : pochette,
    morceau, frise, précédent / lecture-pause / suivant. Un clic ouvre le
    lecteur complet. Sans musique, il reste discret (« Aucune lecture »)."""

    key = "media"
    MAX_TEXT = 260
    TICK_MS = 1000

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._media = ctx.media
        self._info: MediaInfo | None = None
        self._popup = None
        self.show_idle = bool(ctx.widget_cfg("media").get("show_idle", True))
        self.row.setContentsMargins(5, 0, 5, 0)
        self.cover = CoverArt(26)
        self.title = TrackText(self.MAX_TEXT)
        self.previous = IconButton("previous", "Précédent", role="TEXT_SECONDARY", icon_size=13)
        self.play = IconButton("play", "Lecture / pause", filled=True, icon_size=12, size=24)
        self.next = IconButton("next", "Suivant", role="TEXT_SECONDARY", icon_size=13)
        self.row.addWidget(self.cover)
        self.row.addSpacing(2)
        self.row.addWidget(self.title)
        self.row.addSpacing(2)
        for button in (self.previous, self.play, self.next):
            self.row.addWidget(button)
        self.previous.clicked.connect(self._media.previous)
        self.play.clicked.connect(self._media.play_pause)
        self.next.clicked.connect(self._media.next)
        self.clicked.connect(self.open_player)
        self._timer = QTimer(self)            # avancée de la frise pendant la lecture
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self.update)
        self._media.changed.connect(self._show)
        self._show(self._media.current)

    @property
    def progress(self) -> float:
        """Part du morceau déjà jouée (0 à 1 ; 0 si la durée est inconnue)."""
        info = self._info
        if info is None or info.duration <= 0:
            return 0.0
        return max(0.0, min(1.0, info.position_at() / info.duration))

    def _show(self, info: MediaInfo | None) -> None:
        self._info = info
        available = bool(getattr(self._media, "available", False))
        self.set_shown(info is not None or (self.show_idle and available))
        idle = info is None
        for button in (self.previous, self.play, self.next):
            button.setVisible(not idle)
        if idle:
            self._timer.stop()
            self.cover.set_cover(b"")
            self.title.set_track("Aucune lecture", idle=True)
            self.setToolTip("Rien ne joue pour l'instant (Spotify, Deezer, navigateur…).\n"
                            "Clic : lecteur")
            self.updateGeometry()
            self.update()
            return
        self.title.set_track(info.title, info.artist)
        self.cover.set_cover(info.cover)
        self.play.set_icon("pause" if info.playing else "play")
        self.previous.setEnabled(info.can_previous)
        self.next.setEnabled(info.can_next)
        self.play.setEnabled(info.can_play_pause)
        details = [info.title, info.artist, info.album]
        self.setToolTip("\n".join(d for d in details if d)
                        + (f"\n{info.app}" if info.app else "") + "\nClic : lecteur")
        if info.playing and info.duration > 0:
            self._timer.start()
        else:
            self._timer.stop()
        self.updateGeometry()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Barre fine (mode compact) : pochette et boutons rapetissent avec elle."""
        super().resizeEvent(event)
        cover = max(14, min(26, self.height() - 8))
        if self.cover.width() != cover:
            self.cover.setFixedSize(cover, cover)
        for button, largest in ((self.previous, 26), (self.play, 24), (self.next, 26)):
            side = max(14, min(largest, self.height() - 4))
            if button.width() != side:
                button.setFixedSize(side, side)

    def open_player(self) -> None:
        from ui.media_player import MediaPopup

        if self._popup is not None:
            self._popup.close()
        popup = MediaPopup(self._media, self._ctx.windows, self.window())
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        popup.destroyed.connect(lambda *_a: setattr(self, "_popup", None))
        self._popup = popup
        popup.show_near(self)

    def show_app(self) -> None:
        info = self._info
        window = self._ctx.windows.find_app(info.app) if info is not None and info.app else None
        if window is not None:
            self._ctx.windows.activate(window.hwnd)

    def menu_actions(self) -> list:
        actions = [("Ouvrir le lecteur…", self.open_player)]
        info = self._info
        if info is not None and info.app and getattr(self._ctx.windows, "available", False):
            actions.append((f"Afficher {info.app}", self.show_app))
        return actions

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        progress = self.progress
        if self._info is None or self._info.duration <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right = PILL_RADIUS, self.width() - PILL_RADIUS
        y = self.height() - 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(styles.BORDER_COLUMN))
        painter.drawRoundedRect(QRectF(left, y, right - left, 2), 1, 1)
        if progress > 0:
            painter.setBrush(QColor(styles.GREEN_NEON))
            painter.drawRoundedRect(QRectF(left, y, (right - left) * progress, 2), 1, 1)


# --------------------------------------------------------------------------- #
# Processeur et mémoire, réseau, batterie
# --------------------------------------------------------------------------- #
class SystemWidget(Pill):
    """Charge du processeur et de la mémoire ; un clic ouvre le Gestionnaire des tâches."""

    key = "system"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self.cpu = Text("", size=12, min_chars=4)
        self.ram = Text("", size=12, min_chars=4)
        self.row.addWidget(Icon("cpu"))
        self.row.addWidget(self.cpu)
        self.row.addSpacing(4)
        self.row.addWidget(Icon("memory"))
        self.row.addWidget(self.ram)
        self.clicked.connect(lambda: shell.run("taskmgr"))
        ctx.system.changed.connect(self._show)
        self._show(ctx.system.stats)

    def _show(self, stats: SystemStats) -> None:
        self.cpu.set_text(f"{stats.cpu:.0f} %")
        self.cpu.set_color(load_color(stats.cpu))
        self.ram.set_text(f"{stats.ram:.0f} %")
        self.ram.set_color(load_color(stats.ram))
        memory = (f"{format_bytes(stats.ram_used)} sur {format_bytes(stats.ram_total)}"
                  if stats.ram_total else f"{stats.ram:.0f} %")
        self.setToolTip(f"Processeur : {stats.cpu:.0f} %\nMémoire : {memory}\n"
                        "Clic : Gestionnaire des tâches")


class NetworkWidget(Pill):
    """Débit du réseau : ce qui arrive, ce qui part."""

    key = "network"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.down = Text("", size=12, min_chars=8)
        self.up = Text("", size=12, min_chars=8)
        self.row.addWidget(Icon("down", role="GREEN_NEON", size=14))
        self.row.addWidget(self.down)
        self.row.addWidget(Icon("up", size=14))
        self.row.addWidget(self.up)
        ctx.system.changed.connect(self._show)
        self._show(ctx.system.stats)

    def _show(self, stats: SystemStats) -> None:
        self.down.set_text(format_rate(stats.down))
        self.up.set_text(format_rate(stats.up))
        self.setToolTip(f"Réception : {format_rate(stats.down)}\nEnvoi : {format_rate(stats.up)}")


class BatteryIcon(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.level, self.charging = 100.0, False
        self.setFixedSize(22, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        low = self.level <= BATTERY_LOW and not self.charging
        fill = styles.VU_RED if low else (styles.STATUS_OK if self.charging else styles.TEXT_PRIMARY)
        icons.draw_battery(QPainter(self), QRectF(self.rect()), self.level,
                           styles.TEXT_SECONDARY, fill, self.charging)


class BatteryWidget(Pill):
    """Niveau de la batterie ; caché sur un PC fixe."""

    key = "battery"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon = BatteryIcon()
        self.value = Text("", size=12, min_chars=4)
        self.row.addWidget(self.icon)
        self.row.addWidget(self.value)
        ctx.system.changed.connect(self._show)
        self._show(ctx.system.stats)

    def _show(self, stats: SystemStats) -> None:
        self.set_shown(stats.battery is not None)
        if stats.battery is None:
            return
        self.icon.level, self.icon.charging = stats.battery, stats.plugged
        self.icon.update()
        self.value.set_text(f"{stats.battery:.0f} %")
        low = stats.battery <= BATTERY_LOW and not stats.plugged
        self.value.set_color(styles.VU_RED if low else None)
        if stats.plugged:
            detail = "sur secteur"
        elif stats.seconds_left:
            detail = f"{format_duration(stats.seconds_left)} restantes"
        else:
            detail = "sur batterie"
        self.setToolTip(f"Batterie : {stats.battery:.0f} % — {detail}")


# --------------------------------------------------------------------------- #
# Météo
# --------------------------------------------------------------------------- #
class WeatherWidget(Pill):
    """Météo de la ville des réglages ; caché tant qu'aucune ville n'est choisie."""

    key = "weather"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self.icon = Icon("cloud", role="TEXT_PRIMARY", size=18)
        self.value = Text("", size=12)
        self.row.addWidget(self.icon)
        self.row.addWidget(self.value)
        self.clicked.connect(ctx.weather.refresh)
        ctx.weather.changed.connect(self._show)
        self._show(ctx.weather.weather)

    def _show(self, weather: Weather | None) -> None:
        self.set_shown(weather is not None)
        if weather is None:
            return
        self.icon.set_icon(weather.icon)
        self.icon.set_color(styles.VU_YELLOW if weather.icon == "sun" else None)
        self.value.set_text(f"{weather.temperature:.0f}°")
        lines = [f"{weather.city} — {weather.description}" if weather.description else weather.city]
        if weather.low is not None and weather.high is not None:
            lines.append(f"Min {weather.low:.0f}° · Max {weather.high:.0f}°")
        if self._ctx.weather.error:
            lines.append(f"Dernière mise à jour impossible : {self._ctx.weather.error}")
        lines.append("Clic : actualiser")
        self.setToolTip("\n".join(lines))

    def menu_actions(self) -> list:
        return [("Actualiser la météo", self._ctx.weather.refresh),
                ("Changer de ville…", lambda: self._ctx.open_settings("widgets"))]


# --------------------------------------------------------------------------- #
# Horloge
# --------------------------------------------------------------------------- #
def clock_texts(time: QTime, date: QDate, seconds: bool, locale: QLocale) -> tuple[str, str]:
    """(heure, date) affichées : « 14:32 », « dim. 15 nov. »."""
    return (time.toString("HH:mm:ss" if seconds else "HH:mm"),
            locale.toString(date, "ddd d MMM"))


class ClockWidget(Pill):
    """Heure et date ; un clic ouvre le calendrier."""

    key = "clock"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._locale = QLocale(QLocale.Language.French)
        options = ctx.widget_cfg("clock")
        self._seconds = bool(options.get("seconds", False))
        self.date = Text("", role="TEXT_SECONDARY", size=12)
        self.time = Text("", size=13, weight=QFont.Weight.DemiBold,
                         min_chars=8 if self._seconds else 5)
        self.row.addWidget(self.date)
        self.row.addWidget(self.time)
        self.date.setVisible(bool(options.get("date", True)))   # une fois dans la pill
        self._popup: Popup | None = None
        self.clicked.connect(self.show_calendar)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self.tick()

    def tick(self) -> None:
        time, date = clock_texts(QTime.currentTime(), QDate.currentDate(), self._seconds,
                                 self._locale)
        self.time.set_text(time)
        self.date.set_text(date)
        self.setToolTip(self._locale.toString(QDate.currentDate(), "dddd d MMMM yyyy"))

    def show_calendar(self) -> None:
        popup = Popup(self.window())
        title = QLabel(self._locale.toString(QDate.currentDate(), "dddd d MMMM yyyy").capitalize())
        title.setObjectName("title")
        calendar = QCalendarWidget()
        calendar.setLocale(self._locale)
        calendar.setGridVisible(False)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
        calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        for name, arrow in (("qt_calendar_prevmonth", "‹"), ("qt_calendar_nextmonth", "›")):
            button = calendar.findChild(QToolButton, name)      # flèches noires de Qt
            if button is not None:
                button.setIcon(QIcon())
                button.setText(arrow)
        popup.body.addWidget(title)
        popup.body.addWidget(calendar)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._popup = popup
        popup.show_near(self)
