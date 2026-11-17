"""
Musique en cours : titre, artiste, pochette, et commandes précédent /
lecture-pause / suivant de l'application qui joue (Spotify, Deezer, un
navigateur…). Ce sont les contrôles média de Windows, lus avec Python/WinRT :
le même lecteur que celui du Master de REKA.

Trois moteurs, même interface :
- WindowsMedia : le vrai ; les appels WinRT bloquent, ils tournent dans un
  thread qui scrute la session en cours toutes les secondes ;
- DemoMedia    : morceaux simulés (--demo, --selftest, tests) ;
- NullMedia    : indisponible (autre système, winrt absent) : widget caché.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

POLL_S = 1.0
AFTER_COMMAND_S = 0.25        # relecture rapide après précédent / pause / suivant
RETRY_S = 3.0
WINRT_TIMEOUT_S = 3.0
COVER_READS = 4               # la pochette arrive souvent un peu après le titre
MAX_COVER_BYTES = 4 * 1024 * 1024
WINRT_MODULES = ("winrt.windows.media.control", "winrt.windows.storage.streams",
                 "winrt.windows.foundation")
PLAYING = 4                   # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
ASYNC_COMPLETED, ASYNC_ERROR = 1, 3

APP_NAMES = {
    "spotify": "Spotify", "deezer": "Deezer", "chrome": "Chrome", "msedge": "Edge",
    "firefox": "Firefox", "308046b0af4a39cb": "Firefox", "opera": "Opera", "brave": "Brave",
    "vivaldi": "Vivaldi", "vlc": "VLC", "itunes": "iTunes", "applemusic": "Apple Music",
    "microsoft.zunemusic": "Lecteur multimédia", "tidal": "TIDAL", "amazon music": "Amazon Music",
    "discord": "Discord",
}


@dataclass(frozen=True)
class MediaInfo:
    title: str
    artist: str = ""
    album: str = ""
    app: str = ""
    playing: bool = False
    can_previous: bool = True
    can_next: bool = True
    can_play_pause: bool = True
    cover: bytes = b""
    position: float = 0.0         # secondes écoulées, au moment `updated`
    duration: float = 0.0         # secondes (0 : inconnue, radio, direct)
    can_seek: bool = False
    updated: float = field(default=0.0, compare=False)    # time.monotonic() de la lecture

    def position_at(self, now: float | None = None) -> float:
        """Position estimée à l'instant `now` (time.monotonic()) : elle avance
        toute seule pendant la lecture, entre deux relevés."""
        position = self.position
        if self.playing:
            now = time.monotonic() if now is None else now
            position += max(0.0, now - self.updated)
        if self.duration > 0:
            position = min(position, self.duration)
        return max(0.0, position)


def format_time(seconds: float) -> str:
    """« 3:07 », « 1:02:45 »."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def to_seconds(value) -> float:
    """Durée WinRT (TimeSpan) en secondes : timedelta, nombre de « ticks » de
    100 ns, ou objet avec un champ `duration`."""
    if value is None:
        return 0.0
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value) / 10_000_000
    ticks = getattr(value, "duration", None)
    return float(ticks) / 10_000_000 if isinstance(ticks, (int, float)) else 0.0


def timeline_position(position: float, start: float, end: float, last_update,
                      playing: bool, now: datetime | None = None) -> tuple[float, float]:
    """(position, durée) d'après la frise de Windows : la position est celle du
    dernier relevé de l'application (`last_update`) ; pendant la lecture, on y
    ajoute le temps écoulé depuis."""
    duration = max(0.0, end - start)
    position -= start
    if playing and isinstance(last_update, datetime):
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
        elapsed = ((now or datetime.now(timezone.utc)) - last_update).total_seconds()
        if 0 < elapsed < 24 * 3600:
            position += elapsed
    if duration > 0:
        position = min(position, duration)
    return max(0.0, position), duration


def app_label(app_id: str) -> str:
    """Nom affiché de l'application d'après son identifiant Windows."""
    name = (app_id or "").split("!")[-1].replace("/", "\\").rsplit("\\", 1)[-1].strip()
    if name.lower().endswith(".exe"):
        name = name[:-4]
    key = name.lower()
    for known, label in APP_NAMES.items():
        if key == known or key.startswith(known):
            return label
    return name


class MediaBackend(QObject):
    """Interface commune : `changed` (MediaInfo, ou None si rien ne joue)."""

    changed = Signal(object)
    available = False

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current: MediaInfo | None = None

    @property
    def current(self) -> MediaInfo | None:
        return self._current

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def play_pause(self) -> None:
        pass

    def next(self) -> None:
        pass

    def previous(self) -> None:
        pass

    def seek(self, seconds: float) -> None:
        """Va à `seconds` dans le morceau (si l'application le permet)."""

    def _publish(self, info: MediaInfo | None) -> None:
        if info == self._current or same_track_on_time(self._current, info):
            return
        self._current = info
        self.changed.emit(info)


DRIFT_S = 1.5                 # écart toléré entre la position estimée et la position lue


def same_track_on_time(old: MediaInfo | None, new: MediaInfo | None) -> bool:
    """Rien n'a changé sauf la position, qui avance comme prévu : inutile de
    tout redessiner à chaque relevé (la barre fait avancer la frise seule)."""
    if old is None or new is None or replace(old, position=0.0) != replace(new, position=0.0):
        return False
    now = time.monotonic()
    return abs(old.position_at(now) - new.position_at(now)) < DRIFT_S


class NullMedia(MediaBackend):
    def __init__(self, reason: str = "Disponible sous Windows seulement.",
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.reason = reason


class DemoMedia(MediaBackend):
    """Quelques morceaux simulés (les mêmes que la démo de REKA)."""

    available = True
    TRACKS = (
        ("Néons de minuit", "Les Ondes", "Nuit blanche", "Spotify", "#3b82f6", "#a66bff"),
        ("Ligne de basse", "Studio 206", "Sessions", "Deezer", "#ff4fb8", "#ff9a1f"),
        ("Retour au calme", "Regrettable", "REKA", "Chrome", "#00e5ff", "#00ff88"),
    )
    DURATIONS = (214.0, 187.0, 243.0)
    START_AT = 71.0               # la démo démarre en cours de morceau

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._index = 0
        self._playing = True
        self._position = self.START_AT
        self._since = time.monotonic()
        self._covers: dict[int, bytes] = {}

    def start(self) -> None:
        self._emit()

    def _elapsed(self) -> float:
        position = self._position + (time.monotonic() - self._since if self._playing else 0.0)
        return min(position, self.DURATIONS[self._index])

    def play_pause(self) -> None:
        self._position, self._since = self._elapsed(), time.monotonic()
        self._playing = not self._playing
        self._emit()

    def next(self) -> None:
        self._index = (self._index + 1) % len(self.TRACKS)
        self._position, self._since = 0.0, time.monotonic()
        self._emit()

    def previous(self) -> None:
        self._index = (self._index - 1) % len(self.TRACKS)
        self._position, self._since = 0.0, time.monotonic()
        self._emit()

    def seek(self, seconds: float) -> None:
        self._position = max(0.0, min(float(seconds), self.DURATIONS[self._index]))
        self._since = time.monotonic()
        self._emit()

    def _emit(self) -> None:
        title, artist, album, app, _a, _b = self.TRACKS[self._index]
        self._publish(MediaInfo(title, artist, album, app, self._playing, cover=self._cover(),
                                position=self._elapsed(), duration=self.DURATIONS[self._index],
                                can_seek=True, updated=time.monotonic()))

    def _cover(self) -> bytes:
        if self._index not in self._covers:
            from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
            from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

            title, _artist, _album, _app, start, end = self.TRACKS[self._index]
            image = QImage(96, 96, QImage.Format.Format_RGB32)
            painter = QPainter(image)
            gradient = QLinearGradient(0, 0, 96, 96)
            gradient.setColorAt(0.0, QColor(start))
            gradient.setColorAt(1.0, QColor(end))
            painter.fillRect(image.rect(), gradient)
            font = QFont()
            font.setPixelSize(40)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 220))
            initials = "".join(word[0] for word in title.split()[:3] if word[0].isupper()) or title[0]
            painter.drawText(QRectF(0, 0, 96, 96), Qt.AlignmentFlag.AlignCenter, initials[:2])
            painter.end()
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            self._covers[self._index] = bytes(buffer.data())
        return self._covers[self._index]


# --------------------------------------------------------------------------- #
# Windows : contrôles média du système (WinRT)
# --------------------------------------------------------------------------- #
def winrt_wait(operation, timeout: float = WINRT_TIMEOUT_S):
    """Résultat d'une opération asynchrone WinRT, en bloquant au plus `timeout` s."""
    waiter = getattr(operation, "wait", None)
    if waiter is not None:
        status = int(waiter(timeout))
    else:
        deadline = time.monotonic() + timeout
        while int(operation.status) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        status = int(operation.status)
    if status not in (ASYNC_COMPLETED, ASYNC_ERROR):
        with contextlib.suppress(Exception):
            operation.cancel()
        raise TimeoutError("Windows ne répond pas (contrôles média)")
    return operation.get_results()


def run_in_mta(function, timeout: float = 2 * WINRT_TIMEOUT_S):
    """Exécute `function()` dans un thread WinRT (appartement multithread)."""
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            from winrt import runtime

            with contextlib.suppress(Exception):
                runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
            outcome["result"] = function()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=target, name="winrt-call", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError("Windows ne répond pas (contrôles média)")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("result")


def probe_media_controls() -> str:
    """Les contrôles média de Windows répondent-ils ? (auto-test de l'exe)"""
    def probe() -> str:
        from winrt.windows.media.control import \
            GlobalSystemMediaTransportControlsSessionManager as Manager

        session = winrt_wait(Manager.request_async()).get_current_session()
        return "une session en cours" if session is not None else "aucune session en cours"

    return run_in_mta(probe)


def read_cover(reference) -> bytes:
    if reference is None:
        return b""
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    stream = winrt_wait(reference.open_read_async())
    try:
        size = int(stream.size)
        if size <= 0 or size > MAX_COVER_BYTES:
            return b""
        buffer = Buffer(size)
        result = winrt_wait(stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD))
        return bytes(memoryview(result))[: int(result.length)]
    finally:
        with contextlib.suppress(Exception):
            stream.close()


class WindowsMedia(MediaBackend):
    available = True

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._commands: list[tuple[str, float]] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="media-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=WINRT_TIMEOUT_S + 1)
            self._thread = None

    def play_pause(self) -> None:
        self._command("play_pause")

    def next(self) -> None:
        self._command("next")

    def previous(self) -> None:
        self._command("previous")

    def seek(self, seconds: float) -> None:
        self._command("seek", seconds)

    def _command(self, name: str, value: float = 0.0) -> None:
        with self._lock:
            if name == "seek":          # seul le dernier saut compte (curseur glissé)
                self._commands = [c for c in self._commands if c[0] != "seek"]
            self._commands.append((name, value))
        self._wake.set()

    def _run(self) -> None:
        try:
            from winrt import runtime

            with contextlib.suppress(Exception):
                runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
            from winrt.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as Manager
        except Exception as exc:
            log.warning("Musique en cours indisponible (WinRT) : %s", exc)
            return
        manager = None
        cover_key, cover, cover_reads = None, b"", 0
        failing = False
        while not self._stop.is_set():
            delay = POLL_S
            try:
                if manager is None:
                    manager = winrt_wait(Manager.request_async())
                session = manager.get_current_session()
                if self._run_commands(session):
                    delay = AFTER_COMMAND_S
                info, thumbnail = self._read(session)
                key = None if info is None else (info.app, info.title, info.artist, info.album)
                if key != cover_key:
                    cover_key, cover, cover_reads = key, b"", COVER_READS
                if info is not None and cover_reads > 0:
                    cover_reads -= 1
                    with contextlib.suppress(Exception):
                        cover = read_cover(thumbnail) or cover
                self._publish(None if info is None else replace(info, cover=cover))
                failing = False
            except Exception as exc:
                if not failing:
                    log.warning("Contrôles média de Windows injoignables : %s", exc)
                failing, manager, delay = True, None, RETRY_S
            self._wake.wait(delay)
            self._wake.clear()

    def _run_commands(self, session) -> bool:
        with self._lock:
            commands, self._commands = self._commands, []
        if session is None:
            return False
        actions = {"play_pause": lambda _v: session.try_toggle_play_pause_async(),
                   "next": lambda _v: session.try_skip_next_async(),
                   "previous": lambda _v: session.try_skip_previous_async(),
                   "seek": lambda v: session.try_change_playback_position_async(
                       int(max(0.0, v) * 10_000_000))}
        for name, value in commands:
            try:
                winrt_wait(actions[name](value))
            except Exception as exc:
                log.warning("Commande média « %s » refusée : %s", name, exc)
        return bool(commands)

    @staticmethod
    def _read(session) -> tuple[MediaInfo | None, object]:
        if session is None:
            return None, None
        props = winrt_wait(session.try_get_media_properties_async())
        title = str(getattr(props, "title", "") or "").strip()
        if props is None or not title:
            return None, None
        playback = session.get_playback_info()
        controls = getattr(playback, "controls", None)

        def enabled(name: str) -> bool:
            return bool(getattr(controls, name, True)) if controls is not None else True

        status = getattr(playback, "playback_status", 0)
        playing = int(status) == PLAYING
        position = duration = 0.0
        try:
            timeline = session.get_timeline_properties()
            rate = getattr(playback, "playback_rate", None)
            position, duration = timeline_position(
                to_seconds(timeline.position), to_seconds(timeline.start_time),
                to_seconds(timeline.end_time), getattr(timeline, "last_updated_time", None),
                playing and (rate is None or float(rate or 0) > 0))
        except Exception as exc:          # frise absente (radio, direct, vieille application)
            log.debug("Frise du morceau illisible : %s", exc)
        info = MediaInfo(
            title=title,
            artist=str(props.artist or "").strip(),
            album=str(props.album_title or "").strip(),
            app=app_label(str(session.source_app_user_model_id or "")),
            playing=playing,
            can_previous=enabled("is_previous_enabled"),
            can_next=enabled("is_next_enabled"),
            can_play_pause=enabled("is_play_pause_toggle_enabled"),
            position=position,
            duration=duration,
            can_seek=duration > 0 and enabled("is_playback_position_enabled"),
            updated=time.monotonic(),
        )
        return info, props.thumbnail


def create_media_backend() -> MediaBackend:
    """Le moteur réel sous Windows, sinon un moteur indisponible (jamais d'exception)."""
    if sys.platform != "win32":
        return NullMedia()
    try:
        missing = [name for name in WINRT_MODULES if importlib.util.find_spec(name) is None]
    except (ImportError, ValueError) as exc:
        missing = [str(exc)]
    if missing:
        log.warning("Musique en cours indisponible : modules absents (%s).", ", ".join(missing))
        return NullMedia("Modules Windows (winrt) absents.")
    return WindowsMedia()
