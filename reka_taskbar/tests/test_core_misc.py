"""Système, météo, raccourcis Windows, fenêtres, ancrage."""

import sys
import time

import pytest

from conftest import wait_for
from core import appbar, shell
from core.system import SystemMonitor, format_bytes, format_duration, format_rate
from core.weather import Weather, WeatherService, fetch_weather, parse_weather
from core.windows import DemoWindows, is_task_window, stable_order


# --- système -------------------------------------------------------------------
def test_formats():
    assert format_rate(0) == "0 o/s" and format_rate(840) == "840 o/s"
    assert format_rate(12 * 1024) == "12 ko/s" and format_rate(1536) == "1,5 ko/s"
    assert format_rate(3.4 * 1024 ** 2) == "3,4 Mo/s"
    assert format_rate(2 * 1024 ** 3) == "2,0 Go/s"
    assert format_bytes(8 * 1024 ** 3) == "8,0 Go"
    assert format_duration(3 * 3600 + 12 * 60) == "3 h 12" and format_duration(600) == "10 min"


def test_system_monitor_reads_this_machine(qapp):
    monitor = SystemMonitor()
    seen = []
    monitor.changed.connect(seen.append)
    monitor.sample()
    monitor.sample()
    stats = seen[-1]
    assert 0 <= stats.cpu <= 100 and 0 < stats.ram <= 100 and stats.ram_total > 0
    assert stats.down >= 0 and stats.up >= 0


# --- météo ---------------------------------------------------------------------
FORECAST = {"current": {"temperature_2m": 17.4, "weather_code": 61, "is_day": 0},
            "daily": {"temperature_2m_min": [11.2], "temperature_2m_max": [19.0]}}


def test_parse_weather():
    weather = parse_weather("Lyon", FORECAST)
    assert weather == Weather("Lyon", 17.4, 61, False, 11.2, 19.0)
    assert weather.description == "Pluie faible" and weather.icon == "rain"
    assert Weather("x", 1, 0, is_day=False).icon == "moon" and Weather("x", 1, 0).icon == "sun"
    with pytest.raises(ValueError):
        parse_weather("Lyon", {"current": {}})


def test_fetch_weather_sends_only_the_city():
    calls = []

    def get_json(url, params):
        calls.append((url, params))
        if "geocoding" in url:
            return {"results": [{"name": "Lyon", "latitude": 45.75, "longitude": 4.85}]}
        return FORECAST

    assert fetch_weather("lyon", get_json).city == "Lyon"
    assert calls[0][1]["name"] == "lyon" and calls[1][1]["latitude"] == 45.75
    with pytest.raises(LookupError):
        fetch_weather("Nulle part", lambda url, params: {})


def test_weather_service(qapp):
    requested = []

    def fetch(city):
        requested.append(city)
        if city == "Erreur":
            raise OSError("pas de réseau")
        return Weather(city, 20.0)

    service = WeatherService("", fetch=fetch)
    seen = []
    service.changed.connect(seen.append)
    service.start()
    assert requested == []                            # pas de ville : aucune requête
    service.set_city("Paris")
    assert wait_for(qapp, lambda: service.weather == Weather("Paris", 20.0))
    service.set_city("Erreur")
    assert wait_for(qapp, lambda: bool(service.error))
    assert service.weather is None and "réseau" in service.error
    service.stop()


# --- raccourci clavier ------------------------------------------------------------
def test_parse_hotkey():
    assert shell.parse_hotkey("Ctrl+Alt+M") == (shell.MOD_CONTROL | shell.MOD_ALT, ord("M"))
    assert shell.parse_hotkey(" ctrl + maj + f9 ") == (shell.MOD_CONTROL | shell.MOD_SHIFT, 0x78)
    assert shell.parse_hotkey("F13") == (0, 0x7C)
    assert shell.parse_hotkey("Pause") == (0, 0x13)
    assert shell.parse_hotkey("Win+0") == (shell.MOD_WIN, ord("0"))
    for invalid in ("", "M", "Ctrl+", "Ctrl+Truc", "Truc+M", "F25", None):
        assert shell.parse_hotkey(invalid) is None, invalid


def test_autostart_command_points_to_the_app():
    command = shell.autostart_command()
    assert command.startswith('"') and ("main.py" in command or getattr(sys, "frozen", False))


# --- fenêtres ---------------------------------------------------------------------
def test_task_window_rules():
    normal = dict(visible=True, title="Bloc-notes", ex_style=0, has_owner=False, cloaked=False,
                  class_name="Notepad")
    assert is_task_window(**normal)
    assert not is_task_window(**{**normal, "visible": False})
    assert not is_task_window(**{**normal, "title": "  "})
    assert not is_task_window(**{**normal, "cloaked": True})            # appli du Store en veille
    assert not is_task_window(**{**normal, "ex_style": 0x80})           # fenêtre outil
    assert not is_task_window(**{**normal, "has_owner": True})          # boîte de dialogue
    assert is_task_window(**{**normal, "has_owner": True, "ex_style": 0x40000})   # WS_EX_APPWINDOW
    assert not is_task_window(**{**normal, "class_name": "Shell_TrayWnd"})
    assert not is_task_window(**{**normal, "class_name": "Progman"})


def test_stable_order_keeps_buttons_in_place():
    assert stable_order([1, 2, 3], [3, 1, 2]) == [1, 2, 3]              # ordre d'empilement changé
    assert stable_order([1, 2, 3], [4, 3, 1]) == [1, 3, 4]              # 2 fermée, 4 ouverte
    assert stable_order([], [5, 6]) == [5, 6]


def test_demo_windows():
    backend = DemoWindows()
    windows = backend.windows()
    first = windows[0].hwnd
    backend.activate(first)
    assert [w.active for w in backend.windows()].count(True) == 1 and backend.windows()[0].active
    backend.minimize(first)
    assert backend.windows()[0].minimized and not backend.windows()[0].active
    backend.close(first)
    assert first not in [w.hwnd for w in backend.windows()]
    assert windows[1].app == "Discord"


# --- ancrage ----------------------------------------------------------------------
def test_every_winapi_name_used_exists():
    """Chaque « winapi.X » du code existe dans core/winapi.py. Lu sans importer le
    module (il ne se charge que sous Windows) : ce test tourne partout."""
    import ast
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "core" / "winapi.py").read_text(encoding="utf-8"))
    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        defined.add(name.id)
        elif isinstance(node, ast.Try):           # définitions selon la version de Windows
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    defined.add(sub.id)
    used = {}
    for path in [root / "main.py", *root.glob("core/*.py"), *root.glob("ui/**/*.py")]:
        for name in re.findall(r"\bwinapi\.([A-Za-z_]\w*)", path.read_text(encoding="utf-8")):
            used.setdefault(name, path.name)
    missing = {name: where for name, where in used.items() if name not in defined}
    assert not missing, f"absents de core/winapi.py : {missing}"


def test_covers_screen():
    screen = (0, 0, 1920, 1080)
    assert appbar.covers((0, 0, 1920, 1080), screen)                  # plein écran exact
    assert appbar.covers((-1, 0, 1921, 1081), screen)                 # tolérance d'un pixel
    assert not appbar.covers((0, 0, 1920, 1040), screen)              # fenêtre sans la barre des tâches
    assert not appbar.covers((100, 100, 1820, 980), screen)           # fenêtre normale
    assert not appbar.foreground_fills_screen(0)                      # hors Windows : jamais
    assert appbar.fullscreen_foreground(0) == 0


def test_fullscreen_rules():
    screen = (0, 0, 1920, 1080)
    assert appbar.is_fullscreen((0, 0, 1920, 1080), screen, style=0x80000000)    # jeu sans bord
    assert appbar.is_fullscreen((0, 0, 1920, 1080), screen, zoomed=True)         # agrandi sans titre
    # Navigateur agrandi, rien de réservé à l'écran : ses bords invisibles débordent
    assert not appbar.is_fullscreen((-8, -8, 1928, 1088), screen, style=0x00CF0000, zoomed=True)
    assert appbar.is_fullscreen((-8, -8, 1928, 1088), screen, style=0x00CF0000)  # plein écran F11
    assert not appbar.is_fullscreen((0, 0, 1920, 1080), screen, class_name="WorkerW")   # bureau
    assert not appbar.is_fullscreen((0, 0, 1280, 720), screen)


def test_find_app_matches_media_names_to_windows():
    from core.windows import WindowInfo, find_app

    windows = [WindowInfo(1, "Firefox", "C:/Apps/firefox.exe"),
               WindowInfo(2, "Spotify Premium", "C:/Apps/Spotify.exe"),
               WindowInfo(3, "Nouvel onglet", "C:/Program Files/Edge/msedge.exe")]
    assert find_app(windows, "Spotify").hwnd == 2
    assert find_app(windows, "Edge").hwnd == 3                        # « msedge »
    assert find_app(windows, "firefox").hwnd == 1
    assert find_app(windows, "Deezer") is None and find_app(windows, "") is None


def test_media_timeline_helpers():
    from datetime import datetime, timedelta, timezone

    from core.media import (MediaInfo, format_time, same_track_on_time, timeline_position,
                            to_seconds)

    assert format_time(0) == "0:00" and format_time(187.9) == "3:07"
    assert format_time(3765) == "1:02:45"
    assert to_seconds(timedelta(minutes=2)) == 120.0 and to_seconds(1_500_000_000) == 150.0
    assert to_seconds(None) == 0.0 and to_seconds(object()) == 0.0
    now = datetime(2026, 11, 17, 12, 0, 10, tzinfo=timezone.utc)
    last = now - timedelta(seconds=10)
    assert timeline_position(60, 0, 200, last, True, now) == (70.0, 200.0)   # 10 s de lecture
    assert timeline_position(60, 0, 200, last, False, now) == (60.0, 200.0)  # en pause
    assert timeline_position(195, 0, 200, last, True, now) == (200.0, 200.0)  # borné à la fin
    assert timeline_position(60, 0, 0, last.replace(tzinfo=None), True, now) == (70.0, 0.0)

    info = MediaInfo("Titre", playing=True, position=10.0, duration=100.0, updated=50.0)
    assert info.position_at(55.0) == 15.0 and info.position_at(500.0) == 100.0
    paused = MediaInfo("Titre", playing=False, position=10.0, duration=100.0, updated=50.0)
    assert paused.position_at(55.0) == 10.0
    import time

    now_s = time.monotonic()
    a = MediaInfo("Titre", playing=True, position=10.0, duration=100.0, updated=now_s - 1.0)
    b = MediaInfo("Titre", playing=True, position=11.0, duration=100.0, updated=now_s)
    assert same_track_on_time(a, b)                       # la frise avance comme prévu
    c = MediaInfo("Titre", playing=True, position=60.0, duration=100.0, updated=now_s)
    assert not same_track_on_time(a, c)                   # saut dans le morceau
    assert not same_track_on_time(a, MediaInfo("Autre", playing=True, position=11.0,
                                               duration=100.0, updated=now_s))


def test_demo_media_seeks_and_tracks_time(qapp):
    from core.media import DemoMedia

    media = DemoMedia()
    seen = []
    media.changed.connect(seen.append)
    media.start()
    assert media.current.duration == 214.0 and media.current.position_at() >= 71.0
    media.seek(100.0)
    assert abs(media.current.position_at() - 100.0) < 0.5
    media.play_pause()
    position = media.current.position_at()
    time.sleep(0.05)
    assert media.current.position_at() == position        # en pause : la frise ne bouge plus
    media.next()
    assert media.current.position_at() < 0.5 and len(seen) == 4


def test_bar_rect_and_monitor_choice():
    screen = (0, 0, 1920, 1080)
    assert appbar.bar_rect(screen, "top", 44) == (0, 0, 1920, 44)
    assert appbar.bar_rect(screen, "bottom", 44) == (0, 1036, 1920, 1080)
    assert appbar.bar_rect((1920, -200, 4480, 1240), "bottom", 55) == (1920, 1185, 4480, 1240)
    assert appbar.bar_rect(screen, "gauche", 44) == (0, 0, 1920, 44)    # bord inconnu : en haut
    monitors = [appbar.Monitor("\\\\.\\DISPLAY1", (0, 0, 1920, 1080), True),
                appbar.Monitor("\\\\.\\DISPLAY2", (1920, 0, 3840, 1080))]
    assert appbar.pick_monitor(monitors, "\\\\.\\display2") is monitors[1]
    assert appbar.pick_monitor(monitors, "") is monitors[0]
    assert appbar.pick_monitor(monitors, "débranché") is monitors[0]
    assert appbar.pick_monitor(monitors, "Écran 2", origin=(1920, 0)) is monitors[1]   # par position
    assert appbar.pick_monitor([], "") is None


@pytest.mark.skipif(sys.platform == "win32", reason="chemin hors Windows")
def test_windows_only_features_are_harmless_elsewhere(tmp_path):
    assert appbar.list_monitors() == []
    assert not appbar.set_windows_taskbar_hidden(True, tmp_path)
    assert not (tmp_path / appbar.STATE_FILENAME).exists()
    assert appbar.windows_taskbar_visible()
    assert not shell.autostart_enabled() and not shell.set_autostart(True)
    bar = appbar.AppBar(0)
    assert not bar.supported and bar.dock("top", 44) is None
