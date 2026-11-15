"""
Ancrage de la barre au bord de l'écran, et masquage de la barre de Windows.

- AppBar : enregistre la fenêtre comme « barre d'application » auprès de
  Windows (SHAppBarMessage). Windows lui réserve alors une bande d'écran : les
  fenêtres agrandies s'arrêtent à la barre au lieu de passer dessous.
- set_windows_taskbar_hidden() : cache la barre des tâches de Windows (et la
  passe en masquage automatique, sinon sa place resterait réservée), puis la
  rend dans l'état où elle était. L'état d'origine est noté dans un fichier :
  même après un plantage, le lancement suivant (ou --restore-taskbar) la rend.

Tout le code Win32 est derrière sys.platform == "win32" ; ailleurs, les
fonctions ne font rien (développement, tests).
"""

from __future__ import annotations

import ctypes
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

EDGE_TOP, EDGE_BOTTOM = "top", "bottom"
EDGES = {EDGE_TOP: "En haut", EDGE_BOTTOM: "En bas"}
_ABE = {EDGE_TOP: 1, EDGE_BOTTOM: 3}
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS, ABM_GETSTATE = 0, 1, 2, 3, 4
ABM_SETSTATE = 10
ABN_POSCHANGED, ABN_FULLSCREENAPP = 1, 2
ABS_AUTOHIDE = 1
CALLBACK_MESSAGE_NAME = "REKA.Taskbar.AppBar"
STATE_FILENAME = "taskbar_state.json"

Rect = tuple[int, int, int, int]          # gauche, haut, droite, bas (pixels physiques)


@dataclass(frozen=True)
class Monitor:
    device: str          # « \\.\DISPLAY1 » : le nom que Qt donne à l'écran
    rect: Rect
    primary: bool = False


def normalize_edge(edge: str) -> str:
    return edge if edge in _ABE else EDGE_TOP


def bar_rect(monitor: Rect, edge: str, height: int) -> Rect:
    """Bande de `height` pixels en haut ou en bas d'un écran."""
    left, top, right, bottom = monitor
    height = max(1, min(int(height), bottom - top))
    if normalize_edge(edge) == EDGE_BOTTOM:
        return left, bottom - height, right, bottom
    return left, top, right, top + height


def pick_monitor(monitors: list[Monitor], device: str,
                 origin: tuple[int, int] | None = None) -> Monitor | None:
    """L'écran voulu : reconnu à son nom, sinon à la position de son coin
    haut-gauche (`origin`), sinon l'écran principal."""
    for monitor in monitors:
        if device and monitor.device.lower() == device.lower():
            return monitor
    if origin is not None:
        for monitor in monitors:
            left, top, right, bottom = monitor.rect
            if left <= origin[0] < right and top <= origin[1] < bottom:
                return monitor
    for monitor in monitors:
        if monitor.primary:
            return monitor
    return monitors[0] if monitors else None


def covers(window: Rect, monitor: Rect) -> bool:
    """La fenêtre recouvre-t-elle tout l'écran (à 1 pixel près) ?"""
    return (window[0] <= monitor[0] + 1 and window[1] <= monitor[1] + 1
            and window[2] >= monitor[2] - 1 and window[3] >= monitor[3] - 1)


# Fenêtres du bureau : elles couvrent l'écran sans être un jeu
DESKTOP_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def foreground_fills_screen(own_hwnd: int) -> bool:
    """Une autre application plein écran est-elle au premier plan, sur le même
    écran que la barre ? Lu directement (pas via une notification de Windows,
    qui peut manquer quand un jeu quitte le plein écran, par exemple après
    Ctrl+Échap)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    from core import winapi

    foreground = int(winapi.user32.GetForegroundWindow() or 0)
    if not foreground or foreground == own_hwnd or winapi.class_name(foreground) in DESKTOP_CLASSES:
        return False
    monitor_flag = 2                                   # MONITOR_DEFAULTTONEAREST

    def monitor_of(hwnd: int):
        handle = int(winapi.user32.MonitorFromWindow(hwnd, monitor_flag) or 0)
        info = winapi.MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not handle or not winapi.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return None, None
        r = info.rcMonitor
        return handle, (r.left, r.top, r.right, r.bottom)

    own_handle, own_rect = monitor_of(own_hwnd)
    fg_handle, fg_rect = monitor_of(foreground)
    if own_rect is None or fg_rect is None or own_handle != fg_handle:
        return False
    window = wintypes.RECT()
    if not winapi.user32.GetWindowRect(foreground, ctypes.byref(window)):
        return False
    return covers((window.left, window.top, window.right, window.bottom), own_rect)


def list_monitors() -> list[Monitor]:
    if sys.platform != "win32":
        return []
    from core import winapi

    found: list[Monitor] = []

    def visit(handle, _dc, _rect, _lparam) -> bool:
        info = winapi.MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if winapi.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(Monitor(info.szDevice, (r.left, r.top, r.right, r.bottom),
                                 bool(info.dwFlags & winapi.MONITORINFOF_PRIMARY)))
        return True

    winapi.user32.EnumDisplayMonitors(None, None, winapi.MONITORENUMPROC(visit), 0)
    return found


class AppBar:
    """Réservation d'une bande d'écran pour une fenêtre (Windows seulement)."""

    def __init__(self, hwnd: int) -> None:
        self._hwnd = int(hwnd)
        self._registered = False
        self.callback_message = 0
        self.explorer_restarted_message = 0     # « TaskbarCreated » : l'Explorateur a redémarré
        self.supported = sys.platform == "win32"
        if self.supported:
            from core import winapi

            self._api = winapi
            self.callback_message = int(
                winapi.user32.RegisterWindowMessageW(CALLBACK_MESSAGE_NAME))
            self.explorer_restarted_message = int(
                winapi.user32.RegisterWindowMessageW("TaskbarCreated"))

    @property
    def registered(self) -> bool:
        return self._registered

    def _data(self):
        data = self._api.APPBARDATA()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = self._hwnd
        return data

    def dock(self, edge: str, height_px: int, device: str = "", reserve: bool = True,
             origin: tuple[int, int] | None = None) -> Rect | None:
        """Place la fenêtre sur le bord `edge` de l'écran `device` (ou de celui
        qui contient `origin`) ; avec `reserve`, Windows garde cette bande
        libre. Renvoie le rectangle obtenu."""
        if not self.supported:
            return None
        api = self._api
        monitor = pick_monitor(list_monitors(), device, origin)
        if monitor is None:
            return None
        edge = normalize_edge(edge)
        rect = bar_rect(monitor.rect, edge, height_px)
        if reserve:
            if not self._registered:
                data = self._data()
                data.uCallbackMessage = self.callback_message
                self._registered = bool(api.shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(data)))
                if not self._registered:
                    log.warning("Windows a refusé de réserver la place de la barre.")
            if self._registered:
                data = self._data()
                data.uEdge = _ABE[edge]
                data.rc.left, data.rc.top, data.rc.right, data.rc.bottom = rect
                api.shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(data))
                # Windows a pu décaler la bande (autre barre sur ce bord) : on
                # garde la position proposée et on y remet notre épaisseur
                if edge == EDGE_TOP:
                    data.rc.bottom = data.rc.top + (rect[3] - rect[1])
                else:
                    data.rc.top = data.rc.bottom - (rect[3] - rect[1])
                api.shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(data))
                rect = (data.rc.left, data.rc.top, data.rc.right, data.rc.bottom)
        else:
            self.remove()
        api.user32.SetWindowPos(self._hwnd, api.HWND_TOPMOST, rect[0], rect[1],
                                rect[2] - rect[0], rect[3] - rect[1], api.SWP_NOACTIVATE)
        return rect

    def forget_registration(self) -> None:
        """L'Explorateur de Windows a redémarré : il a oublié la réservation,
        le prochain dock() la refait."""
        self._registered = False

    def remove(self) -> None:
        """Rend la bande d'écran à Windows."""
        if self.supported and self._registered:
            data = self._data()
            self._api.shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(data))
            self._registered = False


# --------------------------------------------------------------------------- #
# Barre des tâches de Windows
# --------------------------------------------------------------------------- #
def _taskbar_windows() -> list[int]:
    from core import winapi

    windows = []
    main = winapi.user32.FindWindowW("Shell_TrayWnd", None)
    if main:
        windows.append(int(main))
    child = None
    while True:      # une barre par écran secondaire
        child = winapi.user32.FindWindowExW(None, child, "Shell_SecondaryTrayWnd", None)
        if not child:
            break
        windows.append(int(child))
    return windows


def _taskbar_state(set_to: int | None = None) -> int:
    """Lit (ou règle) l'état de la barre de Windows : ABS_AUTOHIDE…"""
    from core import winapi

    data = winapi.APPBARDATA()
    data.cbSize = ctypes.sizeof(data)
    data.hWnd = winapi.user32.FindWindowW("Shell_TrayWnd", None)
    if set_to is None:
        return int(winapi.shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data)))
    data.lParam = set_to
    winapi.shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(data))
    return set_to


def windows_taskbar_visible() -> bool:
    if sys.platform != "win32":
        return True
    from core import winapi

    return any(winapi.user32.IsWindowVisible(hwnd) for hwnd in _taskbar_windows())


def set_windows_taskbar_hidden(hidden: bool, data_dir: Path) -> bool:
    """Cache ou rend la barre des tâches de Windows ; True si c'est fait.

    `data_dir` reçoit le fichier qui note son état d'origine tant qu'elle est
    cachée ; s'il existe au démarrage, c'est qu'il faut encore la rendre."""
    state_file = data_dir / STATE_FILENAME
    if sys.platform != "win32":
        return False
    from core import winapi

    try:
        if hidden:
            if not state_file.is_file():           # l'état d'origine, noté une seule fois
                state_file.write_text(json.dumps({"state": _taskbar_state()}), encoding="utf-8")
                _taskbar_state(_taskbar_state() | ABS_AUTOHIDE)
            for hwnd in _taskbar_windows():
                winapi.user32.ShowWindow(hwnd, winapi.SW_HIDE)
        else:
            if state_file.is_file():
                try:
                    original = int(json.loads(state_file.read_text(encoding="utf-8"))["state"])
                except (OSError, ValueError, KeyError, TypeError):
                    original = _taskbar_state() & ~ABS_AUTOHIDE
                _taskbar_state(original)
                state_file.unlink(missing_ok=True)
            for hwnd in _taskbar_windows():
                winapi.user32.ShowWindow(hwnd, winapi.SW_SHOWNOACTIVATE)
    except OSError as exc:
        log.warning("Barre des tâches de Windows : %s", exc)
        return False
    return True


def restore_windows_taskbar_if_needed(data_dir: Path) -> bool:
    """Au démarrage : rend la barre de Windows si une session précédente l'a
    laissée cachée (plantage, arrêt forcé). True si elle a été rendue."""
    if (data_dir / STATE_FILENAME).is_file():
        log.info("Barre des tâches de Windows laissée cachée : on la rend.")
        return set_windows_taskbar_hidden(False, data_dir)
    return False
