"""
Garde des mises à jour : installe le nouvel exe, le lance, le surveille, et
revient à l'ancienne version si la nouvelle ne démarre pas.

Ce module n'utilise que la bibliothèque standard (pas de Qt) : le gardien
tourne dans l'ANCIEN exe (renommé REKA-Taskbar.old.exe), lancé avec
« --update-watchdog » par boot.py avant tout import lourd. Il fonctionne donc
même si la nouvelle version est complètement cassée.

Déroulé d'une mise à jour :
1. la barre en cours met le nouvel exe à la place du sien (le sien devient
   REKA-Taskbar.old.exe), note la mise à jour dans update_pending.json, lance
   le gardien depuis l'ancien exe, puis se ferme ;
2. le gardien lance la nouvelle version et attend qu'elle confirme son bon
   fonctionnement (elle efface update_pending.json après quelques secondes de
   marche normale) ;
3. si la nouvelle version s'arrête avant, ou ne confirme rien à temps, le
   gardien remet l'ancien exe en place, marque la version fautive comme
   ignorée et relance l'ancienne version.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from core import config

MARKER_FILE = "update_pending.json"
LOG_FILE = "update.log"
OLD_SUFFIX = ".old.exe"
BROKEN_SUFFIX = ".broken.exe"
WATCH_TIMEOUT_S = 150.0         # démarrage (verrou, extraction) + temps de bon fonctionnement
POLL_S = 0.5
HEALTHY_AFTER_MS = 20_000       # la nouvelle version confirme après 20 s de marche normale
RELEASE_RETRIES = 40            # l'exe fautif peut rester verrouillé un instant après son arrêt
WATCHDOG_ARG = "--update-watchdog"
STILL_ACTIVE = 259


class UpdateError(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


# --------------------------------------------------------------------------- #
# Fichiers
# --------------------------------------------------------------------------- #
def update_dir() -> Path:
    return config.app_data_dir() / "update"


def old_exe_path(current: Path) -> Path:
    return current.with_name(current.stem + OLD_SUFFIX)


def broken_exe_path(current: Path) -> Path:
    return current.with_name(current.stem + BROKEN_SUFFIX)


def marker_path() -> Path:
    return config.app_data_dir() / MARKER_FILE


def note(message: str) -> None:
    """Journal des mises à jour (update.log) : le gardien n'a pas d'autre journal."""
    try:
        with open(config.app_data_dir() / LOG_FILE, "a", encoding="utf-8") as out:
            out.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def write_marker(data: dict) -> None:
    path = marker_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_marker() -> dict | None:
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("exe") and data.get("to") else None


def remove_marker() -> None:
    try:
        marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def _retrying(action: Callable[[], object], attempts: int = 10, pause: float = 0.3) -> None:
    """Un fichier tout juste téléchargé peut être ouvert un instant par
    l'antivirus : quelques nouveaux essais avant d'abandonner."""
    for attempt in range(attempts):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause)


def install(new_exe: Path, current: Path) -> None:
    """Met `new_exe` à la place de `current` (l'exe en cours) : l'exe en cours
    est renommé en .old.exe (Windows le permet même s'il tourne), puis le
    nouveau prend son nom. En cas d'échec, l'ancien est remis en place."""
    old = old_exe_path(current)
    where = f"Impossible de remplacer REKA Taskbar dans {current.parent}"
    try:
        old.unlink(missing_ok=True)         # reste d'une mise à jour précédente
        _retrying(lambda: os.replace(current, old))
    except OSError as exc:
        raise UpdateError(f"{where} ({exc}).") from exc
    try:
        _retrying(lambda: shutil.move(str(new_exe), str(current)))
    except Exception as exc:
        try:
            if current.exists():
                current.unlink()
            os.replace(old, current)
        except OSError:
            note(f"Ancien exe non remis en place : {old}")
        raise UpdateError(f"Impossible d'installer la mise à jour ({exc}).") from exc


def cleanup_previous(current: Path | None = None) -> bool:
    """Supprime l'ancien exe, l'exe fautif d'un retour en arrière et les
    téléchargements restants ; False si l'un d'eux est encore verrouillé."""
    if current is None:
        if not getattr(sys, "frozen", False):
            return True
        current = Path(sys.executable)
    done = True
    for leftover in (old_exe_path(current), broken_exe_path(current)):
        if leftover.exists():
            try:
                leftover.unlink()
            except OSError:
                done = False
    folder = update_dir()
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    return done


# --------------------------------------------------------------------------- #
# Processus
# --------------------------------------------------------------------------- #
def launch(exe: Path, args: list[str]) -> int:
    """Lance `exe` détaché et renvoie son pid. Lève OSError en cas d'échec."""
    env = dict(os.environ)
    # Exe PyInstaller « onefile » : sans cette variable, le processus lancé se
    # croirait un sous-processus de celui-ci et réutiliserait son dossier
    # temporaire, supprimé dès que celui-ci se ferme.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen([str(exe), *args], env=env, cwd=str(exe.parent), close_fds=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
    return int(process.pid)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Hors Windows, un enfant terminé reste « zombie » tant qu'on ne l'a pas attendu
    try:
        done, _status = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def kill_tree(pid: int) -> None:
    """Arrête un processus et ses enfants (l'exe PyInstaller en a un)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Côté barre
# --------------------------------------------------------------------------- #
def start_watched_restart(previous: str, new_version: str, exe: Path,
                          launcher: Callable[[Path, list[str]], int] | None = None) -> bool:
    """Après install() : note la mise à jour et lance le gardien depuis l'ancien
    exe (qui lancera la nouvelle version). False si le gardien n'a pas pu
    partir : l'appelant relance alors directement la nouvelle version."""
    old = old_exe_path(exe)
    if not old.is_file():
        return False
    write_marker({"from": previous, "to": new_version, "exe": str(exe),
                  "created": time.time()})
    try:
        (launcher or launch)(old, [WATCHDOG_ARG])
    except OSError as exc:
        note(f"Gardien non lancé ({exc}) : redémarrage direct.")
        remove_marker()
        return False
    note(f"Mise à jour {previous} → {new_version} : gardien lancé.")
    return True


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def startup(version: str, executable: Path | None = None) -> bool:
    """Au démarrage : True si cette instance est une nouvelle version sous
    surveillance (elle devra appeler confirm() une fois en bon état). Elle se
    reconnaît à sa version, ou à son exe (celui que le gardien a lancé)."""
    data = read_marker()
    if data is None:
        return False
    if str(data.get("to")) == version or (
            executable is not None and _same_file(Path(data["exe"]), executable)):
        return True
    remove_marker()                 # reste d'une mise à jour plus ancienne
    return False


def confirm() -> None:
    """La nouvelle version fonctionne : le gardien peut s'arrêter."""
    if read_marker() is not None:
        note("Nouvelle version en bon état : confirmé au gardien.")
    remove_marker()


# --------------------------------------------------------------------------- #
# Côté gardien (ancien exe)
# --------------------------------------------------------------------------- #
def skip_version(version: str) -> None:
    """La version fautive n'est plus installée automatiquement."""
    path = config.user_config_path()
    try:
        cfg = config.read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        cfg = {}
    section = cfg.get("update") if isinstance(cfg.get("update"), dict) else {}
    section["skipped_version"] = version
    cfg["update"] = section
    try:
        config.save_config(cfg)
    except OSError as exc:
        note(f"Version fautive non mémorisée ({exc}).")


def rollback(marker: dict, launcher: Callable[[Path, list[str]], int] | None = None,
             sleep: Callable[[float], None] = time.sleep) -> bool:
    """Remet l'ancien exe en place et relance l'ancienne version."""
    launcher = launcher or launch
    exe = Path(marker["exe"])
    old, broken = old_exe_path(exe), broken_exe_path(exe)
    bad = str(marker.get("to", "?"))
    if not old.is_file():
        note(f"Retour en arrière impossible : {old} introuvable.")
        remove_marker()
        return False
    for _attempt in range(RELEASE_RETRIES):
        try:
            broken.unlink(missing_ok=True)
            if exe.exists():
                os.replace(exe, broken)
            break
        except OSError:
            sleep(POLL_S)               # l'exe fautif se termine encore
    else:
        note(f"Retour en arrière impossible : {exe} reste verrouillé.")
        remove_marker()
        return False
    try:
        os.replace(old, exe)
    except OSError as exc:
        note(f"Retour en arrière impossible ({exc}).")
        try:
            os.replace(broken, exe)
        except OSError:
            pass
        remove_marker()
        return False
    skip_version(bad)
    remove_marker()
    note(f"Version {bad} : pas démarrée, retour à la version {marker.get('from', '?')}.")
    try:
        launcher(exe, ["--restart", "--rolled-back", bad])
    except OSError as exc:
        note(f"Ancienne version non relancée ({exc}).")
    return True


def watch(marker: dict, launcher: Callable[[Path, list[str]], int] | None = None,
          alive: Callable[[int], bool] | None = None,
          kill: Callable[[int], None] | None = None,
          clock: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep,
          timeout: float = WATCH_TIMEOUT_S) -> str:
    """Lance la nouvelle version et attend sa confirmation : « ok » ou
    « rolled_back » (ou « failed » si le retour en arrière a échoué)."""
    launcher, alive, kill = launcher or launch, alive or process_alive, kill or kill_tree
    exe = Path(marker["exe"])
    try:
        pid = launcher(exe, ["--restart", "--updated-from", str(marker.get("from", ""))])
    except OSError as exc:
        note(f"Nouvelle version non lancée ({exc}).")
        pid = 0
    deadline = clock() + timeout
    while clock() < deadline:
        if read_marker() is None:
            return "ok"                 # la nouvelle version a confirmé
        if not alive(pid):
            break
        sleep(POLL_S)
    if read_marker() is None:
        return "ok"
    if alive(pid):
        note(f"Version {marker.get('to')} : pas de confirmation à temps, arrêt.")
        kill(pid)
    return "rolled_back" if rollback(marker, launcher, sleep) else "failed"


def watchdog_main() -> int:
    """Point d'entrée « --update-watchdog » (appelé par boot.py)."""
    marker = read_marker()
    if marker is None:
        return 0
    try:
        result = watch(marker)
    except Exception as exc:        # le gardien ne doit jamais rester bloqué
        note(f"Gardien interrompu : {exc!r}")
        return 1
    note(f"Gardien : {result}.")
    return 0 if result == "ok" else 1
