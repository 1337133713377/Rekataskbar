"""
Météo de la ville choisie dans les réglages (Open-Meteo, sans clé ni compte).

Seul le nom de la ville part sur Internet, et seulement s'il est renseigné :
sans ville, aucune requête n'est faite et le widget reste caché.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 8
RETRY_MS = 60_000             # après un échec (pas de réseau au démarrage…)
USER_AGENT = "taskbar-weather-widget"

# Codes météo de l'OMM → (description, icône)
_CODES = {
    0: ("Ciel dégagé", "sun"), 1: ("Peu nuageux", "partly"), 2: ("Partiellement nuageux", "partly"),
    3: ("Couvert", "cloud"), 45: ("Brouillard", "fog"), 48: ("Brouillard givrant", "fog"),
    51: ("Bruine légère", "rain"), 53: ("Bruine", "rain"), 55: ("Bruine forte", "rain"),
    56: ("Bruine verglaçante", "rain"), 57: ("Bruine verglaçante", "rain"),
    61: ("Pluie faible", "rain"), 63: ("Pluie", "rain"), 65: ("Pluie forte", "rain"),
    66: ("Pluie verglaçante", "rain"), 67: ("Pluie verglaçante", "rain"),
    71: ("Neige faible", "snow"), 73: ("Neige", "snow"), 75: ("Neige forte", "snow"),
    77: ("Grains de neige", "snow"), 80: ("Averses", "rain"), 81: ("Averses", "rain"),
    82: ("Averses violentes", "rain"), 85: ("Averses de neige", "snow"),
    86: ("Averses de neige", "snow"), 95: ("Orage", "storm"), 96: ("Orage et grêle", "storm"),
    99: ("Orage et grêle", "storm"),
}


@dataclass(frozen=True)
class Weather:
    city: str
    temperature: float
    code: int = 0
    is_day: bool = True
    low: float | None = None
    high: float | None = None

    @property
    def description(self) -> str:
        return _CODES.get(self.code, ("", "cloud"))[0]

    @property
    def icon(self) -> str:
        icon = _CODES.get(self.code, ("", "cloud"))[1]
        return "moon" if icon == "sun" and not self.is_day else icon


def _get_json(url: str, params: dict) -> dict:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_weather(city: str, forecast: dict) -> Weather:
    """Réponse d'Open-Meteo → Weather (lève ValueError si elle est incomplète)."""
    try:
        current = forecast["current"]
        daily = forecast.get("daily") or {}
        lows, highs = daily.get("temperature_2m_min") or [], daily.get("temperature_2m_max") or []
        return Weather(city=city, temperature=float(current["temperature_2m"]),
                       code=int(current.get("weather_code", 0)),
                       is_day=bool(current.get("is_day", 1)),
                       low=float(lows[0]) if lows else None,
                       high=float(highs[0]) if highs else None)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"réponse météo incomplète : {exc}") from exc


def fetch_weather(city: str, get_json: Callable[[str, dict], dict] = _get_json) -> Weather:
    """Cherche la ville puis sa météo du moment (bloquant : à appeler d'un thread)."""
    places = get_json(GEOCODING_URL, {"name": city, "count": 1, "language": "fr"}).get("results")
    if not places:
        raise LookupError(f"ville « {city} » introuvable")
    place = places[0]
    forecast = get_json(FORECAST_URL, {
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min",
        "forecast_days": 1, "timezone": "auto"})
    return parse_weather(str(place.get("name") or city), forecast)


class WeatherService(QObject):
    """Météo relue régulièrement dans un thread ; `changed` (Weather ou None)."""

    changed = Signal(object)
    _fetched = Signal(str, object)       # (ville demandée, Weather ou message d'erreur)

    def __init__(self, city: str = "", refresh_min: float = 20,
                 fetch: Callable[[str], Weather] = fetch_weather,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._city = city.strip()
        self._fetch = fetch
        self._weather: Weather | None = None
        self.error = ""
        self._refresh_ms = round(max(5.0, float(refresh_min)) * 60_000)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self._fetched.connect(self._on_fetched)

    @property
    def city(self) -> str:
        return self._city

    @property
    def weather(self) -> Weather | None:
        return self._weather

    def set_city(self, city: str) -> None:
        city = city.strip()
        if city == self._city:
            return
        self._city, self.error = city, ""
        if self._weather is not None:
            self._weather = None
            self.changed.emit(None)
        self.refresh()

    def start(self) -> None:
        self.refresh()

    def stop(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        self._timer.stop()
        if not self._city:
            return
        city = self._city

        def work() -> None:
            try:
                result: object = self._fetch(city)
            except Exception as exc:
                result = str(exc) or type(exc).__name__
            try:
                self._fetched.emit(city, result)
            except RuntimeError:          # application fermée entre-temps
                pass

        threading.Thread(target=work, name="weather", daemon=True).start()

    def _on_fetched(self, city: str, result: object) -> None:
        if city != self._city:            # ville changée pendant la requête
            return
        if isinstance(result, Weather):
            self.error = ""
            self._timer.start(self._refresh_ms)
            if result != self._weather:
                self._weather = result
                self.changed.emit(result)
        else:
            self.error = str(result)
            log.info("Météo indisponible : %s", self.error)
            self._timer.start(RETRY_MS)
            self.changed.emit(self._weather)
