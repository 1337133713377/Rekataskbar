"""
Fenêtres ouvertes : la liste que montre une barre des tâches, et de quoi les
activer, les réduire et les fermer.

Trois moteurs, même interface :
- Win32Windows : le vrai (EnumWindows, mêmes règles que Alt+Tab) ;
- DemoWindows  : quelques fenêtres simulées (--demo, --selftest, tests) ;
- NullWindows  : hors Windows, liste vide (le widget se cache).
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

# Fenêtres du bureau et de l'Explorateur qui ne sont pas des applications
SHELL_CLASSES = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
    "TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow",
})
UWP_FRAME_CLASS = "ApplicationFrameWindow"
UWP_CORE_CLASS = "Windows.UI.Core.CoreWindow"
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    exe: str = ""            # chemin de l'exécutable ("" si inconnu)
    active: bool = False     # c'est la fenêtre au premier plan
    minimized: bool = False

    @property
    def app(self) -> str:
        """Nom court de l'application : « chrome », « Discord »."""
        return Path(self.exe.replace("\\", "/")).stem if self.exe else self.title


def is_task_window(*, visible: bool, title: str, ex_style: int, has_owner: bool,
                   cloaked: bool, class_name: str) -> bool:
    """Cette fenêtre a-t-elle sa place dans la barre ? (règles de Alt+Tab)"""
    if not visible or cloaked or not title.strip() or class_name in SHELL_CLASSES:
        return False
    if ex_style & WS_EX_APPWINDOW:           # la fenêtre demande elle-même à y figurer
        return True
    if ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
        return False
    return not has_owner                     # une boîte de dialogue suit sa fenêtre


def stable_order(previous: list[int], current: list[int]) -> list[int]:
    """Ordre des boutons : une fenêtre garde sa place, les nouvelles arrivent
    au bout (EnumWindows suit l'ordre d'empilement, qui change à chaque clic)."""
    alive = set(current)
    order = [hwnd for hwnd in previous if hwnd in alive]
    known = set(order)
    order.extend(hwnd for hwnd in current if hwnd not in known)
    return order


class WindowBackend:
    available = False

    def windows(self) -> list[WindowInfo]:
        return []

    def activate(self, hwnd: int) -> None:
        pass

    def minimize(self, hwnd: int) -> None:
        pass

    def close(self, hwnd: int) -> None:
        pass


class NullWindows(WindowBackend):
    pass


class DemoWindows(WindowBackend):
    """Fenêtres simulées ; activer / réduire / fermer agissent sur la liste."""

    available = True
    APPS = (("REKA", "C:/Apps/REKA.exe"), ("Discord", "C:/Apps/Discord.exe"),
            ("Spotify — Néons de minuit", "C:/Apps/Spotify.exe"),
            ("OBS Studio", "C:/Apps/obs64.exe"), ("Explorateur de fichiers", "C:/Windows/explorer.exe"),
            ("Mozilla Firefox", "C:/Apps/firefox.exe"))

    def __init__(self) -> None:
        self._windows = [WindowInfo(100 + n, title, exe, active=n == 1)
                         for n, (title, exe) in enumerate(self.APPS)]

    def windows(self) -> list[WindowInfo]:
        return list(self._windows)

    def activate(self, hwnd: int) -> None:
        self._windows = [replace(w, active=w.hwnd == hwnd,
                                 minimized=w.minimized and w.hwnd != hwnd)
                         for w in self._windows]

    def minimize(self, hwnd: int) -> None:
        self._windows = [replace(w, active=False, minimized=True) if w.hwnd == hwnd else w
                         for w in self._windows]

    def close(self, hwnd: int) -> None:
        self._windows = [w for w in self._windows if w.hwnd != hwnd]


class Win32Windows(WindowBackend):
    available = True

    def __init__(self) -> None:
        from core import winapi

        self._api = winapi
        self._own_pid = int(winapi.kernel32.GetCurrentProcessId())
        self._order: list[int] = []
        self._paths: dict[int, str] = {}         # pid → exécutable
        self._last_foreground = 0                # dernière fenêtre active qui n'est pas la barre

    def windows(self) -> list[WindowInfo]:
        api = self._api
        found: dict[int, WindowInfo] = {}

        def visit(hwnd, _lparam) -> bool:
            hwnd = int(hwnd or 0)
            try:
                info = self._describe(hwnd)
            except Exception as exc:              # fenêtre disparue pendant l'énumération
                log.debug("Fenêtre %#x ignorée : %s", hwnd, exc)
                info = None
            if info is not None:
                found[hwnd] = info
            return True

        api.user32.EnumWindows(api.WNDENUMPROC(visit), 0)
        foreground = int(api.user32.GetForegroundWindow() or 0)
        if foreground in found:
            self._last_foreground = foreground
        elif foreground and api.window_pid(foreground) != self._own_pid:
            self._last_foreground = 0             # bureau, menu Démarrer… : rien d'actif
        self._order = stable_order(self._order, list(found))
        if len(self._paths) > 512:
            self._paths.clear()
        return [replace(found[hwnd], active=hwnd == self._last_foreground
                        and not found[hwnd].minimized)
                for hwnd in self._order]

    def _describe(self, hwnd: int) -> WindowInfo | None:
        api = self._api
        if not api.user32.IsWindowVisible(hwnd):
            return None
        pid = api.window_pid(hwnd)
        if pid == self._own_pid:
            return None
        title = api.window_text(hwnd)
        name = api.class_name(hwnd)
        if not is_task_window(visible=True, title=title,
                              ex_style=int(api.user32.GetWindowLongW(hwnd, api.GWL_EXSTYLE)),
                              has_owner=bool(api.user32.GetWindow(hwnd, api.GW_OWNER)),
                              cloaked=api.is_cloaked(hwnd), class_name=name):
            return None
        if name == UWP_FRAME_CLASS:      # application du Store : son vrai processus est l'enfant
            core = api.user32.FindWindowExW(hwnd, None, UWP_CORE_CLASS, None)
            if core:
                pid = api.window_pid(int(core)) or pid
        return WindowInfo(hwnd, title, self._path(pid),
                          minimized=bool(api.user32.IsIconic(hwnd)))

    def _path(self, pid: int) -> str:
        if pid not in self._paths:
            self._paths[pid] = self._api.process_path(pid)
        return self._paths[pid]

    def activate(self, hwnd: int) -> None:
        api = self._api
        if api.user32.IsIconic(hwnd):
            api.user32.ShowWindowAsync(hwnd, api.SW_RESTORE)
        api.user32.SetForegroundWindow(hwnd)
        self._last_foreground = hwnd

    def minimize(self, hwnd: int) -> None:
        self._api.user32.ShowWindowAsync(hwnd, self._api.SW_MINIMIZE)
        if self._last_foreground == hwnd:
            self._last_foreground = 0

    def close(self, hwnd: int) -> None:
        self._api.user32.PostMessageW(hwnd, self._api.WM_CLOSE, 0, 0)


def create_window_backend() -> WindowBackend:
    if sys.platform != "win32":
        return NullWindows()
    try:
        return Win32Windows()
    except Exception as exc:
        log.warning("Liste des fenêtres indisponible : %s", exc)
        return NullWindows()
