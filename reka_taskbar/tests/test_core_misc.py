"""Système, météo, raccourcis Windows, fenêtres, ancrage."""

import sys

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
def test_covers_screen():
    screen = (0, 0, 1920, 1080)
    assert appbar.covers((0, 0, 1920, 1080), screen)                  # plein écran exact
    assert appbar.covers((-1, 0, 1921, 1081), screen)                 # tolérance d'un pixel
    assert not appbar.covers((0, 0, 1920, 1040), screen)              # fenêtre sans la barre des tâches
    assert not appbar.covers((100, 100, 1820, 980), screen)           # fenêtre normale
    assert not appbar.foreground_fills_screen(0)                      # hors Windows : jamais


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
