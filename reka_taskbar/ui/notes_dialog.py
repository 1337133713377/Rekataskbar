"""Fenêtre « Nouveautés » : ce qui a changé dans les dernières versions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout

from core import config
from core.release_notes import as_markdown, load_notes, notes_between


class NotesDialog(QDialog):
    def __init__(self, since: str | None = None, text: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Nouveautés — {config.APP_NAME}")
        self.setMinimumSize(520, 360)
        chosen = notes_between(load_notes() if text is None else text, since, config.APP_VERSION)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel(f"{config.APP_NAME} {config.APP_VERSION}"
                       + (f" — nouveautés depuis la {since}" if since else " — nouveautés"))
        title.setObjectName("title")
        layout.addWidget(title)
        self.body = QLabel(as_markdown(chosen) or "Pas de notes pour cette version.")
        self.body.setTextFormat(Qt.TextFormat.MarkdownText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.body)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("OK")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.versions = [version for version, _body in chosen]
