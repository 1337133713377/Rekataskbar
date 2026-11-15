"""
Icône d'une application d'après le chemin de son exécutable (ou d'un
raccourci, d'un dossier) : celle que montre l'Explorateur, sinon une pastille
avec son initiale.
"""

from __future__ import annotations

import zlib
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from ui import styles

_AVATAR_COLORS = ("#3b82f6", "#22c55e", "#f59e0b", "#ec4899", "#a855f7", "#06b6d4", "#ef4444")
_cache: dict[tuple[str, str, int, float], QPixmap] = {}
_provider: QFileIconProvider | None = None


def avatar(label: str, size: int, ratio: float = 1.0) -> QPixmap:
    """Pastille de couleur avec l'initiale de `label`."""
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = _AVATAR_COLORS[zlib.crc32(label.lower().encode("utf-8")) % len(_AVATAR_COLORS)]
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)
    painter.setPen(QColor(styles.WHITE))
    painter.setFont(styles.font(round(size * 0.56), QFont.Weight.DemiBold))
    letter = next((c for c in label if c.isalnum()), "?").upper()
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return pixmap


def app_pixmap(path: str, label: str, size: int, ratio: float = 1.0) -> QPixmap:
    """Icône de `path` en `size` pixels ; pastille à l'initiale de `label` si
    le fichier n'a pas d'icône lisible (processus protégé, fichier absent)."""
    global _provider
    key = (path, label if not path else "", size, ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    pixmap = QPixmap()
    if path and Path(path).exists():
        if _provider is None:
            _provider = QFileIconProvider()
        icon = _provider.icon(QFileInfo(path))
        if not icon.isNull():
            pixmap = icon.pixmap(QSize(size, size), ratio)
    if pixmap.isNull():
        pixmap = avatar(label or Path(path).stem or "?", size, ratio)
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = pixmap
    return pixmap
