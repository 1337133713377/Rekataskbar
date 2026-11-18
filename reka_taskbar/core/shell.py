"""
Petits services de Windows : menu Démarrer, verrouillage, démarrage avec la
session, raccourci clavier global. Hors Windows, ces fonctions ne font rien.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "REKA Taskbar"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
              "maj": MOD_SHIFT, "win": MOD_WIN, "windows": MOD_WIN}
_KEYS = {"pause": 0x13, "espace": 0x20, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
         "end": 0x23, "fin": 0x23, "home": 0x24, "insert": 0x2D, "inser": 0x2D,
         "delete": 0x2E, "suppr": 0x2E, "scrolllock": 0x91, "arretdefil": 0x91}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """« Ctrl+Alt+M » → (modificateurs, code de touche) pour RegisterHotKey ;
    None si le raccourci est vide ou incompréhensible. Une touche seule n'est
    acceptée que pour F1 à F24 et les touches nommées (Pause, Arrêt défil…) :
    réserver « M » empêcherait de taper cette lettre partout."""
    parts = [p.strip().lower() for p in str(text or "").replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    modifiers = 0
    for name in parts[:-1]:
        if name not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[name]
    key = parts[-1].replace(" ", "")
    named = False
    if len(key) == 1 and (key.isascii() and key.isalnum()):
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk, named = 0x70 + int(key[1:]) - 1, True
    elif key in _KEYS:
        vk, named = _KEYS[key], True
    else:
        return None
    if not modifiers and not named:
        return None
    return modifiers, vk


def open_start_menu() -> None:
    if sys.platform == "win32":
        from core import winapi

        winapi.press_windows_key()


def open_tray_overflow() -> None:
    """Icônes cachées près de l'horloge (applications réduites dans la zone de notification)."""
    if sys.platform == "win32":
        from core import winapi

        winapi.open_tray_overflow()


def lock_session() -> None:
    if sys.platform == "win32":
        from core import winapi

        winapi.user32.LockWorkStation()


def run(command: str) -> bool:
    """Ouvre un programme, un dossier, un raccourci ou une adresse
    (« taskmgr », « ms-settings: », « C:\\Jeux\\jeu.lnk »)."""
    try:
        if sys.platform == "win32":
            os.startfile(command)       # noqa: S606 - commande choisie par l'utilisateur
        else:
            subprocess.Popen(["xdg-open", command], close_fds=True)
    except OSError as exc:
        log.warning("« %s » non ouvert : %s", command, exc)
        return False
    return True


# --- Démarrage avec Windows ---------------------------------------------------
def autostart_command() -> str:
    """Commande qui relance la barre : l'exe, ou python + main.py en développement."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main = Path(__file__).resolve().parent.parent / "main.py"
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.is_file() else python}" "{main}"'


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, RUN_VALUE)[0])
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Inscrit (ou retire) la barre des programmes lancés à l'ouverture de session."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        # CreateKeyEx ouvre la clé, ou la crée : elle n'existe pas sur un compte tout neuf
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log.warning("Démarrage avec Windows non modifié : %s", exc)
        return False
    return True
