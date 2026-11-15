"""
Mises à jour automatiques de REKA Taskbar (même principe que REKA).

Chaque release GitHub (tag « v1.2.3 ») publie, à côté de REKA-Taskbar.exe, un
`version.json` qui décrit cet exe : version, adresse, taille, empreinte
SHA-256 et nouveautés. L'exe embarque `build_info.json` (sa version et le
dépôt) : il sait donc où regarder.

- La barre lit le version.json de la dernière release (au démarrage, puis
  toutes les quelques heures).
- Si la version en ligne est plus récente, elle télécharge l'exe en arrière-
  plan et vérifie taille et empreinte.
- Puis elle le met à la place de l'exe en cours : Windows interdit d'écraser un
  exe qui tourne, mais permet de le renommer (REKA-Taskbar.exe →
  REKA-Taskbar.old.exe). La barre redémarre sur le nouvel exe, qui supprime
  l'ancien.

Le remplacement et le redémarrage passent par le gardien (core/update_guard.py) :
il lance la nouvelle version depuis l'ancien exe et revient à l'ancienne si la
nouvelle ne démarre pas.

Avec l'installation automatique désactivée (ou si l'exe est dans un dossier
protégé), un bouton « Mise à jour » apparaît dans la barre à la place. Pendant
un téléchargement automatique, la barre en montre la progression.

En développement (python main.py), pas de build_info.json : pas de vérification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from core import config, update_guard
from core.update_guard import UpdateError, update_dir

# Opérations sur les fichiers : dans le garde (sans Qt), réexportées ici
install = update_guard.install
cleanup_previous = update_guard.cleanup_previous
old_exe_path = update_guard.old_exe_path

log = logging.getLogger(__name__)

BUILD_INFO_FILE = "build_info.json"
VERSION_FILE = "version.json"
EXE_NAME = "REKA-Taskbar.exe"
FETCH_TIMEOUT_S = 10.0
DOWNLOAD_TIMEOUT_S = 30.0
CHUNK = 64 * 1024
MAX_VERSION_FILE = 64 * 1024
START_DELAY_S = 20              # première vérification : une fois la session bien lancée
MIN_INTERVAL_H = 1.0
DEFAULT_INTERVAL_H = 3.0
BUSY_RETRY_MS = 60_000          # menu, réglages ou jeu plein écran : on redémarre plus tard
# Vérification ratée (pas encore de réseau au démarrage…) : nouvel essai bien
# avant la vérification régulière
CHECK_RETRY_MS = (5 * 60_000, 15 * 60_000, 30 * 60_000, 60 * 60_000)
DOWNLOAD_RETRY_MS = 10 * 60_000
DOWNLOAD_ATTEMPTS = 3
LOOPBACK = ("http://127.0.0.1:", "http://localhost:")   # serveur local (tests de bout en bout)


@dataclass(frozen=True)
class BuildInfo:
    version: str
    repo: str          # « owner/dépôt » GitHub
    commit: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str           # REKA-Taskbar.exe en ligne
    sha256: str
    size: int
    notes: str = ""
    published: str = ""


def version_key(version: str) -> tuple[int, ...]:
    """« 1.10.2 » → (1, 10, 2) : se compare dans le bon ordre (1.10 > 1.9)."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", str(version))[:4])
    return numbers + (0,) * (3 - len(numbers)) if len(numbers) < 3 else numbers


def is_newer(update: UpdateInfo, current: str, skipped: str = "") -> bool:
    """La version en ligne est-elle plus récente que `current` (et pas ignorée) ?"""
    if skipped and version_key(update.version) == version_key(skipped):
        return False
    return version_key(update.version) > version_key(current)


def load_build_info(path: Path | None = None) -> BuildInfo | None:
    """Infos du build en cours, embarquées par le build GitHub ; None en développement."""
    path = path or config.resource_path(BUILD_INFO_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BuildInfo(str(data["version"]), str(data["repo"]), str(data.get("commit", "")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("build_info.json illisible : %s", exc)
        return None


def version_url(cfg: dict, build: BuildInfo | None) -> str | None:
    """Adresse du version.json à consulter : update.url, sinon celui de la
    dernière release du dépôt du build."""
    custom = str(cfg.get("update", {}).get("url", "") or "").strip()
    if custom:
        return custom
    if build is None or not build.repo:
        return None
    return f"https://github.com/{build.repo}/releases/latest/download/{VERSION_FILE}"


def parse_update(data: dict) -> UpdateInfo:
    try:
        update = UpdateInfo(str(data["version"]), str(data["url"]), str(data["sha256"]).lower(),
                            int(data["size"]), str(data.get("notes", "")),
                            str(data.get("published", "")))
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError(f"Description de la mise à jour invalide ({exc}).") from exc
    secure = update.url.lower().startswith("https://") or update.url.startswith(LOOPBACK)
    if (not secure or len(update.sha256) != 64
            or any(c not in "0123456789abcdef" for c in update.sha256) or update.size <= 0):
        raise UpdateError("Description de la mise à jour invalide (adresse, empreinte ou taille).")
    return update


def _open(url: str, timeout: float):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"REKA-Taskbar/{config.APP_VERSION}",
        "Cache-Control": "no-cache",
    })
    return urllib.request.build_opener().open(request, timeout=timeout)


def fetch_update(url: str, timeout: float = FETCH_TIMEOUT_S) -> UpdateInfo:
    """Lit le version.json en ligne. Lève UpdateError (réseau, format)."""
    try:
        with _open(url, timeout) as response:
            raw = response.read(MAX_VERSION_FILE + 1)
    except Exception as exc:
        raise UpdateError(f"Impossible de joindre le serveur de mises à jour ({exc}).") from exc
    if len(raw) > MAX_VERSION_FILE:
        raise UpdateError("Description de la mise à jour trop grande.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError("Description de la mise à jour illisible.") from exc
    if not isinstance(data, dict):
        raise UpdateError("Description de la mise à jour invalide.")
    return parse_update(data)


def download(update: UpdateInfo, dest: Path,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Télécharge l'exe dans `dest` et vérifie taille + SHA-256. Lève UpdateError."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    digest, received = hashlib.sha256(), 0
    try:
        with _open(update.url, DOWNLOAD_TIMEOUT_S) as response, open(partial, "wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("Téléchargement annulé.")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                received += len(chunk)
                if received > update.size:
                    raise UpdateError("Fichier téléchargé plus gros que prévu.")
                digest.update(chunk)
                out.write(chunk)
                if progress is not None:
                    progress(received, update.size)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Téléchargement interrompu ({exc}).") from exc
    if received != update.size or digest.hexdigest() != update.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("Le fichier téléchargé est incomplet ou abîmé : réessaie.")
    os.replace(partial, dest)
    return dest


def can_self_update() -> bool:
    """Remplacement automatique possible : exe PyInstaller (pas en développement)."""
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).suffix.lower() == ".exe"


def launch_restart(previous_version: str, new_version: str = "",
                   executable: Path | None = None) -> bool:
    """Redémarre sur le nouvel exe (déjà installé) ; l'appelant quitte ensuite.

    Le gardien, lancé depuis l'ancien exe, démarre la nouvelle version et la
    surveille ; s'il ne peut pas partir, la nouvelle version est lancée
    directement (sans retour en arrière possible)."""
    exe = executable or Path(sys.executable)
    if new_version and update_guard.start_watched_restart(previous_version, new_version, exe):
        return True
    try:
        update_guard.launch(exe, ["--restart", "--updated-from", previous_version])
    except OSError as exc:
        log.error("Impossible de relancer la barre (%s) : %s", exe, exc)
        return False
    return True


# --------------------------------------------------------------------------- #
# Vérification et installation en arrière-plan
# --------------------------------------------------------------------------- #
STATE_IDLE = "idle"                 # rien à signaler
STATE_CHECKING = "checking"
STATE_DOWNLOADING = "downloading"
STATE_READY = "ready"               # téléchargée et vérifiée, prête à être installée
STATE_AVAILABLE = "available"       # à installer à la main (bouton « Mise à jour »)


class UpdateManager(QObject):
    """Vérifie, télécharge et propose (ou installe) les mises à jour.

    - `available` : une version plus récente est à installer à la main (UpdateInfo) ;
    - `progress` : avancement du téléchargement automatique (pourcentage) ;
    - `ready` : l'exe est téléchargé et vérifié (UpdateInfo, Path) : à
      installer dès que l'utilisateur ne se sert pas de la barre ;
    - `checked` : fin d'une vérification (UpdateInfo ou None, message d'erreur).
    """

    available = Signal(object)
    ready = Signal(object, object)
    progress = Signal(int)
    checked = Signal(object, str)
    state_changed = Signal(str)
    _fetched = Signal(object, str, bool)      # (UpdateInfo | None, erreur, manuelle)
    _downloaded = Signal(object, object, str)  # (UpdateInfo, Path | None, erreur)
    _progressed = Signal(int)

    def __init__(self, cfg: dict, build: BuildInfo | None,
                 fetch: Callable[[str], UpdateInfo] = fetch_update,
                 fetch_exe: Callable[..., Path] = download,
                 self_update: bool | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.build = build
        self._fetch = fetch
        self._fetch_exe = fetch_exe
        self.self_update = can_self_update() if self_update is None else self_update
        self.latest: UpdateInfo | None = None
        self.ready_path: Path | None = None
        self.percent = 0
        self.error = ""
        self._state = STATE_IDLE
        self._busy = threading.Lock()
        self._check_failures = 0
        self._download_attempts = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.check(False))
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(lambda: self.check(False))
        self._fetched.connect(self._on_fetched)
        self._downloaded.connect(self._on_downloaded)
        self._progressed.connect(self._on_progress)

    # ------------------------------------------------------------------ état
    @property
    def enabled(self) -> bool:
        return self.build is not None and version_url(self._cfg, self.build) is not None

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_version(self) -> str:
        return self.build.version if self.build is not None else config.APP_VERSION

    @property
    def auto_install(self) -> bool:
        return bool(self._section().get("auto_install", True)) and self.self_update

    def _section(self) -> dict:
        section = self._cfg.get("update")
        return section if isinstance(section, dict) else {}

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def start(self) -> None:
        """Vérification au démarrage (un peu différée) puis régulière."""
        section = self._section()
        if not self.enabled or not section.get("check", True):
            return
        try:
            hours = max(MIN_INTERVAL_H, float(section.get("interval_hours", DEFAULT_INTERVAL_H)))
        except (TypeError, ValueError):
            hours = DEFAULT_INTERVAL_H
        try:
            first = max(1.0, float(section.get("first_check_s", START_DELAY_S)))
        except (TypeError, ValueError):
            first = float(START_DELAY_S)
        self._timer.start(round(hours * 3_600_000))
        QTimer.singleShot(round(first * 1000), lambda: self.check(False))

    def stop(self) -> None:
        self._timer.stop()
        self._retry.stop()

    # ---------------------------------------------------------- vérification
    def check(self, manual: bool = False) -> bool:
        """Lance une vérification ; False si impossible (développement) ou déjà
        en cours. `manual` : demandée par l'utilisateur (une version ignorée
        est quand même proposée, et le résultat est annoncé via `checked`)."""
        url = version_url(self._cfg, self.build)
        if url is None or self.build is None or self._state in (STATE_DOWNLOADING, STATE_READY):
            return False
        if not self._busy.acquire(blocking=False):
            return False
        self._retry.stop()
        self._set_state(STATE_CHECKING)

        def work() -> None:
            try:
                update, error = self._fetch(url), ""
            except UpdateError as exc:
                update, error = None, str(exc)
            except Exception as exc:        # jamais d'exception perdue dans un thread
                update, error = None, f"Erreur inattendue ({exc})."
            finally:
                self._busy.release()
            try:
                self._fetched.emit(update, error, manual)
            except RuntimeError:            # application fermée entre-temps
                pass

        threading.Thread(target=work, name="update-check", daemon=True).start()
        return True

    def _on_fetched(self, update: UpdateInfo | None, error: str, manual: bool) -> None:
        if update is None:
            self.error = error
            delay = CHECK_RETRY_MS[min(self._check_failures, len(CHECK_RETRY_MS) - 1)]
            self._check_failures += 1
            log.info("Vérification des mises à jour : %s (nouvel essai dans %d min)",
                     error, delay // 60_000)
            self._retry.start(delay)
            self._set_state(STATE_AVAILABLE if self.latest is not None else STATE_IDLE)
            self.checked.emit(None, error)
            return
        self.error = ""
        self._check_failures = 0
        skipped = "" if manual else str(self._section().get("skipped_version") or "")
        if not is_newer(update, self.current_version, skipped):
            self._set_state(STATE_AVAILABLE if self.latest is not None else STATE_IDLE)
            self.checked.emit(None, "")
            return
        log.info("Mise à jour disponible : %s (en cours : %s)", update.version,
                 self.current_version)
        if self.latest is None or self.latest.version != update.version:
            self._download_attempts = 0
        self.latest = update
        self.checked.emit(update, "")
        if self.auto_install and not manual:
            self.download(update)
        else:
            self._set_state(STATE_AVAILABLE)
            self.available.emit(update)

    # ---------------------------------------------------------- téléchargement
    def download(self, update: UpdateInfo) -> None:
        """Téléchargement silencieux, vérifié, avec progression ; `ready` à la fin."""
        self._download_attempts += 1
        self.percent = 0
        self._set_state(STATE_DOWNLOADING)
        self.progress.emit(0)
        dest = update_dir() / f"REKA-Taskbar-{update.version}.exe"
        last = [-1]

        def report(received: int, total: int) -> None:
            percent = int(received * 100 / total) if total else 0
            if percent != last[0]:          # un signal par pourcent, pas par bloc
                last[0] = percent
                try:
                    self._progressed.emit(percent)
                except RuntimeError:
                    pass

        def work() -> None:
            try:
                path, error = self._fetch_exe(update, dest, report), ""
            except UpdateError as exc:
                path, error = None, str(exc)
            except Exception as exc:
                path, error = None, f"Erreur inattendue ({exc})."
            try:
                self._downloaded.emit(update, path, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_progress(self, percent: int) -> None:
        if self._state == STATE_DOWNLOADING:
            self.percent = percent
            self.progress.emit(percent)

    def _on_downloaded(self, update: UpdateInfo, path: Path | None, error: str) -> None:
        if path is None:
            log.warning("Mise à jour non téléchargée : %s", error)
            self.fail(error)
            if self.auto_install and self._download_attempts < DOWNLOAD_ATTEMPTS:
                # Nouvel essai automatique ; en attendant, le bouton reste disponible
                QTimer.singleShot(DOWNLOAD_RETRY_MS, lambda: self._retry_download(update))
            return
        self.ready_path = Path(path)
        self.percent = 100
        self._set_state(STATE_READY)
        self.ready.emit(update, self.ready_path)

    def _retry_download(self, update: UpdateInfo) -> None:
        if self.latest is update and self._state == STATE_AVAILABLE:
            self.download(update)

    def fail(self, error: str) -> None:
        """L'installation automatique a échoué : on repasse au bouton « Mise à jour »."""
        self.error = error
        self.ready_path = None
        self._set_state(STATE_AVAILABLE)
        if self.latest is not None:
            self.available.emit(self.latest)

    def skip(self, update: UpdateInfo) -> None:
        """« Ignorer cette version » : plus proposée automatiquement."""
        self._cfg.setdefault("update", {})["skipped_version"] = update.version
        self.latest = None
        self.ready_path = None
        self._set_state(STATE_IDLE)
