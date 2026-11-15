"""
Moteurs simulés : la barre tourne sans Voicemeeter, sans REKA et hors Windows
(--demo, --selftest, tests).

FakeRemote imite l'API Remote de Voicemeeter : le vrai VoicemeeterLink
tourne par-dessus, thread de scrutation compris.
"""

from __future__ import annotations

import math
import threading
import time

from core.reka_link import EDITIONS, RekaLink, RekaSetup
from core.system import SystemMonitor, SystemStats
from core.voicemeeter import LEVEL_OUTPUT, VoicemeeterError, VoicemeeterLink, input_channel
from core.weather import Weather

DEMO_GAINS = (2.0, -9.0, -3.0, -6.0, -14.0, -20.0, 0.0, 0.0)
DEMO_ACTIVITY = (0.85, 0.6, 0.0, 0.45, 0.3, 0.0, 0.0, 0.0)   # niveau moyen de chaque canal


class FakeRemote:
    """Voicemeeter en mémoire : paramètres, niveaux animés, marche / arrêt."""

    def __init__(self, kind: str = "potato", running: bool = True, animate: bool = True) -> None:
        self.kind_name = kind
        self.running = running
        self.animate = animate
        self.logged_in = False
        self.sets: list[tuple[str, float]] = []      # écritures reçues, dans l'ordre
        self._lock = threading.Lock()
        self._dirty = True
        self._params: dict[str, float] = {}
        ed = EDITIONS[kind]
        for strip in range(ed.strip_count):
            self._params[f"Strip[{strip}].Gain"] = 0.0
            self._params[f"Strip[{strip}].Mute"] = 0.0
            for bus in ed.buses:
                self._params[f"Strip[{strip}].{bus}"] = 1.0 if bus == ed.buses[0] else 0.0
        for bus in range(len(ed.buses)):
            self._params[f"Bus[{bus}].Gain"] = 0.0
            self._params[f"Bus[{bus}].Mute"] = 0.0

    # --- API Remote ---------------------------------------------------------
    def login(self) -> bool:
        self.logged_in = self.running
        return self.running

    def logout(self) -> None:
        self.logged_in = False

    def kind(self) -> str:
        self._check()
        return self.kind_name

    def version(self) -> str:
        return "3.1.1.9"

    def dirty(self) -> bool:
        self._check()
        with self._lock:
            dirty, self._dirty = self._dirty, False
        return dirty

    def get(self, param: str) -> float:
        self._check()
        with self._lock:
            if param not in self._params:
                raise VoicemeeterError(f"{param} : code -3")
            return self._params[param]

    def set(self, param: str, value: float) -> None:
        self._check()
        with self._lock:
            self.sets.append((param, float(value)))
            if not param.startswith("Command."):
                self._params[param] = float(value)
                self._dirty = True

    def level(self, kind: int, channel: int) -> float:
        self._check()
        ed = EDITIONS[self.kind_name]
        t = time.monotonic() if self.animate else 0.37
        if kind == LEVEL_OUTPUT:
            bus = channel // 8
            total = sum(self._strip_amp(s, 0, t) for s in range(ed.strip_count)
                        if self.peek(f"Strip[{s}].{ed.buses[bus]}") >= 0.5)
            gain = 10 ** (self.peek(f"Bus[{bus}].Gain") / 20)
            return 0.0 if self.peek(f"Bus[{bus}].Mute") >= 0.5 else min(1.4, total * 0.6 * gain)
        for strip in range(ed.strip_count):
            first = input_channel(strip, ed.physical_strips)
            if channel in (first, first + 1):
                return self._strip_amp(strip, channel - first, t)
        return 0.0

    # --- Pour la démo et les tests ------------------------------------------
    def peek(self, param: str) -> float:
        with self._lock:
            return self._params.get(param, 0.0)

    def poke(self, param: str, value: float) -> None:
        """Réglage fait « ailleurs » (dans REKA, dans Voicemeeter)."""
        with self._lock:
            self._params[param] = float(value)
            self._dirty = True

    def _strip_amp(self, strip: int, side: int, t: float) -> float:
        if self.peek(f"Strip[{strip}].Mute") >= 0.5:
            return 0.0
        activity = DEMO_ACTIVITY[strip % len(DEMO_ACTIVITY)]
        if activity <= 0:
            return 0.0
        wave = 0.5 + 0.5 * math.sin(t * (2.1 + strip * 0.7) + strip + side * 0.4)
        burst = 0.6 + 0.4 * math.sin(t * 7.3 + strip * 2.0)
        gain = 10 ** (self.peek(f"Strip[{strip}].Gain") / 20)
        return activity * (0.35 + 0.65 * wave * burst) * gain * 0.5

    def _check(self) -> None:
        if not self.running or not self.logged_in:
            raise VoicemeeterError("code -2")


def demo_setup() -> RekaSetup:
    return RekaSetup(found=True)


def demo_remote(setup: RekaSetup | None = None, animate: bool = True) -> FakeRemote:
    """Voicemeeter simulé, avec les volumes de la démo de REKA."""
    setup = setup or demo_setup()
    remote = FakeRemote(setup.kind, animate=animate)
    for index, vm_strip in enumerate(setup.strips):
        remote.poke(f"Strip[{vm_strip}].Gain", DEMO_GAINS[index % len(DEMO_GAINS)])
        for label, bus in setup.routes:
            remote.poke(f"Strip[{vm_strip}].{bus}",
                        1.0 if label == "Monitor" or (index == 0 and label != "Obs") else 0.0)
    remote.poke(f"Strip[{setup.strips[2]}].Mute", 1.0)
    return remote


def demo_link(setup: RekaSetup | None = None, animate: bool = True,
              poll_hz: float = 30.0) -> tuple[VoicemeeterLink, FakeRemote]:
    setup = setup or demo_setup()
    remote = demo_remote(setup, animate)
    return VoicemeeterLink(setup, poll_hz, remote_factory=lambda: remote), remote


class DemoRekaLink(RekaLink):
    """REKA simulée : « ouverte », sans rien lire ni lancer."""

    def __init__(self, cfg: dict, setup: RekaSetup | None = None, running: bool = True) -> None:
        super().__init__(cfg)
        self._setup = setup or demo_setup()
        self._demo_running = running
        self._running = running
        self.shown = 0

    def refresh(self) -> None:
        pass

    def _probe_running(self) -> bool:
        return self._demo_running

    def show(self) -> bool:
        self.shown += 1
        return self._demo_running

    def launch(self) -> bool:
        self._demo_running = self._running = True
        self.running_changed.emit(True)
        return True


class DemoSystem(SystemMonitor):
    def __init__(self, animate: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self._animate = animate

    def _read(self) -> SystemStats:
        t = time.monotonic() if self._animate else 0.0
        return SystemStats(cpu=18 + 10 * math.sin(t / 3), ram=47.0,
                           ram_used=round(7.5 * 1024 ** 3), ram_total=16 * 1024 ** 3,
                           down=2.4e6 * (1 + 0.5 * math.sin(t / 2)), up=180e3,
                           battery=82.0, plugged=False, seconds_left=3 * 3600 + 12 * 60)


def demo_weather(city: str) -> Weather:
    return Weather(city=city or "Paris", temperature=17.4, code=2, is_day=True, low=11.0, high=19.0)
