"""
Bouton « Mise à jour » : n'apparaît dans la barre que lorsqu'une nouvelle
version attend d'être installée à la main (installation automatique coupée,
ou impossible dans le dossier où se trouve l'exe).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QWidget

from core.updater import STATE_AVAILABLE
from ui import styles
from ui.widgets.base import Context, Pill, Text


class UpdateWidget(Pill):
    key = "update"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self.label = Text("", size=12, weight=QFont.Weight.DemiBold)
        self.row.addSpacing(12)
        self.row.addWidget(self.label)
        self.clicked.connect(ctx.open_update)
        ctx.updates.state_changed.connect(self._refresh)
        ctx.updates.available.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args) -> None:
        updates = self._ctx.updates
        latest = updates.latest
        shown = updates.state == STATE_AVAILABLE and latest is not None
        self.set_shown(shown)
        if not shown:
            self.hide()
            return
        self.label.set_text(f"Mise à jour {latest.version}")
        self.label.set_color(styles.ink_on(styles.GREEN_NEON))
        self.set_tint(styles.GREEN_NEON)
        self.setToolTip(f"REKA Taskbar {latest.version} est disponible — clic pour l'installer")

    refresh_theme = _refresh

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(styles.color(styles.ink_on(styles.GREEN_NEON)))
        painter.setBrush(styles.color(styles.ink_on(styles.GREEN_NEON)))
        y = self.height() / 2
        painter.drawEllipse(QRectF(10, y - 3, 6, 6))

    def menu_actions(self) -> list:
        return [("Installer la mise à jour…", self._ctx.open_update)]
