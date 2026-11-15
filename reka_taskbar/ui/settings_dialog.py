"""
Réglages de la barre : position, widgets, lien avec REKA, raccourcis.

Rien n'est écrit tant qu'on n'a pas cliqué sur Appliquer ou OK : la fenêtre
modifie alors la config en place et émet `applied` (la barre se reconstruit).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from core import appbar, config, shell
from core.reka_link import REKA_PAGE_URL
from ui import styles
from ui.widgets.reka import vm_state_text

HIDDEN_ZONE = "hidden"
TABS = ("bar", "widgets", "reka", "shortcuts")
KEY_ROLE = Qt.ItemDataRole.UserRole


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("heading")
    return label


class SettingsDialog(QDialog):
    applied = Signal()

    check_updates = Signal()      # « Rechercher maintenant »

    def __init__(self, cfg: dict, reka, vm, updates=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._reka = reka
        self._vm = vm
        self._updates = updates
        self.setWindowTitle(f"Réglages — {config.APP_NAME}")
        self.setMinimumSize(760, 540)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_bar_tab(), "Barre")
        self.tabs.addTab(self._build_widgets_tab(), "Widgets")
        self.tabs.addTab(self._build_reka_tab(), "REKA")
        self.tabs.addTab(self._build_shortcuts_tab(), "Raccourcis")

        buttons = QHBoxLayout()
        version = QLabel(f"{config.APP_NAME} {config.APP_VERSION} — par {config.APP_AUTHORS}")
        version.setObjectName("muted")
        cancel = QPushButton("Annuler")
        apply = QPushButton("Appliquer")
        ok = QPushButton("OK")
        ok.setObjectName("primary")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.apply)
        ok.clicked.connect(self._accept)
        buttons.addWidget(version)
        buttons.addStretch(1)
        for button in (cancel, apply, ok):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)

    def select_tab(self, key: str) -> None:
        if key in TABS:
            self.tabs.setCurrentIndex(TABS.index(key))

    # ------------------------------------------------------------------ barre
    def _build_bar_tab(self) -> QWidget:
        bar = self._cfg.get("bar", {})
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)

        self.edge = QComboBox()
        for key, label in appbar.EDGES.items():
            self.edge.addItem(label, key)
        self.edge.setCurrentIndex(max(0, self.edge.findData(
            appbar.normalize_edge(str(bar.get("edge", appbar.EDGE_TOP))))))
        form.addRow("Position", self.edge)

        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.height_box = QSpinBox()
        self.height_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.height_box.setRange(32, 72)
        self.height_box.setSuffix(" px")
        self.height_box.setValue(int(bar.get("height", 44) or 44))
        form.addRow("Hauteur", self.height_box)

        self.screen = QComboBox()
        self.screen.addItem("Écran principal", "")
        for screen in QGuiApplication.screens():
            size = screen.size()
            self.screen.addItem(f"{screen.name()} ({size.width()} × {size.height()})",
                                screen.name())
        self.screen.setCurrentIndex(max(0, self.screen.findData(str(bar.get("screen") or ""))))
        form.addRow("Écran", self.screen)

        self.opacity = QSpinBox()
        self.opacity.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.opacity.setRange(20, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(round(float(self._cfg.get("appearance", {}).get("opacity", 1.0)) * 100))
        form.addRow("Opacité du fond", self.opacity)

        self.reserve = QCheckBox("Réserver la place de la barre (les fenêtres agrandies s'arrêtent à elle)")
        self.reserve.setChecked(bool(bar.get("reserve_space", True)))
        form.addRow(self.reserve)

        self.fullscreen = QCheckBox("Passer derrière les jeux et vidéos en plein écran")
        self.fullscreen.setChecked(bool(bar.get("hide_on_fullscreen", True)))
        form.addRow(self.fullscreen)

        self.hide_taskbar = QCheckBox("Cacher la barre des tâches de Windows")
        self.hide_taskbar.setChecked(bool(bar.get("hide_windows_taskbar", False)))
        form.addRow(self.hide_taskbar)
        form.addRow(_note(
            "Les icônes près de l'horloge de Windows (zone de notification) sont cachées avec "
            "elle. La barre de Windows revient dès que tu décoches cette case ou que tu quittes "
            "REKA Taskbar ; en cas de souci, lance « REKA-Taskbar.exe --restore-taskbar »."))

        self.autostart = QCheckBox("Lancer REKA Taskbar au démarrage de Windows")
        self.autostart.setChecked(shell.autostart_enabled())
        form.addRow(self.autostart)

        update = self._cfg.get("update", {})
        self.auto_update = QCheckBox("Installer les mises à jour automatiquement")
        self.auto_update.setChecked(bool(update.get("auto_install", True)))
        check = QPushButton("Rechercher maintenant")
        check.clicked.connect(self.check_updates)
        row = QHBoxLayout()
        row.addWidget(self.auto_update)
        row.addStretch(1)
        row.addWidget(check)
        form.addRow(row)
        current = self._updates.current_version if self._updates is not None else config.APP_VERSION
        form.addRow(_note(
            f"Version installée : {current}. La barre vérifie les nouvelles versions au "
            "démarrage puis toutes les 6 heures ; sans installation automatique, un bouton "
            "« Mise à jour » apparaît dans la barre."))
        return page

    # ---------------------------------------------------------------- widgets
    def _build_widgets_tab(self) -> QWidget:
        from ui.bar import WIDGETS, ZONES, normalized_layout

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(_note("Glisse un widget d'une liste à l'autre pour le déplacer, et dans "
                               "sa liste pour changer son ordre. « Non affichés » le retire de "
                               "la barre."))

        current = normalized_layout(self._cfg)
        placed = {key for keys in current.values() for key in keys}
        zones = {**current, HIDDEN_ZONE: [key for key in WIDGETS if key not in placed]}
        titles = {**ZONES, HIDDEN_ZONE: "Non affichés"}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.zone_lists: dict[str, QListWidget] = {}
        for column, zone in enumerate(zones):
            widget = QListWidget()
            widget.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
            widget.setDefaultDropAction(Qt.DropAction.MoveAction)
            widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            widget.setMinimumHeight(200)
            widget.setSpacing(2)
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            widget.setTextElideMode(Qt.TextElideMode.ElideRight)
            for key in zones[zone]:
                item = QListWidgetItem(WIDGETS[key][0])
                item.setData(KEY_ROLE, key)
                widget.addItem(item)
            self.zone_lists[zone] = widget
            grid.addWidget(_heading(titles[zone]), 0, column)
            grid.addWidget(widget, 1, column)
        layout.addLayout(grid)

        options = self._cfg.get("widgets", {})
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.clock_seconds = QCheckBox("Afficher les secondes")
        self.clock_seconds.setChecked(bool(options.get("clock", {}).get("seconds", False)))
        self.clock_date = QCheckBox("Afficher la date")
        self.clock_date.setChecked(bool(options.get("clock", {}).get("date", True)))
        clock = QHBoxLayout()
        clock.addWidget(self.clock_seconds)
        clock.addWidget(self.clock_date)
        clock.addStretch(1)
        form.addRow("Horloge", clock)
        self.task_labels = QCheckBox("Afficher le titre des fenêtres à côté de leur icône")
        self.task_labels.setChecked(bool(options.get("tasks", {}).get("labels", False)))
        form.addRow("Fenêtres", self.task_labels)
        self.city = QLineEdit(str(options.get("weather", {}).get("city") or ""))
        self.city.setPlaceholderText("Paris, Lyon, Montréal… (vide : pas de météo)")
        form.addRow("Ville de la météo", self.city)
        layout.addLayout(form)
        layout.addWidget(_note("La météo vient d'Open-Meteo : seul le nom de la ville est envoyé."))
        layout.addStretch(1)
        return page

    def layout_from_lists(self) -> dict[str, list[str]]:
        return {zone: [widget.item(row).data(KEY_ROLE) for row in range(widget.count())]
                for zone, widget in self.zone_lists.items() if zone != HIDDEN_ZONE}

    # ------------------------------------------------------------------- REKA
    def _build_reka_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        setup = self._reka.setup

        layout.addWidget(_heading("État"))
        found = (f"Réglages de REKA lus dans {self._reka.config_path}" if setup.found
                 else f"REKA n'a pas encore été lancée sur ce PC ({self._reka.config_path} absent) : "
                      "la barre utilise ses canaux par défaut.")
        self.status = _note("\n".join((
            found,
            "REKA est ouverte." if self._reka.running else "REKA est fermée.",
            vm_state_text(self._vm.state, self._vm.setup) + ".")))
        layout.addWidget(self.status)
        link = QLabel(f'<a href="{REKA_PAGE_URL}" style="color: {styles.GREEN_NEON};">'
                      "Page de REKA (téléchargement, aide)</a>")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        appearance = self._cfg.get("appearance", {})
        self.follow_reka = QCheckBox("Reprendre le thème et les couleurs de REKA")
        self.follow_reka.setChecked(bool(appearance.get("follow_reka", True)))
        form.addRow("Apparence", self.follow_reka)
        self.theme = QComboBox()
        for key, (label, _accent) in styles.THEMES.items():
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(appearance.get("theme", "studio"))))
        self.theme.setEnabled(not self.follow_reka.isChecked())
        self.follow_reka.toggled.connect(lambda checked: self.theme.setEnabled(not checked))
        form.addRow("Thème de la barre", self.theme)

        mic = self._cfg.get("widgets", {}).get("mic", {})
        self.mic_strip = QComboBox()
        self.mic_strip.addItem(f"Comme dans REKA ({setup.name(setup.mic_strip)})", -1)
        for index in range(len(setup.strips)):
            self.mic_strip.addItem(setup.name(index), index)
        self.mic_strip.setCurrentIndex(max(0, self.mic_strip.findData(int(mic.get("strip", -1)))))
        form.addRow("Canal du micro", self.mic_strip)

        self.hotkey = QLineEdit(str(mic.get("hotkey") or ""))
        self.hotkey.setPlaceholderText("Ctrl+Alt+M, F13, Pause… (vide : aucun)")
        form.addRow("Raccourci « couper le micro »", self.hotkey)

        self.exe_path = QLineEdit(str(self._cfg.get("reka", {}).get("exe_path") or ""))
        self.exe_path.setPlaceholderText("Repéré tout seul la première fois que REKA est ouverte")
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse_exe)
        row = QHBoxLayout()
        row.addWidget(self.exe_path)
        row.addWidget(browse)
        form.addRow("REKA.exe", row)
        layout.addLayout(form)
        layout.addWidget(_note(
            "Le raccourci fonctionne partout, même en jeu. Un Muet posé depuis la barre s'allume "
            "aussi dans REKA (et dans Discord si sa synchronisation du micro est activée)."))
        layout.addStretch(1)
        return page

    def _browse_exe(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Où est REKA.exe ?", self.exe_path.text(),
                                                    "REKA (REKA.exe);;Programmes (*.exe)")
        if path:
            self.exe_path.setText(path)

    # ------------------------------------------------------------- raccourcis
    def _build_shortcuts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(_note("Programmes, dossiers et fichiers à garder sous la main : ils "
                               "apparaissent dans le widget « Raccourcis »."))
        self.shortcuts = QListWidget()
        self.shortcuts.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for item in self._cfg.get("shortcuts") or []:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                self._add_shortcut(str(item.get("name") or ""), str(item["path"]))
        layout.addWidget(self.shortcuts, 1)
        buttons = QHBoxLayout()
        add_file = QPushButton("Ajouter un programme ou un fichier…")
        add_folder = QPushButton("Ajouter un dossier…")
        remove = QPushButton("Retirer")
        add_file.clicked.connect(self._choose_file)
        add_folder.clicked.connect(self._choose_folder)
        remove.clicked.connect(lambda: self.shortcuts.takeItem(self.shortcuts.currentRow()))
        buttons.addWidget(add_file)
        buttons.addWidget(add_folder)
        buttons.addStretch(1)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        return page

    def _add_shortcut(self, name: str, path: str) -> None:
        name = name.strip() or Path(path.replace("\\", "/")).stem or path
        item = QListWidgetItem(f"{name}   —   {path}")
        item.setData(KEY_ROLE, {"name": name, "path": path})
        self.shortcuts.addItem(item)

    def _choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Ajouter un raccourci", "",
            "Programmes et raccourcis (*.exe *.lnk *.url *.bat);;Tous les fichiers (*)")
        if path:
            self._add_shortcut("", path)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ajouter un dossier")
        if path:
            self._add_shortcut("", path)

    # -------------------------------------------------------------- appliquer
    def apply(self) -> None:
        cfg = self._cfg
        bar = cfg.setdefault("bar", {})
        bar["edge"] = self.edge.currentData()
        bar["height"] = self.height_box.value()
        bar["screen"] = self.screen.currentData()
        bar["reserve_space"] = self.reserve.isChecked()
        bar["hide_on_fullscreen"] = self.fullscreen.isChecked()
        bar["hide_windows_taskbar"] = self.hide_taskbar.isChecked()

        appearance = cfg.setdefault("appearance", {})
        appearance["opacity"] = self.opacity.value() / 100
        appearance["follow_reka"] = self.follow_reka.isChecked()
        appearance["theme"] = self.theme.currentData()

        cfg["layout"] = self.layout_from_lists()
        widgets = cfg.setdefault("widgets", {})
        widgets.setdefault("clock", {}).update(seconds=self.clock_seconds.isChecked(),
                                               date=self.clock_date.isChecked())
        widgets.setdefault("tasks", {})["labels"] = self.task_labels.isChecked()
        widgets.setdefault("weather", {})["city"] = self.city.text().strip()
        widgets.setdefault("mic", {}).update(strip=int(self.mic_strip.currentData()),
                                             hotkey=self.hotkey.text().strip())
        cfg.setdefault("reka", {})["exe_path"] = self.exe_path.text().strip()
        cfg["shortcuts"] = [self.shortcuts.item(row).data(KEY_ROLE)
                            for row in range(self.shortcuts.count())]

        cfg.setdefault("update", {})["auto_install"] = self.auto_update.isChecked()
        if self.autostart.isChecked() != shell.autostart_enabled():
            shell.set_autostart(self.autostart.isChecked())
        self.applied.emit()

    def _accept(self) -> None:
        self.apply()
        self.accept()
