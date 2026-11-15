"""Fonctions Win32 réelles (exécutées par le build GitHub, sur une machine Windows)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows seulement")


@pytest.fixture
def real_windows(qapp):
    """Ces tests ont besoin de vraies fenêtres : QT_QPA_PLATFORM=windows."""
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        pytest.skip("Qt hors écran : pas de vraies fenêtres")
    return qapp


def test_monitors_are_listed():
    from core import appbar

    monitors = appbar.list_monitors()
    assert monitors and any(m.primary for m in monitors)
    left, top, right, bottom = monitors[0].rect
    assert right > left and bottom > top


def test_open_windows_are_enumerated_without_error(real_windows):
    qapp = real_windows
    from PySide6.QtWidgets import QWidget

    from conftest import pump
    from core.windows import Win32Windows

    backend = Win32Windows()
    own = QWidget()
    own.setWindowTitle("Fenêtre de la barre")
    own.show()
    pump(qapp, 0.2)
    windows = backend.windows()
    assert all(w.title for w in windows)
    assert int(own.winId()) not in [w.hwnd for w in windows]      # jamais ses propres fenêtres
    own.close()


def test_appbar_reserves_and_releases_screen_space(real_windows):
    qapp = real_windows
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from conftest import pump
    from core import appbar, winapi

    window = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    window.show()
    pump(qapp, 0.2)
    bar = appbar.AppBar(int(window.winId()))
    try:
        rect = bar.dock("top", 40)
        assert rect is not None and rect[3] - rect[1] == 40
        if bar.registered:            # une session sans Explorateur refuse la réservation
            import ctypes
            from ctypes import wintypes

            actual = wintypes.RECT()
            winapi.user32.GetWindowRect(int(window.winId()), ctypes.byref(actual))
            assert (actual.left, actual.top, actual.right, actual.bottom) == rect
    finally:
        bar.remove()
        assert not bar.registered
        window.close()


def test_reka_detection_reads_named_pipes(qapp):
    from PySide6.QtNetwork import QLocalServer

    from core import reka_link

    assert not reka_link.is_reka_running()             # canal de test : personne n'écoute
    server = QLocalServer()
    assert server.listen(reka_link.instance_name())
    try:
        assert reka_link.is_reka_running()
        assert not server.hasPendingConnections()      # détecter ne se connecte pas
    finally:
        server.close()


def test_remote_api_reports_missing_voicemeeter_cleanly():
    from core.voicemeeter import RemoteApi, VoicemeeterMissing

    try:
        api = RemoteApi()
    except VoicemeeterMissing:
        return                                          # pas installé sur la machine de build
    running = api.login()
    api.logout()
    assert running in (True, False)


def test_autostart_round_trip():
    from core import shell

    was = shell.autostart_enabled()
    try:
        assert shell.set_autostart(True) and shell.autostart_enabled()
        assert shell.set_autostart(False) and not shell.autostart_enabled()
    finally:
        shell.set_autostart(was)
