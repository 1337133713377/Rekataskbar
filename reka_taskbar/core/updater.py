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

Avec l'installation automatique désactivée (ou si l'exe est dans un dossier
protégé), un bouton « Mise à jour » apparaît dans la barre à la place.

En développement (python main.py), pas de build_info.json : pas de vérification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from core import config

log = logging.getLogger(__name__)

BUILD_INFO_FILE = "build_info.json"
VERSION_FILE = "version.json"
EXE_NAME = "REKA-Taskbar.exe"
OLD_SUFFIX = ".old.exe"
FETCH_TIMEOUT_S = 10.0
DOWNLOAD_TIMEOUT_S = 30.0
CHUNK = 64 * 1024
MAX_VERSION_FILE = 64 * 1024
START_DELAY_MS = 20_000         # première vérification : une fois la session bien lancée
MIN_INTERVAL_H = 1.0
BUSY_RETRY_MS = 60_000          # menu ou réglages ouverts : on redémarre un peu plus tard


class UpdateError(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


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
    if (not update.url.lower().startswith("https://") or len(update.sha256) != 64
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


def update_dir() -> Path:
    return config.app_data_dir() / "update"


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


def old_exe_path(current: Path) -> Path:
    return current.with_name(current.stem + OLD_SUFFIX)


def install(new_exe: Path, current: Path) -> None:
    """Met `new_exe` à la place de `current` (l'exe en cours) : l'exe en cours
    est renommé en .old.exe (Windows le permet même s'il tourne), puis le
    nouveau prend son nom. En cas d'échec, l'ancien est remis en place."""
    old = old_exe_path(current)
    where = f"Impossible de remplacer REKA Taskbar dans {current.parent}"
    try:
        old.unlink(missing_ok=True)         # reste d'une mise à jour précédente
        os.replace(current, old)
    except OSError as exc:
        raise UpdateError(f"{where} ({exc}).") from exc
    try:
        shutil.move(str(new_exe), str(current))
    except Exception as exc:
        try:
            if current.exists():
                current.unlink()
            os.replace(old, current)
        except OSError:
            log.exception("Mise à jour : ancien exe non remis en place (%s)", old)
        raise UpdateError(f"Impossible d'installer la mise à jour ({exc}).") from exc
    log.info("Mise à jour installée : %s (ancien exe : %s)", current, old)


def cleanup_previous(current: Path | None = None) -> bool:
    """Supprime l'ancien exe et les téléchargements restants ; False si l'ancien
    exe est encore verrouillé (l'ancienne instance finit de se fermer)."""
    if current is None:
        if not getattr(sys, "frozen", False):
            return True
        current = Path(sys.executable)
    done = True
    old = old_exe_path(current)
    if old.exists():
        try:
            old.unlink()
            log.info("Ancien exe supprimé : %s", old)
        except OSError:
            done = False
    folder = update_dir()
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    return done


def can_self_update() -> bool:
    """Remplacement automatique possible : exe PyInstaller (pas en développement)."""
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).suffix.lower() == ".exe"


def restart_command(previous_version: str) -> tuple[str, list[str]]:
    """Commande qui relance la barre après une mise à jour."""
    return sys.executable, ["--restart", "--updated-from", previous_version]


def launch_restart(previous_version: str) -> bool:
    """Lance la nouvelle instance (détachée) ; l'appelant quitte ensuite."""
    from PySide6.QtCore import QProcess

    program, args = restart_command(previous_version)
    # Exe PyInstaller « onefile » : sans cette variable, la nouvelle instance
    # se croirait un sous-processus de celle-ci et réutiliserait son dossier
    # temporaire, supprimé dès que cette instance se ferme.
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    result = QProcess.startDetached(program, args)
    started = result[0] if isinstance(result, tuple) else bool(result)
    if not started:
        log.error("Impossible de relancer la barre : %s %s", program, " ".join(args))
    return started


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

    - `available` : une version plus récente existe (UpdateInfo) ;
    - `ready` : l'exe est téléchargé et vérifié (UpdateInfo, Path) : à
      installer dès que la barre n'est pas occupée ;
    - `checked` : fin d'une vérification (UpdateInfo ou None, message d'erreur).
    """

    available = Signal(object)
    ready = Signal(object, object)
    checked = Signal(object, str)
    state_changed = Signal(str)
    _fetched = Signal(object, str, bool)      # (UpdateInfo | None, erreur, manuelle)
    _downloaded = Signal(object, object, str)  # (UpdateInfo, Path | None, erreur)

    def __init__(self, cfg: dict, build: BuildInfo | None,
                 fetch: Callable[[str], UpdateInfo] = fetch_update,
                 fetch_exe: Callable[[UpdateInfo, Path], Path] = download,
                 self_update: bool | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.build = build
        self._fetch = fetch
        self._fetch_exe = fetch_exe
        self.self_update = can_self_update() if self_update is None else self_update
        self.latest: UpdateInfo | None = None
        self.error = ""
        self._state = STATE_IDLE
        self._busy = threading.Lock()
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.check(False))
        self._fetched.connect(self._on_fetched)
        self._downloaded.connect(self._on_downloaded)

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
        return bool(self._cfg.get("update", {}).get("auto_install", True)) and self.self_update

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def start(self) -> None:
        """Vérification au démarrage (un peu différée) puis régulière."""
        section = self._cfg.get("update", {})
        if not self.enabled or not section.get("check", True):
            return
        try:
            hours = max(MIN_INTERVAL_H, float(section.get("interval_hours", 6)))
        except (TypeError, ValueError):
            hours = 6.0
        self._timer.start(round(hours * 3_600_000))
        QTimer.singleShot(START_DELAY_MS, lambda: self.check(False))

    def stop(self) -> None:
        self._timer.stop()

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
            log.info("Vérification des mises à jour : %s", error)
            self.error = error
            self._set_state(STATE_AVAILABLE if self.latest is not None else STATE_IDLE)
            self.checked.emit(None, error)
            return
        self.error = ""
        skipped = "" if manual else str(self._cfg.get("update", {}).get("skipped_version") or "")
        if not is_newer(update, self.current_version, skipped):
            self._set_state(STATE_AVAILABLE if self.latest is not None else STATE_IDLE)
            self.checked.emit(None, "")
            return
        log.info("Mise à jour disponible : %s (en cours : %s)", update.version,
                 self.current_version)
        self.latest = update
        self.checked.emit(update, "")
        if self.auto_install and not manual:
            self.download(update)
        else:
            self._set_state(STATE_AVAILABLE)
            self.available.emit(update)

    # ---------------------------------------------------------- téléchargement
    def download(self, update: UpdateInfo) -> None:
        """Téléchargement silencieux, vérifié ; `ready` à la fin."""
        self._set_state(STATE_DOWNLOADING)
        dest = update_dir() / f"REKA-Taskbar-{update.version}.exe"

        def work() -> None:
            try:
                path, error = self._fetch_exe(update, dest), ""
            except UpdateError as exc:
                path, error = None, str(exc)
            except Exception as exc:
                path, error = None, f"Erreur inattendue ({exc})."
            try:
                self._downloaded.emit(update, path, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_downloaded(self, update: UpdateInfo, path: Path | None, error: str) -> None:
        if path is None:
            log.warning("Mise à jour non téléchargée : %s", error)
            self.fail(error)
            return
        self._set_state(STATE_READY)
        self.ready.emit(update, path)

    def fail(self, error: str) -> None:
        """L'installation automatique a échoué : on repasse au bouton « Mise à jour »."""
        self.error = error
        self._set_state(STATE_AVAILABLE)
        if self.latest is not None:
            self.available.emit(self.latest)

    def skip(self, update: UpdateInfo) -> None:
        """« Ignorer cette version » : plus proposée automatiquement."""
        self._cfg.setdefault("update", {})["skipped_version"] = update.version
        self.latest = None
        self._set_state(STATE_IDLE)
