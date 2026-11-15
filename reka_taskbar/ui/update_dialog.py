"""
Fenêtre « Mise à jour disponible » : version en ligne, nouveautés, puis au
choix installation (téléchargement vérifié, remplacement de l'exe,
redémarrage), téléchargement dans le navigateur, plus tard, ou ignorer cette
version. Utilisée quand l'installation automatique est coupée ou a échoué.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from core import config
from core.updater import UpdateError, UpdateInfo, download, install, update_dir

log = logging.getLogger(__name__)


class _Downloader(QObject):
    progress = Signal(int, int)
    finished = Signal(object)        # Path de l'exe vérifié
    failed = Signal(str)

    def __init__(self, update: UpdateInfo) -> None:
        super().__init__()
        self._update = update
        self._cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="update-download", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        dest = update_dir() / f"REKA-Taskbar-{self._update.version}.exe"
        try:
            path = download(self._update, dest, self.progress.emit, self._cancel.is_set)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(path)


class UpdateDialog(QDialog):
    """Après exec() : `installed` (le nouvel exe est en place, il faut
    redémarrer) ou `skipped` (ignorer cette version)."""

    def __init__(self, update: UpdateInfo, current: str, self_update: bool,
                 error: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Mise à jour — {config.APP_NAME}")
        self.setMinimumWidth(520)
        self.update_info = update
        self.installed = False
        self.skipped = False
        self._downloader: _Downloader | None = None
        self._self_update = self_update

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        header = QHBoxLayout()
        logo = QLabel()
        pixmap = QPixmap(str(config.resource_path("assets/reka_mark.png")))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(30, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(logo)
        title = QLabel(f"{config.APP_NAME} {update.version} est disponible")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        versions = QLabel(f"Installée : {current}")
        versions.setObjectName("secondary")
        layout.addWidget(versions)
        if update.notes:
            notes = QLabel(update.notes)
            notes.setWordWrap(True)
            notes.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(notes)

        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.setText(
            (f"La mise à jour automatique n'a pas abouti : {error}\n" if error else "")
            + ("La barre va télécharger la nouvelle version, la vérifier, puis redémarrer "
               "dessus. Tes réglages sont conservés." if self_update else
               "Télécharge le nouveau REKA-Taskbar.exe et remplace l'ancien."))
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, update.size))
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.skip_button = QPushButton("Ignorer cette version")
        self.skip_button.clicked.connect(self._skip)
        self.later_button = QPushButton("Plus tard")
        self.later_button.clicked.connect(self.reject)
        self.browser_button = QPushButton("Navigateur" if self_update else "Télécharger")
        self.browser_button.setToolTip("Télécharger REKA-Taskbar.exe avec le navigateur")
        self.browser_button.clicked.connect(self._open_browser)
        self.install_button = QPushButton("Mettre à jour")
        self.install_button.setObjectName("primary")
        self.install_button.clicked.connect(self.start_install)
        self.install_button.setVisible(self_update)
        default = self.install_button if self_update else self.browser_button
        default.setObjectName("primary")
        default.setDefault(True)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        for button in (self.later_button, self.browser_button, self.install_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _skip(self) -> None:
        self.skipped = True
        self.reject()

    def _open_browser(self) -> None:
        QDesktopServices.openUrl(QUrl(self.update_info.url))

    def start_install(self) -> None:
        if self._downloader is not None:
            return
        self.install_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.later_button.setText("Annuler")
        self.progress.show()
        self.status.setText("Téléchargement de la nouvelle version…")
        # Sans parent : le fil de téléchargement peut finir après la fermeture du dialogue
        self._downloader = _Downloader(self.update_info)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.finished.connect(self._on_downloaded)
        self._downloader.failed.connect(self._on_failed)
        self._downloader.start()

    def _on_progress(self, received: int, total: int) -> None:
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(received)

    def _on_downloaded(self, path: Path) -> None:
        if self._downloader is None:        # annulé entre-temps
            return
        self.status.setText("Installation…")
        try:
            install(path, Path(sys.executable))
        except UpdateError as exc:
            log.warning("Mise à jour non installée : %s", exc)
            self._on_failed(f"{exc}\nLe nouvel exe est ici : {path}")
            return
        self.installed = True
        self.accept()

    def _on_failed(self, message: str) -> None:
        if self._downloader is None:
            return
        self._downloader = None
        self.progress.hide()
        self.status.setText(f"⚠ {message}\nTu peux aussi télécharger l'exe dans le navigateur.")
        self.install_button.setEnabled(True)
        self.install_button.setText("Réessayer")
        self.skip_button.setEnabled(True)
        self.later_button.setText("Plus tard")

    def reject(self) -> None:
        if self._downloader is not None:
            self._downloader.cancel()
            self._downloader = None
        super().reject()
