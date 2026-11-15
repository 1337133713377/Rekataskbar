"""
Fenêtres volantes de la barre (mini-console, calendrier) : un cadre arrondi
qui s'ouvre contre la barre, sous elle ou au-dessus selon le bord où elle est,
et se ferme au premier clic ailleurs.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QMenu, QVBoxLayout, QWidget

GAP = 8
MARGIN = 8


def place(anchor: QRect, size: QSize, screen: QRect) -> QPoint:
    """Coin haut-gauche d'une fenêtre volante de taille `size` ouverte contre
    `anchor` (coordonnées globales) : centrée sur lui, du côté où il y a de la
    place, sans sortir de l'écran."""
    below = anchor.center().y() < screen.center().y()
    y = anchor.bottom() + 1 + GAP if below else anchor.top() - GAP - size.height()
    x = anchor.center().x() - size.width() // 2
    x = max(screen.left() + MARGIN, min(x, screen.right() + 1 - MARGIN - size.width()))
    y = max(screen.top() + MARGIN, min(y, screen.bottom() + 1 - MARGIN - size.height()))
    return QPoint(x, y)


def show_menu(menu: QMenu, position: QPoint) -> None:
    """Ouvre un menu depuis la barre. La barre ne prend jamais le focus : sans
    activation, Windows ne préviendrait pas le menu d'un clic dans une autre
    application et il resterait ouvert (même recette que le menu d'une icône
    de la zone de notification)."""
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    menu.popup(position)
    menu.activateWindow()


class Popup(QWidget):
    """Fenêtre volante : `self.body` reçoit le contenu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("popupFrame")
        outer.addWidget(self.frame)
        self.body = QVBoxLayout(self.frame)
        self.body.setContentsMargins(14, 14, 14, 14)
        self.body.setSpacing(10)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def show_near(self, anchor: QWidget) -> None:
        self.adjustSize()
        rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        screen = anchor.screen() or QGuiApplication.primaryScreen()
        area = screen.geometry() if screen is not None else QRect(0, 0, 1920, 1080)
        self.move(place(rect, self.sizeHint(), area))
        self.show()
        self.raise_()
        self.activateWindow()
