"""
Bouton « Mise à jour » : n'apparaît dans la barre que lorsqu'une mise à jour
est en cours ou attend l'utilisateur.

- téléchargement automatique : « Mise à jour 1.2.0 · 42 % » ;
- prête (en attente que tu aies fini : menu, réglages, jeu plein écran) :
  « 1.2.0 prête » ; un clic l'installe tout de suite ;
- à installer à la main (installation automatique coupée, ou impossible dans
  le dossier de l'exe) : « Mise à jour 1.2.0 » ; un clic ouvre la fenêtre.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QWidget

from core.updater import STATE_AVAILABLE, STATE_DOWNLOADING, STATE_READY
from ui import styles
from ui.widgets.base import Context, Pill, Text


class UpdateWidget(Pill):
    key = "update"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._percent = 0
        self.label = Text("", size=12, weight=QFont.Weight.DemiBold)
        self.row.addSpacing(12)
        self.row.addWidget(self.label)
        self.clicked.connect(ctx.open_update)
        ctx.updates.state_changed.connect(self._refresh)
        ctx.updates.available.connect(self._refresh)
        ctx.updates.progress.connect(self._on_progress)
        self._refresh()

    @property
    def mode(self) -> str | None:
        """État montré : « downloading », « ready », « available » ou None (caché)."""
        updates = self._ctx.updates
        if updates.latest is None:
            return None
        return updates.state if updates.state in (STATE_DOWNLOADING, STATE_READY,
                                                  STATE_AVAILABLE) else None

    def _on_progress(self, percent: int) -> None:
        self._percent = percent
        self._refresh()

    def _refresh(self, *_args) -> None:
        mode = self.mode
        self.set_shown(mode is not None)
        if mode is None:
            self.hide()
            return
        version = self._ctx.updates.latest.version
        if mode == STATE_DOWNLOADING:
            self.label.set_text(f"Mise à jour {version} · {self._percent} %")
            self.label.set_color(styles.TEXT_PRIMARY)
            self.set_tint(None)
            self.setToolTip(f"Téléchargement de REKA Taskbar {version} : la barre "
                            "l'installera et redémarrera toute seule.")
        elif mode == STATE_READY:
            self.label.set_text(f"{version} prête")
            self.label.set_color(styles.ink_on(styles.GREEN_NEON))
            self.set_tint(styles.GREEN_NEON)
            self.setToolTip(f"REKA Taskbar {version} est prête : elle s'installe dès que tu ne "
                            "te sers plus de la barre ni d'un jeu en plein écran.\n"
                            "Clic : installer maintenant (la barre redémarre en 2 secondes).")
        else:
            self.label.set_text(f"Mise à jour {version}")
            self.label.set_color(styles.ink_on(styles.GREEN_NEON))
            self.set_tint(styles.GREEN_NEON)
            self.setToolTip(f"REKA Taskbar {version} est disponible — clic pour l'installer")
        self.updateGeometry()

    refresh_theme = _refresh

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        if self.mode == STATE_DOWNLOADING:
            # Anneau de progression à la place de la pastille
            rect = QRectF(8, y - 5, 10, 10)
            painter.setPen(styles.color(styles.GREEN_SCALE))
            painter.drawEllipse(rect)
            pen = painter.pen()
            pen.setColor(styles.color(styles.GREEN_NEON))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -round(self._percent * 3.6 * 16))
            return
        ink = styles.color(styles.ink_on(styles.GREEN_NEON))
        painter.setPen(ink)
        painter.setBrush(ink)
        painter.drawEllipse(QRectF(10, y - 3, 6, 6))

    def menu_actions(self) -> list:
        mode = self.mode
        if mode == STATE_READY:
            return [("Installer maintenant", self._ctx.open_update)]
        if mode == STATE_AVAILABLE:
            return [("Installer la mise à jour…", self._ctx.open_update)]
        return []
