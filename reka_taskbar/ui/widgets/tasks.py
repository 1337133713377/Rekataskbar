"""
Fenêtres ouvertes : un bouton par fenêtre, comme dans la barre de Windows.

Clic : afficher la fenêtre, réduite ou non (ou la réduire si elle est déjà
devant). Clic du milieu : la fermer. Les boutons qui ne tiennent pas dans la
largeur disponible sont repliés derrière un compteur « +3 » : un clic dessus
liste ces fenêtres, pour les afficher. Un bouton « ▾ 2 » apparaît dès qu'une
fenêtre est réduite : il liste toutes les applications réduites pour les
rouvrir une à une, ou toutes d'un coup.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QWidget

from core.windows import WindowInfo
from ui import styles
from ui.popup import show_menu
from ui.widgets.appicon import app_pixmap
from ui.widgets.base import Context, Text

POLL_MS = 500
BUTTON_SIZE = 34
ICON = 20
LABEL_WIDTH = 120


class TaskButton(QWidget):
    activated = Signal(int)          # clic gauche
    closed = Signal(int)             # clic du milieu
    minimized = Signal(int)

    def __init__(self, info: WindowInfo, labels: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self._labels = labels
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(BUTTON_SIZE + (LABEL_WIDTH if labels else 0))
        self.setToolTip(info.title)

    def set_info(self, info: WindowInfo) -> None:
        if info != self.info:
            self.info = info
            self.setToolTip(info.title)
            self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self.rect().contains(event.position().toPoint()):
            event.ignore()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.info.hwnd)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.closed.emit(self.info.hwnd)
        else:
            event.ignore()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.addAction("Afficher", lambda: self.activated.emit(self.info.hwnd)
                       ).setEnabled(not self.info.active)
        menu.addAction("Réduire", lambda: self.minimized.emit(self.info.hwnd)
                       ).setEnabled(not self.info.minimized)
        menu.addSeparator()
        menu.addAction("Fermer la fenêtre", lambda: self.closed.emit(self.info.hwnd))
        show_menu(menu, event.globalPos())
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        info = self.info
        if info.active or self._hover:
            painter.setPen(QColor(styles.BORDER_COLUMN) if info.active else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(styles.BUTTON_HOVER if self._hover else styles.BG_COLUMN))
            painter.drawRoundedRect(rect, 7, 7)
        x = (BUTTON_SIZE - ICON) / 2
        y = (self.height() - ICON) / 2 - 1
        pixmap = app_pixmap(info.exe, info.app, ICON, self.devicePixelRatioF())
        painter.setOpacity(0.55 if info.minimized else 1.0)
        painter.drawPixmap(QRectF(x, y, ICON, ICON), pixmap, QRectF(pixmap.rect()))
        painter.setOpacity(1.0)
        if self._labels:
            font = styles.font(12, QFont.Weight.Medium if info.active else QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor(styles.TEXT_PRIMARY if info.active else styles.TEXT_SECONDARY))
            text_rect = QRectF(BUTTON_SIZE - 2, 0, self.width() - BUTTON_SIZE - 6, self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             QFontMetrics(font).elidedText(info.title, Qt.TextElideMode.ElideRight,
                                                           int(text_rect.width())))
        # Repère sous l'icône : large et coloré pour la fenêtre active, discret sinon
        width = 14 if info.active else 5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(styles.GREEN_NEON if info.active else styles.TEXT_MUTED))
        painter.drawRoundedRect(QRectF(BUTTON_SIZE / 2 - width / 2, self.height() - 5, width, 3),
                                1.5, 1.5)


class OverflowButton(Text):
    """Compteur « +3 » des fenêtres qui ne tiennent pas dans la barre ; un
    clic ouvre leur liste."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", role="TEXT_SECONDARY", size=11, weight=QFont.Weight.DemiBold,
                         parent=parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width() + 10, hint.height())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept() if event.button() == Qt.MouseButton.LeftButton else event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()
        else:
            event.ignore()


class TasksWidget(QWidget):
    key = "tasks"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._backend = ctx.windows
        self._labels = bool(ctx.widget_cfg("tasks").get("labels", False))
        self._buttons: dict[int, TaskButton] = {}
        self._order: list[int] = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(2)
        self.overflow = OverflowButton()
        self.overflow.clicked.connect(self.show_overflow)
        self._row.addWidget(self.overflow)
        self.minimized_button = OverflowButton()
        self.minimized_button.clicked.connect(self.show_minimized)
        self._row.addWidget(self.minimized_button)
        self._row.addStretch(1)
        self.overflow.hide()
        self.minimized_button.hide()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)
        if self._backend.available:
            self._timer.start()
            self.refresh()
        else:
            self.hide()

    @property
    def buttons(self) -> list[TaskButton]:
        return [self._buttons[hwnd] for hwnd in self._order]

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(BUTTON_SIZE, BUTTON_SIZE - 4)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = sum(b.width() + 2 for b in self._buttons.values())
        return QSize(max(BUTTON_SIZE, width), BUTTON_SIZE - 2)

    def refresh(self) -> None:
        if not self.window().updatesEnabled():
            return                      # barre cachée derrière un jeu : rien à montrer
        windows = self._backend.windows()
        order = [w.hwnd for w in windows]
        for hwnd in [h for h in self._buttons if h not in set(order)]:
            button = self._buttons.pop(hwnd)
            self._row.removeWidget(button)
            button.deleteLater()
        for info in windows:
            button = self._buttons.get(info.hwnd)
            if button is None:
                button = TaskButton(info, self._labels, self)
                button.activated.connect(self._activate)
                button.closed.connect(self._close)
                button.minimized.connect(self._minimize)
                self._buttons[info.hwnd] = button
            else:
                button.set_info(info)
        if order != self._order:
            self._order = order
            for position, hwnd in enumerate(order):      # l'ordre des fenêtres, puis « +N »
                self._row.insertWidget(position, self._buttons[hwnd])
            self.updateGeometry()
        self._fit()
        self._update_minimized()

    def _update_minimized(self) -> None:
        reduced = self.minimized_windows
        self.minimized_button.set_text(f"▾ {len(reduced)}")
        self.minimized_button.setToolTip(
            "Applications réduites :\n" + "\n".join(i.title for i in reduced)
            + "\nClic : en rouvrir une, ou toutes")
        self.minimized_button.setVisible(bool(reduced))

    @property
    def minimized_windows(self) -> list[WindowInfo]:
        return [b.info for b in self.buttons if b.info.minimized]

    def minimized_menu(self) -> QMenu:
        menu = QMenu(self)
        reduced = self.minimized_windows
        for info in reduced:
            pixmap = app_pixmap(info.exe, info.app, 16, self.devicePixelRatioF())
            label = info.title if len(info.title) <= 60 else info.title[:59] + "…"
            action = menu.addAction(QIcon(pixmap), label)
            action.triggered.connect(lambda _checked=False, h=info.hwnd: self._activate(h))
        if len(reduced) > 1:
            menu.addSeparator()
            menu.addAction("Tout rouvrir", self.restore_all)
        return menu

    def show_minimized(self) -> None:
        menu = self.minimized_menu()
        if menu.actions():
            below = self.minimized_button.mapToGlobal(self.minimized_button.rect().bottomLeft())
            show_menu(menu, below)

    def restore_all(self) -> None:
        """Rouvre toutes les fenêtres réduites (la première de la barre finit devant)."""
        for info in reversed(self.minimized_windows):
            self._backend.activate(info.hwnd)
        self.refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Montre les boutons qui tiennent dans la largeur ; les autres sont
        comptés dans « +N » (la fenêtre active reste toujours visible)."""
        available = self.width()
        buttons = self.buttons
        total = sum(b.width() + 2 for b in buttons)
        if total <= available or not buttons:
            for button in buttons:
                button.show()
            self.overflow.hide()
            return
        room = available - 34 - (self.minimized_button.sizeHint().width()
                                 if self.minimized_windows else 0)   # compteurs
        shown: list[TaskButton] = []
        used = 0
        active = next((b for b in buttons if b.info.active), None)
        if active is not None:
            used += active.width() + 2
        for button in buttons:
            if button is active:
                shown.append(button)
            elif used + button.width() + 2 <= room:
                used += button.width() + 2
                shown.append(button)
        for button in buttons:
            button.setVisible(button in shown)
        hidden = len(buttons) - len(shown)
        self.overflow.set_text(f"+{hidden}")
        self.overflow.setToolTip("\n".join(b.info.title for b in buttons if b not in shown)
                                 + "\nClic : afficher une de ces fenêtres")
        self.overflow.setVisible(hidden > 0)

    @property
    def hidden_windows(self) -> list[WindowInfo]:
        """Fenêtres repliées derrière « +N »."""
        return [b.info for b in self.buttons if not b.isVisible()]

    def overflow_menu(self) -> QMenu:
        menu = QMenu(self)
        for info in self.hidden_windows:
            pixmap = app_pixmap(info.exe, info.app, 16, self.devicePixelRatioF())
            label = info.title if len(info.title) <= 60 else info.title[:59] + "…"
            if info.minimized:
                label += "  (réduite)"
            action = menu.addAction(QIcon(pixmap), label)
            action.triggered.connect(lambda _checked=False, h=info.hwnd: self._activate(h))
        return menu

    def show_overflow(self) -> None:
        menu = self.overflow_menu()
        if menu.actions():
            below = self.overflow.mapToGlobal(self.overflow.rect().bottomLeft())
            show_menu(menu, below)

    def _activate(self, hwnd: int) -> None:
        button = self._buttons.get(hwnd)
        if button is None:
            return
        if button.info.active:
            self._backend.minimize(hwnd)
        else:
            self._backend.activate(hwnd)
        self.refresh()

    def _minimize(self, hwnd: int) -> None:
        self._backend.minimize(hwnd)
        self.refresh()

    def _close(self, hwnd: int) -> None:
        self._backend.close(hwnd)
        QTimer.singleShot(150, self.refresh)

    def menu_actions(self) -> list:
        return []
