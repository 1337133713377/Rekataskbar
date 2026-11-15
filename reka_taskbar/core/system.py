"""
État de la machine : processeur, mémoire, débit réseau, batterie (psutil).

Un QTimer relève les compteurs dans le thread de l'interface : ces lectures
ne bloquent pas (quelques dizaines de microsecondes).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 1.5


@dataclass(frozen=True)
class SystemStats:
    cpu: float = 0.0                  # % d'utilisation, tous cœurs confondus
    ram: float = 0.0                  # % de mémoire utilisée
    ram_used: int = 0                 # octets
    ram_total: int = 0
    down: float = 0.0                 # octets par seconde reçus
    up: float = 0.0                   # octets par seconde envoyés
    battery: float | None = None      # %, None sans batterie
    plugged: bool = True
    seconds_left: int | None = None   # autonomie estimée


def format_rate(bytes_per_s: float) -> str:
    """Débit lisible : « 840 o/s », « 12 ko/s », « 3,4 Mo/s »."""
    value = max(0.0, float(bytes_per_s))
    if value < 1024:
        return f"{value:.0f} o/s"
    text = ""
    for unit in ("ko/s", "Mo/s", "Go/s"):
        value /= 1024
        text = (f"{value:.1f}" if value < 10 else f"{value:.0f}").replace(".", ",") + f" {unit}"
        if value < 1000:
            break
    return text


def format_bytes(count: int) -> str:
    """Quantité de mémoire : « 7,8 Go »."""
    return f"{count / 1024 ** 3:.1f}".replace(".", ",") + " Go"


def format_duration(seconds: int) -> str:
    hours, minutes = divmod(max(0, int(seconds)) // 60, 60)
    return f"{hours} h {minutes:02d}" if hours else f"{minutes} min"


class SystemMonitor(QObject):
    """Publie un SystemStats à intervalle régulier (signal `changed`)."""

    changed = Signal(object)
    available = True

    def __init__(self, interval_s: float = DEFAULT_INTERVAL_S,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stats = SystemStats()
        self._net: tuple[float, int, int] | None = None   # (instant, reçus, envoyés)
        self._timer = QTimer(self)
        self._timer.setInterval(round(max(0.5, float(interval_s)) * 1000))
        self._timer.timeout.connect(self.sample)

    @property
    def stats(self) -> SystemStats:
        return self._stats

    def start(self) -> None:
        self.sample()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def sample(self) -> None:
        try:
            stats = self._read()
        except Exception as exc:      # compteur indisponible : on garde la dernière mesure
            log.debug("État du système illisible : %s", exc)
            return
        self._stats = stats
        self.changed.emit(stats)

    def _read(self) -> SystemStats:
        import psutil

        memory = psutil.virtual_memory()
        now = time.monotonic()
        counters = psutil.net_io_counters()
        down = up = 0.0
        if counters is not None:
            if self._net is not None and now > self._net[0]:
                span = now - self._net[0]
                down = max(0.0, (counters.bytes_recv - self._net[1]) / span)
                up = max(0.0, (counters.bytes_sent - self._net[2]) / span)
            self._net = (now, counters.bytes_recv, counters.bytes_sent)
        battery = None
        plugged, left = True, None
        sensors = getattr(psutil, "sensors_battery", None)
        info = sensors() if sensors is not None else None
        if info is not None:
            battery = float(info.percent)
            plugged = bool(info.power_plugged)
            left = int(info.secsleft) if info.secsleft and info.secsleft > 0 else None
        return SystemStats(cpu=float(psutil.cpu_percent(None)), ram=float(memory.percent),
                           ram_used=int(memory.total - memory.available),
                           ram_total=int(memory.total), down=down, up=up,
                           battery=battery, plugged=plugged, seconds_left=left)
