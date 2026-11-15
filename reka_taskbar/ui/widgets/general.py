"""
Widgets d'usage courant : Démarrer, raccourcis, musique en cours, processeur
et mémoire, réseau, météo, batterie, horloge et calendrier.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QLocale, QRectF, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QCalendarWidget, QLabel, QToolButton, QWidget

from core import shell
from core.media import MediaInfo
from core.system import SystemStats, format_bytes, format_duration, format_rate
from core.weather import Weather
from ui import icons, styles
from ui.popup import Popup
from ui.widgets.appicon import app_pixmap
from ui.widgets.base import Context, Icon, IconButton, Pill, Text

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
class CoverArt(QWidget):
    SIZE = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_cover(self, data: bytes) -> None:
        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data)
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 5, 5)
        painter.setClipPath(clip)
        if self._pixmap.isNull():
            painter.fillRect(rect, QColor(styles.BUTTON_BG))
            icons.draw(painter, "music", rect.adjusted(5, 5, -5, -5),
                       styles.accent("media", styles.MASTER_SCOPE))
            return
        side = min(self._pixmap.width(), self._pixmap.height())      # recadrage carré, centré
        source = QRectF((self._pixmap.width() - side) / 2, (self._pixmap.height() - side) / 2,
                        side, side)
        painter.drawPixmap(rect, self._pixmap, source)


class MediaWidget(Pill):
    """Le morceau en cours (Spotify, Deezer, navigateur…) et ses commandes."""

    key = "media"
    MAX_TEXT = 240

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._media = ctx.media
        self.row.setContentsMargins(5, 0, 5, 0)
        self.cover = CoverArt()
        self.title = Text("", size=12, weight=QFont.Weight.Medium, max_width=self.MAX_TEXT)
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
        self._media.changed.connect(self._show)
        self._show(self._media.current)

    def _show(self, info: MediaInfo | None) -> None:
        self.set_shown(info is not None)
        if info is None:
            return
        self.title.set_text(f"{info.title} — {info.artist}" if info.artist else info.title)
        self.cover.set_cover(info.cover)
        self.play.set_icon("pause" if info.playing else "play")
        self.previous.setEnabled(info.can_previous)
        self.next.setEnabled(info.can_next)
        self.play.setEnabled(info.can_play_pause)
        details = [info.title, info.artist, info.album]
        self.setToolTip("\n".join(d for d in details if d)
                        + (f"\n{info.app}" if info.app else ""))
        self.updateGeometry()


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
