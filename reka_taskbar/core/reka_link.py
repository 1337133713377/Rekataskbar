"""
Lien avec REKA, la console de mixage (https://github.com/1337133713377/reka).

La barre ne modifie jamais REKA ; elle s'y raccorde par trois chemins :

1. Sa config, %APPDATA%/REKA/config.json, relue dès qu'elle change : édition
   de Voicemeeter, correspondance des strips, noms des canaux, knobs de
   routing, bus du casque, thème et couleurs. La barre affiche donc les mêmes
   canaux, dans le même ordre, aux mêmes couleurs que la console.
2. Voicemeeter, que REKA pilote aussi : un Muet ou un volume réglé depuis la
   barre apparaît aussitôt dans REKA, et l'inverse (voir core/voicemeeter.py).
3. Le canal local « REKA-<utilisateur>-show » que REKA ouvre pour ses propres
   relances : s'y connecter affiche la fenêtre de la console.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QDir, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

from core import config

log = logging.getLogger(__name__)

REKA_NAME = "REKA"
REKA_EXE = "REKA.exe"
REKA_DOWNLOAD_URL = "https://github.com/1337133713377/reka/releases/latest/download/REKA.exe"
REKA_PAGE_URL = "https://github.com/1337133713377/reka"
WATCH_MS = 2000               # relecture de la config et de l'état de REKA
SHOW_TIMEOUT_MS = 1200


@dataclass(frozen=True)
class Edition:
    """Ce qui change d'une édition de Voicemeeter à l'autre (comme dans REKA)."""

    kind: str
    label: str
    physical_strips: int
    virtual_strips: int
    buses: tuple[str, ...]
    default_strip_map: tuple[int, ...]

    @property
    def strip_count(self) -> int:
        return self.physical_strips + self.virtual_strips


EDITIONS = {
    "potato": Edition("potato", "Voicemeeter Potato", 5, 3,
                      ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3"), (0, 1, 5, 6, 2, 7)),
    "banana": Edition("banana", "Voicemeeter Banana", 3, 2,
                      ("A1", "A2", "A3", "B1", "B2"), (0, 1, 3, 4, 2)),
    # REKA ne gère pas l'édition standard ; la barre en montre quand même les entrées
    "basic": Edition("basic", "Voicemeeter", 2, 1, ("A", "B"), (0, 1, 2)),
}
DEFAULT_KIND = "potato"
DEFAULT_NAMES = ("Microphone", "Musique", "Appels", "Bureau", "Autres 1", "Autres 2")
DEFAULT_ROUTING = (("Monitor", "A1"), ("Mic Out", "B1"), ("Discord", "B2"), ("Obs", "A2"))


@dataclass(frozen=True)
class RekaSetup:
    """Ce que la barre reprend de la config de REKA."""

    found: bool = False                              # config de REKA trouvée et lisible
    kind: str = DEFAULT_KIND
    strips: tuple[int, ...] = EDITIONS[DEFAULT_KIND].default_strip_map
    names: tuple[str, ...] = DEFAULT_NAMES
    routes: tuple[tuple[str, str], ...] = DEFAULT_ROUTING   # (nom du knob, bus)
    headphone_bus: str = "A1"
    mic_strip: int = 0                               # canal du micro (synchro Discord de REKA)
    theme: str = "studio"
    colors: dict = field(default_factory=dict, hash=False)
    font_family: str = ""

    @property
    def edition(self) -> Edition:
        return EDITIONS[self.kind]

    def name(self, index: int) -> str:
        if 0 <= index < len(self.names) and self.names[index].strip():
            return self.names[index].strip()
        return f"Canal {index + 1}"

    def for_kind(self, kind: str) -> "RekaSetup":
        """Même réglage, adapté à l'édition de Voicemeeter qui tourne vraiment
        (REKA réglée sur Potato alors que Banana est lancé, par exemple)."""
        if kind == self.kind or kind not in EDITIONS:
            return self
        ed = EDITIONS[kind]
        routes = tuple(r for r in self.routes if r[1] in ed.buses)
        return RekaSetup(found=self.found, kind=kind, strips=ed.default_strip_map,
                         names=self.names, routes=routes,
                         headphone_bus=self.headphone_bus if self.headphone_bus in ed.buses
                         else ed.buses[0],
                         mic_strip=min(self.mic_strip, len(ed.default_strip_map) - 1),
                         theme=self.theme, colors=self.colors, font_family=self.font_family)


# --------------------------------------------------------------------------- #
# Lecture de la config de REKA
# --------------------------------------------------------------------------- #
def reka_data_dir() -> Path:
    return config.roaming_dir() / REKA_NAME


def reka_config_path(cfg: dict) -> Path:
    """Config de REKA : celle indiquée dans les réglages, sinon %APPDATA%/REKA."""
    custom = str(cfg.get("reka", {}).get("config_path") or "").strip()
    if custom:
        path = Path(os.path.expandvars(os.path.expanduser(custom)))
        return path / config.CONFIG_FILENAME if path.is_dir() else path
    return reka_data_dir() / config.CONFIG_FILENAME


def parse_setup(data: dict) -> RekaSetup:
    """Interprète un config.json de REKA ; chaque valeur absente ou invalide
    retombe sur celle par défaut de REKA."""
    vm = data.get("voicemeeter") if isinstance(data.get("voicemeeter"), dict) else {}
    ui = data.get("ui") if isinstance(data.get("ui"), dict) else {}
    discord = data.get("discord") if isinstance(data.get("discord"), dict) else {}

    kind = str(vm.get("kind", DEFAULT_KIND)).lower()
    if kind not in ("potato", "banana"):
        kind = DEFAULT_KIND
    ed = EDITIONS[kind]

    maps = vm.get("strip_maps") if isinstance(vm.get("strip_maps"), dict) else {}
    try:
        strips = tuple(int(s) for s in (maps.get(kind) or ed.default_strip_map))
    except (TypeError, ValueError):
        strips = ed.default_strip_map
    strips = tuple(s for s in strips if 0 <= s < ed.strip_count) or ed.default_strip_map

    raw_names = ui.get("strip_names") if isinstance(ui.get("strip_names"), list) else []
    names = tuple(str(raw_names[i]) if i < len(raw_names) and str(raw_names[i]).strip()
                  else (DEFAULT_NAMES[i] if i < len(DEFAULT_NAMES) else f"Canal {i + 1}")
                  for i in range(len(strips)))

    routes = []
    raw_routes = vm.get("routing") if isinstance(vm.get("routing"), list) else None
    if raw_routes is None:
        raw_routes = [{"label": label, "bus": bus} for label, bus in DEFAULT_ROUTING]
    for n, route in enumerate(raw_routes):
        if not isinstance(route, dict):
            continue
        bus = str(route.get("bus", "")).upper()
        if bus not in ed.buses:      # même repli que REKA
            bus = DEFAULT_ROUTING[n][1] if n < len(DEFAULT_ROUTING) else "A1"
        routes.append((str(route.get("label") or bus), bus))

    headphone = str(vm.get("headphone_bus", "A1")).upper()
    if headphone not in ed.buses:
        headphone = "A1"
    try:
        mic = int(discord.get("mute_strip", 0))
    except (TypeError, ValueError):
        mic = 0
    colors = ui.get("colors") if isinstance(ui.get("colors"), dict) else {}
    return RekaSetup(found=True, kind=kind, strips=strips, names=names, routes=tuple(routes),
                     headphone_bus=headphone, mic_strip=max(0, min(mic, len(strips) - 1)),
                     theme=str(ui.get("theme") or "studio"),
                     colors={str(k): str(v) for k, v in colors.items()},
                     font_family=str(ui.get("font_family") or ""))


def read_setup(path: Path) -> RekaSetup:
    """Réglages de REKA ; ceux par défaut si REKA n'a jamais été lancée ici."""
    try:
        return parse_setup(config.read_json(path))
    except FileNotFoundError:
        return RekaSetup()
    except (OSError, ValueError) as exc:
        # REKA écrit sa config de façon atomique : un échec est une vraie anomalie
        log.warning("Config de REKA illisible (%s) : réglages par défaut.", exc)
        return RekaSetup()


# --------------------------------------------------------------------------- #
# REKA tourne-t-elle ? L'afficher, la lancer
# --------------------------------------------------------------------------- #
def instance_name() -> str:
    """Nom du canal local de REKA (voir _instance_name() dans son main.py)."""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"{REKA_NAME}-{user}-show"


def is_reka_running() -> bool:
    """REKA écoute-t-elle sur son canal ? Sans s'y connecter : une connexion
    vaut demande d'affichage, la console surgirait toutes les 2 secondes."""
    name = instance_name()
    if sys.platform == "win32":
        try:      # les tubes nommés se listent comme un dossier, sans les ouvrir
            return name in os.listdir("\\\\.\\pipe\\")
        except OSError as exc:
            log.debug("Tubes nommés illisibles (%s) : recherche du processus.", exc)
            return find_reka_exe() is not None
    return (Path(QDir.tempPath()) / name).exists()


def find_reka_exe() -> Path | None:
    """Chemin du REKA.exe en cours d'exécution, None s'il ne tourne pas."""
    try:
        import psutil
    except ImportError:
        return None
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if (process.info.get("name") or "").lower() == REKA_EXE.lower():
                exe = process.info.get("exe")
                return Path(exe) if exe else None
        except psutil.Error:
            continue
    return None


def request_show(timeout_ms: int = SHOW_TIMEOUT_MS) -> bool:
    """Demande à REKA d'afficher sa console ; True si elle a répondu « ok »."""
    if sys.platform == "win32":
        # Windows ne laisse passer une fenêtre au premier plan que si le
        # processus qui a reçu le clic (la barre) l'autorise
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
        except (AttributeError, OSError):
            pass
    socket = QLocalSocket()
    socket.connectToServer(instance_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(b"show\n")
    socket.waitForBytesWritten(timeout_ms)
    reply = bytes(socket.readAll())
    waited = 0
    while b"\n" not in reply and waited < timeout_ms:
        socket.waitForReadyRead(100)
        waited += 100
        reply += bytes(socket.readAll())
        if (socket.state() == QLocalSocket.LocalSocketState.UnconnectedState
                and not socket.bytesAvailable()):
            break
    socket.abort()
    return reply.startswith(b"ok")


class RekaLink(QObject):
    """Surveille REKA : ses réglages (setup_changed) et sa présence
    (running_changed)."""

    setup_changed = Signal(object)       # RekaSetup
    running_changed = Signal(bool)

    def __init__(self, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._path = reka_config_path(cfg)
        self._stamp: tuple[float, int] | None = None
        self._setup = RekaSetup()
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(WATCH_MS)
        self._timer.timeout.connect(self.refresh)
        self._load()

    # ------------------------------------------------------------------ état
    @property
    def setup(self) -> RekaSetup:
        return self._setup

    @property
    def running(self) -> bool:
        return self._running

    @property
    def config_path(self) -> Path:
        return self._path

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        path = reka_config_path(self._cfg)
        if path != self._path:           # chemin changé dans les réglages
            self._path, self._stamp = path, None
        if self._file_stamp() != self._stamp:
            previous = self._setup
            self._load()
            if self._setup != previous:
                log.info("Réglages de REKA relus (%s, %d canaux, thème %s).",
                         self._setup.kind, len(self._setup.strips), self._setup.theme)
                self.setup_changed.emit(self._setup)
        running = self._probe_running()
        if running != self._running:
            self._running = running
            log.info("REKA %s.", "ouverte" if running else "fermée")
            if running:
                self._remember_exe()
            self.running_changed.emit(running)

    def _probe_running(self) -> bool:
        return is_reka_running()

    def _file_stamp(self) -> tuple[float, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return stat.st_mtime, stat.st_size

    def _load(self) -> None:
        self._stamp = self._file_stamp()
        self._setup = read_setup(self._path)

    # ------------------------------------------------------------- commandes
    def exe_path(self) -> Path | None:
        """REKA.exe : celui des réglages, sinon le dernier vu en cours d'exécution."""
        value = str(self._cfg.get("reka", {}).get("exe_path") or "").strip()
        if value:
            path = Path(os.path.expandvars(os.path.expanduser(value)))
            if path.is_file():
                return path
        return None

    def _remember_exe(self) -> None:
        if self.exe_path() is not None:
            return
        exe = find_reka_exe()
        if exe is not None and exe.is_file():
            self._cfg.setdefault("reka", {})["exe_path"] = str(exe)
            config.save_quietly(self._cfg)
            log.info("REKA.exe repéré : %s", exe)

    def show(self) -> bool:
        """Affiche la console (True si REKA a répondu)."""
        return request_show()

    def launch(self) -> bool:
        """Lance REKA.exe ; False si on ne sait pas où il est."""
        exe = self.exe_path()
        if exe is None:
            return False
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
        except OSError as exc:
            log.warning("REKA non lancée (%s) : %s", exe, exc)
            return False
        log.info("REKA lancée : %s", exe)
        return True

    def show_or_launch(self) -> str:
        """« shown », « launched » ou « missing » (REKA.exe introuvable)."""
        if self.show():
            return "shown"
        return "launched" if self.launch() else "missing"
