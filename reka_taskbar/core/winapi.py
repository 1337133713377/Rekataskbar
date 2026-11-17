"""
Fonctions Win32 utilisées par la barre (ctypes), avec leurs signatures : sans
elles, ctypes tronquerait les handles de fenêtres à 32 bits.

À n'importer que sous Windows (sys.platform == "win32").
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


def _declare(function, restype, *argtypes) -> None:
    function.restype = restype
    function.argtypes = list(argtypes)


_declare(user32.EnumWindows, wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_declare(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
_declare(user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_declare(user32.IsIconic, wintypes.BOOL, wintypes.HWND)
_declare(user32.GetWindowTextLengthW, ctypes.c_int, wintypes.HWND)
_declare(user32.GetWindowTextW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_declare(user32.GetClassNameW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_declare(user32.GetWindowLongW, wintypes.LONG, wintypes.HWND, ctypes.c_int)
_declare(user32.GetWindow, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_declare(user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND,
         ctypes.POINTER(wintypes.DWORD))
_declare(user32.GetForegroundWindow, wintypes.HWND)
_declare(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_declare(user32.ShowWindow, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_declare(user32.ShowWindowAsync, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_declare(user32.PostMessageW, wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
         wintypes.LPARAM)
_declare(user32.FindWindowW, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_declare(user32.FindWindowExW, wintypes.HWND, wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR,
         wintypes.LPCWSTR)
_declare(user32.SetWindowPos, wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int,
         ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
_declare(user32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_declare(user32.EnumDisplayMonitors, wintypes.BOOL, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
         MONITORENUMPROC, wintypes.LPARAM)
_declare(user32.GetMonitorInfoW, wintypes.BOOL, wintypes.HMONITOR,
         ctypes.POINTER(MONITORINFOEXW))
_declare(user32.MonitorFromWindow, wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
_declare(user32.RegisterWindowMessageW, wintypes.UINT, wintypes.LPCWSTR)
_declare(user32.keybd_event, None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
         ctypes.c_size_t)
_declare(user32.LockWorkStation, wintypes.BOOL)
_declare(user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT,
         wintypes.UINT)
_declare(user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_declare(user32.IsZoomed, wintypes.BOOL, wintypes.HWND)
_declare(user32.IsWindowEnabled, wintypes.BOOL, wintypes.HWND)
_declare(user32.GetLastActivePopup, wintypes.HWND, wintypes.HWND)
_declare(user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_declare(user32.AllowSetForegroundWindow, wintypes.BOOL, wintypes.DWORD)
_declare(user32.SwitchToThisWindow, None, wintypes.HWND, wintypes.BOOL)

_declare(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_declare(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_declare(kernel32.QueryFullProcessImageNameW, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_declare(kernel32.GetCurrentProcessId, wintypes.DWORD)
_declare(kernel32.GetCurrentThreadId, wintypes.DWORD)

_declare(shell32.SHAppBarMessage, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(APPBARDATA))
_declare(shell32.SHQueryUserNotificationState, ctypes.c_long, ctypes.POINTER(ctypes.c_int))
_declare(dwmapi.DwmGetWindowAttribute, ctypes.c_long, wintypes.HWND, wintypes.DWORD,
         ctypes.c_void_p, wintypes.DWORD)

try:      # Windows 10 1607 et suivants
    _declare(user32.GetDpiForWindow, wintypes.UINT, wintypes.HWND)
    get_dpi_for_window = user32.GetDpiForWindow
except AttributeError:      # pragma: no cover - Windows trop ancien
    get_dpi_for_window = None

# --- Constantes ---------------------------------------------------------------
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION = 0x00C00000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4
DWMWA_CLOAKED = 14
SW_HIDE, SW_SHOWNOACTIVATE, SW_MINIMIZE, SW_RESTORE = 0, 4, 6, 9
WM_CLOSE = 0x0010
WM_HOTKEY = 0x0312
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
HWND_TOP, HWND_TOPMOST, HWND_BOTTOM = 0, -1, 1
SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 1, 2
ASFW_ANY = 0xFFFFFFFF
QUNS_RUNNING_D3D_FULL_SCREEN = 3       # jeu Direct3D en plein écran exclusif
MONITORINFOF_PRIMARY = 1
VK_LWIN = 0x5B
KEYEVENTF_KEYUP = 0x0002


def window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_path(pid: int) -> str:
    """Chemin de l'exécutable d'un processus, "" s'il est protégé ou terminé."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def is_cloaked(hwnd: int) -> bool:
    """Fenêtre « masquée par le système » : application UWP en veille, fenêtre
    d'un autre bureau virtuel."""
    value = wintypes.DWORD(0)
    result = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value),
                                          ctypes.sizeof(value))
    return result == 0 and value.value != 0


def is_topmost(hwnd: int) -> bool:
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def exclusive_fullscreen() -> bool:
    """Un jeu Direct3D est-il en plein écran exclusif ? (état vu par Windows)"""
    state = ctypes.c_int(0)
    return (shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0
            and state.value == QUNS_RUNNING_D3D_FULL_SCREEN)


def force_foreground(hwnd: int) -> bool:
    """Met `hwnd` au premier plan, même quand Windows le refuse d'ordinaire
    (« verrou de premier plan » : la barre ne prend jamais le focus, et un jeu
    en plein écran garde la main). Trois essais, du plus doux au plus ferme :
    SetForegroundWindow ; le même en s'attachant un instant au fil de la
    fenêtre au premier plan ; SwitchToThisWindow (celui de Alt+Tab).
    Aucun appel ne peut bloquer la barre sur une application qui ne répond pas."""
    hwnd = int(hwnd)
    if int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    user32.AllowSetForegroundWindow(ASFW_ANY)
    if user32.SetForegroundWindow(hwnd) and int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    foreground = int(user32.GetForegroundWindow() or 0)
    current = int(kernel32.GetCurrentThreadId())
    other = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
    attached = bool(other and other != current
                    and user32.AttachThreadInput(current, other, True))
    try:
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_ASYNCWINDOWPOS)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current, other, False)
    if int(user32.GetForegroundWindow() or 0) == hwnd:
        return True
    user32.SwitchToThisWindow(hwnd, True)
    return int(user32.GetForegroundWindow() or 0) == hwnd


def press_windows_key() -> None:
    """Appui sur la touche Windows : ouvre le menu Démarrer."""
    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
