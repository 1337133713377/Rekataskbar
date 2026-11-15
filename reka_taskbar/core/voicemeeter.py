"""
Voicemeeter vu depuis la barre : Muet, volume et niveaux des canaux de REKA.

La barre parle à Voicemeeter par son API Remote (VoicemeeterRemote64.dll),
exactement comme REKA. Voicemeeter accepte plusieurs clients à la fois : tout
ce qui est réglé ici apparaît dans la console REKA au tour suivant, et un
réglage fait dans REKA remonte ici de la même façon.

Contrairement à REKA, la barre ne lance jamais Voicemeeter : elle attend
qu'il tourne, s'y connecte, et se reconnecte toute seule s'il redémarre.

- Un thread de scrutation est le seul à parler à l'API : il envoie les
  écritures demandées par l'interface (seule la dernière valeur d'un
  paramètre part), relit les paramètres quand Voicemeeter signale un
  changement, et lit les niveaux à chaque tour.
- Les résultats remontent par signaux Qt, livrés dans le thread de l'interface.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from core.reka_link import EDITIONS, Edition, RekaSetup

log = logging.getLogger(__name__)

CHANNELS_PER_BUS = 8
LEVEL_POSTFADER = 1          # types de niveaux de VBVMR_GetLevel
LEVEL_OUTPUT = 3
SILENCE_DB = -100.0
GAIN_MIN_DB, GAIN_MAX_DB = -60.0, 12.0
ECHO_GUARD_S = 0.5           # après une écriture, on garde notre valeur le temps que VM l'applique
RETRY_STOPPED_S = 2.0        # Voicemeeter fermé : nouvel essai de connexion
RETRY_MISSING_S = 15.0       # Voicemeeter pas installé
LOGIN_SETTLE_S = 0.2         # après le login, le temps que l'API ait ses premières valeurs

STATE_MISSING = "missing"        # Voicemeeter n'est pas installé (ou pas sous Windows)
STATE_STOPPED = "stopped"        # installé, mais il ne tourne pas
STATE_CONNECTED = "connected"

_KINDS = {1: "basic", 2: "banana", 3: "potato"}
_VM_UNINSTALL_KEY = "VB:Voicemeeter {17359A74-1236-5467}"


class VoicemeeterError(Exception):
    """L'API Remote a refusé un appel (Voicemeeter fermé, paramètre inconnu…)."""


class VoicemeeterMissing(VoicemeeterError):
    """Voicemeeter n'est pas installé sur cette machine."""


# --------------------------------------------------------------------------- #
# API Remote (ctypes)
# --------------------------------------------------------------------------- #
def find_remote_dll() -> Path:
    """VoicemeeterRemote64.dll, dans le dossier d'installation de Voicemeeter
    (lu dans le registre, comme le fait la doc de VB-Audio)."""
    if sys.platform != "win32":
        raise VoicemeeterMissing("Voicemeeter n'existe que sous Windows")
    import winreg

    bits64 = ctypes.sizeof(ctypes.c_void_p) == 8
    name = "VoicemeeterRemote64.dll" if bits64 else "VoicemeeterRemote.dll"
    for node in ("WOW6432Node\\", ""):
        key = f"SOFTWARE\\{node}Microsoft\\Windows\\CurrentVersion\\Uninstall\\{_VM_UNINSTALL_KEY}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                uninstall = str(winreg.QueryValueEx(handle, "UninstallString")[0]).strip('"')
        except OSError:
            continue
        dll = Path(uninstall).parent / name
        if dll.is_file():
            return dll
    raise VoicemeeterMissing("Voicemeeter n'est pas installé")


class RemoteApi:
    """Les quelques fonctions de l'API Remote dont la barre a besoin."""

    def __init__(self, dll_path: Path | None = None) -> None:
        path = dll_path or find_remote_dll()
        try:
            self._dll = ctypes.CDLL(str(path))
        except OSError as exc:
            raise VoicemeeterMissing(f"{path.name} ne se charge pas : {exc}") from exc
        c_float_p = ctypes.POINTER(ctypes.c_float)
        c_long_p = ctypes.POINTER(ctypes.c_long)
        for name, argtypes in (
                ("VBVMR_Login", ()), ("VBVMR_Logout", ()), ("VBVMR_IsParametersDirty", ()),
                ("VBVMR_GetVoicemeeterType", (c_long_p,)),
                ("VBVMR_GetVoicemeeterVersion", (c_long_p,)),
                ("VBVMR_GetParameterFloat", (ctypes.c_char_p, c_float_p)),
                ("VBVMR_SetParameterFloat", (ctypes.c_char_p, ctypes.c_float)),
                ("VBVMR_GetLevel", (ctypes.c_long, ctypes.c_long, c_float_p))):
            function = getattr(self._dll, name)
            function.argtypes = list(argtypes)
            function.restype = ctypes.c_long

    def login(self) -> bool:
        """True si Voicemeeter tourne et que la connexion est faite ; False s'il
        est fermé (la barre ne le lance pas)."""
        code = self._dll.VBVMR_Login()
        if code == 0:
            return True
        self._dll.VBVMR_Logout()     # 1 = connecté mais Voicemeeter fermé ; < 0 = refus
        return False

    def logout(self) -> None:
        self._dll.VBVMR_Logout()

    def kind(self) -> str:
        value = ctypes.c_long()
        self._check(self._dll.VBVMR_GetVoicemeeterType(ctypes.byref(value)), "GetVoicemeeterType")
        return _KINDS.get(value.value, "")

    def version(self) -> str:
        value = ctypes.c_long()
        self._check(self._dll.VBVMR_GetVoicemeeterVersion(ctypes.byref(value)), "GetVersion")
        v = value.value
        return f"{(v >> 24) & 0xFF}.{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"

    def dirty(self) -> bool:
        code = self._dll.VBVMR_IsParametersDirty()
        self._check(code, "IsParametersDirty")
        return code == 1

    def get(self, param: str) -> float:
        value = ctypes.c_float()
        self._check(self._dll.VBVMR_GetParameterFloat(param.encode("ascii"), ctypes.byref(value)),
                    param)
        return float(value.value)

    def set(self, param: str, value: float) -> None:
        self._check(self._dll.VBVMR_SetParameterFloat(param.encode("ascii"),
                                                      ctypes.c_float(float(value))), param)

    def level(self, kind: int, channel: int) -> float:
        value = ctypes.c_float()
        code = self._dll.VBVMR_GetLevel(kind, channel, ctypes.byref(value))
        if code == -3:               # pas encore de niveau disponible
            return 0.0
        self._check(code, "GetLevel")
        return float(value.value)

    @staticmethod
    def _check(code: int, what: str) -> None:
        if code < 0:
            raise VoicemeeterError(f"{what} : code {code}")


# --------------------------------------------------------------------------- #
# Valeurs échangées avec l'interface
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StripParams:
    gain: float
    mute: bool
    routes: tuple[bool, ...] = ()    # un booléen par knob de routing de REKA


@dataclass(frozen=True)
class MixerParams:
    strips: tuple[StripParams, ...]
    headphone_gain: float = 0.0
    headphone_mute: bool = False


@dataclass(frozen=True)
class MixerLevels:
    strips: tuple[tuple[float, float], ...]   # (gauche, droite) en dB, post-fader
    master: tuple[float, float] = (SILENCE_DB, SILENCE_DB)   # sortie du bus casque


def input_channel(strip: int, physical_strips: int) -> int:
    """Premier canal d'une strip dans les tableaux de niveaux : 2 canaux par
    entrée matérielle, puis 8 par entrée virtuelle."""
    if strip < physical_strips:
        return 2 * strip
    return 2 * physical_strips + 8 * (strip - physical_strips)


def amp_to_db(value: float) -> float:
    return 20.0 * math.log10(value) if value > 1e-5 else SILENCE_DB


def clamp_gain(db: float) -> float:
    """Gain envoyé à Voicemeeter : sa plage, au dixième de dB."""
    return round(max(GAIN_MIN_DB, min(GAIN_MAX_DB, float(db))), 1)


class VoicemeeterLink(QObject):
    """Connexion vivante à Voicemeeter, avec les canaux de REKA."""

    params_changed = Signal(object)      # MixerParams
    levels_changed = Signal(object)      # MixerLevels
    state_changed = Signal(str)          # STATE_*
    setup_changed = Signal(object)       # RekaSetup réellement utilisé (édition qui tourne)

    def __init__(self, setup: RekaSetup, poll_hz: float = 20.0,
                 remote_factory: Callable[[], object] = RemoteApi,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = remote_factory
        self._interval = 1.0 / max(1.0, min(60.0, float(poll_hz)))
        self._lock = threading.Lock()
        self._wanted = setup                 # réglages de REKA
        self._setup = setup                  # adaptés à l'édition qui tourne
        self._running_kind: str | None = None
        self._writes: dict[str, float] = {}
        self._must_read = True
        self._params: MixerParams | None = None
        self._state = STATE_STOPPED
        # Thread de scrutation uniquement
        self._remote = None
        self._echo: dict[str, tuple[float, float]] = {}
        self._last_levels: MixerLevels | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ état
    @property
    def state(self) -> str:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == STATE_CONNECTED

    @property
    def setup(self) -> RekaSetup:
        with self._lock:
            return self._setup

    @property
    def params(self) -> MixerParams | None:
        return self._params

    @property
    def levels(self) -> MixerLevels | None:
        """Derniers niveaux lus (None tant que Voicemeeter n'est pas connecté)."""
        return self._last_levels

    @property
    def edition(self) -> Edition:
        return self.setup.edition

    def configure(self, setup: RekaSetup) -> None:
        """Nouveaux réglages de REKA (canaux, routing, bus du casque)."""
        with self._lock:
            self._wanted = setup
            effective = setup.for_kind(self._running_kind or setup.kind)
            changed = effective != self._setup
            self._setup = effective
            self._must_read = True
        if changed:
            self.setup_changed.emit(effective)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voicemeeter-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ------------------------------------------------- commandes (thread UI)
    def set_gain(self, strip: int, db: float) -> None:
        vm = self._vm_strip(strip)
        if vm is not None:
            self._queue(f"Strip[{vm}].Gain", clamp_gain(db))

    def set_mute(self, strip: int, muted: bool) -> None:
        vm = self._vm_strip(strip)
        if vm is not None:
            self._queue(f"Strip[{vm}].Mute", 1.0 if muted else 0.0)

    def set_route(self, strip: int, route: int, enabled: bool) -> None:
        setup = self.setup
        vm = self._vm_strip(strip)
        if vm is not None and 0 <= route < len(setup.routes):
            self._queue(f"Strip[{vm}].{setup.routes[route][1]}", 1.0 if enabled else 0.0)

    def set_headphone_gain(self, db: float) -> None:
        self._queue(f"Bus[{self._headphone_index()}].Gain", clamp_gain(db))

    def set_headphone_mute(self, muted: bool) -> None:
        self._queue(f"Bus[{self._headphone_index()}].Mute", 1.0 if muted else 0.0)

    def restart_audio_engine(self) -> None:
        """Redémarre le moteur audio de Voicemeeter (son qui craque, périphérique
        rebranché) : le bouton « Restart Audio Engine » de son menu."""
        self._queue("Command.Restart", 1.0)

    def _vm_strip(self, strip: int) -> int | None:
        strips = self.setup.strips
        return strips[strip] if 0 <= strip < len(strips) else None

    def _headphone_index(self) -> int:
        setup = self.setup
        return setup.edition.buses.index(setup.headphone_bus)

    def _queue(self, param: str, value: float) -> None:
        with self._lock:
            self._writes[param] = value

    # ------------------------------------------------ thread de scrutation
    def _run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            if self._remote is None and not self._load():
                if self._stop.wait(RETRY_MISSING_S):
                    break
                continue
            if self._state != STATE_CONNECTED:
                if not self._login():
                    if self._stop.wait(RETRY_STOPPED_S):
                        break
                    continue
                next_tick = time.monotonic()
            try:
                self._tick()
            except Exception as exc:
                log.warning("Voicemeeter ne répond plus : %s", exc)
                self._disconnect()
                if self._stop.wait(RETRY_STOPPED_S):
                    break
                continue
            next_tick += self._interval
            delay = next_tick - time.monotonic()
            if delay < 0:              # du retard : on repart du temps présent
                next_tick, delay = time.monotonic(), 0.0
            self._stop.wait(delay)
        self._shutdown()

    def _load(self) -> bool:
        try:
            self._remote = self._factory()
        except VoicemeeterMissing as exc:
            if self._state != STATE_MISSING:
                log.info("Voicemeeter indisponible : %s", exc)
            self._set_state(STATE_MISSING)
            return False
        except Exception as exc:
            log.warning("API de Voicemeeter inutilisable : %s", exc)
            self._set_state(STATE_MISSING)
            return False
        self._set_state(STATE_STOPPED)
        return True

    def _login(self) -> bool:
        try:
            if not self._remote.login():
                return False
            if self._stop.wait(LOGIN_SETTLE_S):
                self._remote.logout()
                return False
            self._remote.dirty()                     # amorce la lecture des paramètres
            kind = self._remote.kind()
            version = self._remote.version()
        except Exception as exc:
            log.debug("Connexion à Voicemeeter refusée : %s", exc)
            with contextlib.suppress(Exception):
                self._remote.logout()
            return False
        if kind not in EDITIONS:
            log.warning("Édition de Voicemeeter inconnue : connexion abandonnée.")
            with contextlib.suppress(Exception):
                self._remote.logout()
            return False
        with self._lock:
            self._running_kind = kind
            effective = self._wanted.for_kind(kind)
            changed = effective != self._setup
            self._setup = effective
            self._must_read = True
        self._echo.clear()
        self._last_levels = None
        log.info("Connecté à %s %s.", EDITIONS[kind].label, version)
        if changed:
            self.setup_changed.emit(effective)
        self._set_state(STATE_CONNECTED)
        return True

    def _disconnect(self) -> None:
        with contextlib.suppress(Exception):
            self._remote.logout()
        self._set_state(STATE_STOPPED)

    def _shutdown(self) -> None:
        if self._remote is not None and self._state == STATE_CONNECTED:
            try:
                self._flush()                        # derniers gestes de l'utilisateur
            except Exception as exc:
                log.debug("Derniers réglages non envoyés : %s", exc)
            with contextlib.suppress(Exception):
                self._remote.logout()
        self._state = STATE_STOPPED

    def _tick(self) -> None:
        with self._lock:
            setup = self._setup
            must_read, self._must_read = self._must_read, False
        try:
            self._flush()
            if self._remote.dirty() or must_read or self._echo_expired():
                self._read_params(setup)
            self._read_levels(setup)
        except Exception:
            with self._lock:
                self._must_read = True
            raise

    def _flush(self) -> None:
        with self._lock:
            writes, self._writes = self._writes, {}
        expire = time.monotonic() + ECHO_GUARD_S
        pending = list(writes.items())
        try:
            while pending:
                param, value = pending[0]
                self._remote.set(param, value)
                if not param.startswith("Command."):
                    self._echo[param] = (expire, value)
                pending.pop(0)
        except Exception:
            with self._lock:           # rien de ce qui n'est pas parti n'est perdu
                for param, value in pending:
                    self._writes.setdefault(param, value)
            raise

    def _echo_expired(self) -> bool:
        """Une valeur écrite vient de sortir de sa fenêtre de garde : on relit
        pour confirmer ce que Voicemeeter a vraiment appliqué."""
        now = time.monotonic()
        return any(expire <= now for expire, _value in self._echo.values())

    def _get(self, param: str) -> float:
        echo = self._echo.get(param)
        if echo is not None:
            if echo[0] > time.monotonic():
                return echo[1]
            del self._echo[param]
        return self._remote.get(param)

    def _read_params(self, setup: RekaSetup) -> None:
        strips = []
        for vm_strip in setup.strips:
            prefix = f"Strip[{vm_strip}]"
            strips.append(StripParams(
                gain=round(self._get(f"{prefix}.Gain"), 1),
                mute=self._get(f"{prefix}.Mute") >= 0.5,
                routes=tuple(self._get(f"{prefix}.{bus}") >= 0.5 for _label, bus in setup.routes),
            ))
        bus = f"Bus[{setup.edition.buses.index(setup.headphone_bus)}]"
        params = MixerParams(strips=tuple(strips),
                             headphone_gain=round(self._get(f"{bus}.Gain"), 1),
                             headphone_mute=self._get(f"{bus}.Mute") >= 0.5)
        if params != self._params:
            self._params = params
            self.params_changed.emit(params)

    def _read_levels(self, setup: RekaSetup) -> None:
        level = self._remote.level
        physical = setup.edition.physical_strips
        strips = []
        for vm_strip in setup.strips:
            channel = input_channel(vm_strip, physical)
            strips.append((round(amp_to_db(level(LEVEL_POSTFADER, channel)), 1),
                           round(amp_to_db(level(LEVEL_POSTFADER, channel + 1)), 1)))
        base = setup.edition.buses.index(setup.headphone_bus) * CHANNELS_PER_BUS
        levels = MixerLevels(tuple(strips),
                             (round(amp_to_db(level(LEVEL_OUTPUT, base)), 1),
                              round(amp_to_db(level(LEVEL_OUTPUT, base + 1)), 1)))
        if levels != self._last_levels:
            self._last_levels = levels
            self.levels_changed.emit(levels)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            if state != STATE_CONNECTED:
                self._params = None
                self._last_levels = None
            self.state_changed.emit(state)
