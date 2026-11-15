"""
La barre : une bande ancrée en haut ou en bas de l'écran, avec trois zones
de widgets (gauche, centre, droite) décrites dans la config (layout).

Sous Windows, elle se déclare « barre d'application » : les fenêtres agrandies
s'arrêtent à elle. Elle ne prend jamais le focus du clavier, comme la barre
des tâches de Windows : un clic sur un widget ne dérange pas la fenêtre active.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QGridLayout, QMenu,
                               QMessageBox, QSizePolicy, QWidget)

from core import appbar, config, shell
from core.reka_link import REKA_DOWNLOAD_URL, RekaSetup
from ui import styles
from ui.mixer_popup import MixerPopup
from ui.popup import show_menu
from ui.widgets.base import Context
from ui.widgets.general import (BatteryWidget, ClockWidget, MediaWidget, NetworkWidget,
                                ShortcutsWidget, StartWidget, SystemWidget, WeatherWidget)
from ui.widgets.reka import HeadphoneWidget, MicWidget, RekaWidget, StripsWidget, mic_strip
from ui.widgets.tasks import TasksWidget

log = logging.getLogger(__name__)

ZONES = {"left": "Gauche", "center": "Centre", "right": "Droite"}
WIDGETS = {                   # clé (config layout) → (nom affiché, classe)
    "start": ("Démarrer", StartWidget),
    "reka": ("Bouton REKA", RekaWidget),
    "shortcuts": ("Raccourcis", ShortcutsWidget),
    "tasks": ("Fenêtres ouvertes", TasksWidget),
    "media": ("Musique en cours", MediaWidget),
    "strips": ("Canaux de REKA", StripsWidget),
    "mic": ("Micro", MicWidget),
    "headphone": ("Casque", HeadphoneWidget),
    "system": ("Processeur, mémoire", SystemWidget),
    "network": ("Débit du réseau", NetworkWidget),
    "weather": ("Météo", WeatherWidget),
    "battery": ("Batterie", BatteryWidget),
    "clock": ("Horloge, calendrier", ClockWidget),
}
MIN_HEIGHT, MAX_HEIGHT, DEFAULT_HEIGHT = 32, 72, 44
MARGIN_X, MARGIN_Y = 8, 6
REHIDE_MS = 2000              # Windows ressort parfois sa barre : on la recache
HOTKEY_MIC = 1
WM_HOTKEY = 0x0312
HWND_BOTTOM, HWND_TOPMOST = 1, -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10


def normalized_layout(cfg: dict) -> dict[str, list[str]]:
    """Disposition des widgets : zones connues, widgets connus, sans doublon."""
    raw = cfg.get("layout") if isinstance(cfg.get("layout"), dict) else {}
    seen: set[str] = set()
    layout: dict[str, list[str]] = {}
    for zone in ZONES:
        keys = raw.get(zone) if isinstance(raw.get(zone), list) else []
        layout[zone] = []
        for key in keys:
            if key in WIDGETS and key not in seen:
                seen.add(key)
                layout[zone].append(key)
    return layout


def bar_height(cfg: dict) -> int:
    try:
        height = int(cfg.get("bar", {}).get("height", DEFAULT_HEIGHT))
    except (TypeError, ValueError):
        height = DEFAULT_HEIGHT
    return max(MIN_HEIGHT, min(MAX_HEIGHT, height))


def bar_geometry(screen: QRect, edge: str, height: int) -> QRect:
    """Rectangle de la barre sur un écran (coordonnées de Qt)."""
    y = screen.bottom() + 1 - height if appbar.normalize_edge(edge) == appbar.EDGE_BOTTOM \
        else screen.top()
    return QRect(screen.left(), y, screen.width(), height)


class TaskbarWindow(QWidget):
    def __init__(self, cfg: dict, vm, reka, media, system, windows, weather,
                 persist: bool = True) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setWindowTitle(config.APP_NAME)
        self._cfg = cfg
        self._persist = persist            # False : démo et tests, rien n'est écrit ni réservé
        self._vm, self._reka = vm, reka
        self.ctx = Context(cfg=cfg, vm=vm, reka=reka, media=media, system=system,
                           windows=windows, weather=weather, save=self.save,
                           open_settings=self.open_settings, open_mixer=self.open_mixer,
                           open_reka=self.open_reka, quit=self.quit)
        self.widgets: dict[str, QWidget] = {}
        self._zones: dict[str, QWidget] = {}
        self._mixer: MixerPopup | None = None
        self._settings = None
        self._appbar: appbar.AppBar | None = None
        self._taskbar_hidden = False
        self._hotkey = False
        self._closing = False

        grid = QGridLayout(self)
        grid.setContentsMargins(MARGIN_X, MARGIN_Y, MARGIN_X, MARGIN_Y)
        grid.setHorizontalSpacing(12)
        for column, zone in enumerate(ZONES):
            holder = QWidget(self)
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            holder.setSizePolicy(QSizePolicy.Policy.Preferred if zone == "center"
                                 else QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._zones[zone] = holder
            grid.addWidget(holder, 0, column)
            grid.setColumnStretch(column, 0 if zone == "center" else 1)

        self._rehide = QTimer(self)
        self._rehide.setInterval(REHIDE_MS)
        self._rehide.timeout.connect(self._keep_windows_taskbar_hidden)

        reka.setup_changed.connect(self._on_reka_setup)
        self.apply_theme()
        self.build_widgets()
        for screen_signal in (QGuiApplication.instance().screenAdded,
                              QGuiApplication.instance().screenRemoved,
                              QGuiApplication.instance().primaryScreenChanged):
            screen_signal.connect(lambda *_a: QTimer.singleShot(500, self.dock))

    # ---------------------------------------------------------------- widgets
    def build_widgets(self) -> None:
        """(Re)construit les widgets d'après la config (layout)."""
        for widget in self.widgets.values():
            widget.setParent(None)
            widget.deleteLater()
        self.widgets = {}
        layout = normalized_layout(self._cfg)
        for zone, holder in self._zones.items():
            row = holder.layout()
            while row.count():
                row.takeAt(0)
            expanding = False
            if zone == "right":
                row.addStretch(1)
            for key in layout[zone]:
                try:
                    widget = WIDGETS[key][1](self.ctx, holder)
                except Exception:
                    log.exception("Widget « %s » non créé", key)
                    continue
                grows = widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
                expanding = expanding or grows
                row.addWidget(widget, 1 if grows else 0)
                self.widgets[key] = widget
            if zone == "left" and not expanding:
                row.addStretch(1)
        self.update()

    # ------------------------------------------------------------------ thème
    def apply_theme(self) -> None:
        """Thème de REKA (si « suivre REKA » et qu'elle est installée), sinon
        celui choisi dans les réglages de la barre."""
        appearance = self._cfg.get("appearance", {})
        setup: RekaSetup = self._reka.setup
        if appearance.get("follow_reka", True) and setup.found:
            changed = styles.set_theme(setup.theme, setup.colors, setup.font_family)
        else:
            changed = styles.set_theme(appearance.get("theme"))
        app = QApplication.instance()
        if changed or not app.styleSheet():
            styles.apply(app)
        for widget in self.widgets.values():      # couleurs mémorisées par un widget
            refresh = getattr(widget, "refresh_theme", None)
            if refresh is not None:
                refresh()
        self.update()
        for child in self.findChildren(QWidget):
            child.update()

    def _on_reka_setup(self, setup: RekaSetup) -> None:
        self._vm.configure(setup)
        self.apply_theme()

    # ----------------------------------------------------------------- ancrage
    def target_screen(self):
        name = str(self._cfg.get("bar", {}).get("screen") or "")
        for screen in QGuiApplication.screens():
            if name and screen.name() == name:
                return screen
        return QGuiApplication.primaryScreen()

    def dock(self) -> None:
        """Place la barre sur son bord d'écran et y réserve sa place."""
        bar = self._cfg.get("bar", {})
        screen = self.target_screen()
        if screen is None:
            return
        height = bar_height(self._cfg)
        edge = appbar.normalize_edge(str(bar.get("edge", appbar.EDGE_TOP)))
        self.setFixedHeight(height)
        self.setGeometry(bar_geometry(screen.geometry(), edge, height))
        if not self._persist or sys.platform != "win32" or not self.isVisible():
            return
        if self._appbar is None:
            self._appbar = appbar.AppBar(int(self.winId()))
        try:
            corner = screen.geometry().topLeft()
            self._appbar.dock(edge, round(height * screen.devicePixelRatio()), screen.name(),
                              reserve=bool(bar.get("reserve_space", True)),
                              origin=(corner.x(), corner.y()))
        except OSError as exc:
            log.warning("Ancrage de la barre impossible : %s", exc)

    def showEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().showEvent(event)
        QTimer.singleShot(0, self._after_show)

    def _after_show(self) -> None:
        self.dock()
        self._sync_windows_taskbar()
        self._register_hotkey()

    def apply_config(self) -> None:
        """Après un changement dans les réglages : tout est repris de la config."""
        self.ctx.weather.set_city(str(self.ctx.widget_cfg("weather").get("city") or ""))
        self._reka.refresh()
        self._vm.configure(self._reka.setup)
        self.apply_theme()
        self.build_widgets()
        self.dock()
        self._sync_windows_taskbar()
        self._register_hotkey()

    # ------------------------------------------- barre des tâches de Windows
    def _sync_windows_taskbar(self) -> None:
        if not self._persist or sys.platform != "win32":
            return
        wanted = bool(self._cfg.get("bar", {}).get("hide_windows_taskbar", False))
        if wanted != self._taskbar_hidden:
            if appbar.set_windows_taskbar_hidden(wanted, config.app_data_dir()):
                self._taskbar_hidden = wanted
                log.info("Barre des tâches de Windows %s.", "cachée" if wanted else "rendue")
        if self._taskbar_hidden:
            self._rehide.start()
        else:
            self._rehide.stop()

    def _keep_windows_taskbar_hidden(self) -> None:
        if self._taskbar_hidden and appbar.windows_taskbar_visible():
            appbar.set_windows_taskbar_hidden(True, config.app_data_dir())

    def toggle_windows_taskbar(self) -> None:
        bar = self._cfg.setdefault("bar", {})
        bar["hide_windows_taskbar"] = not bar.get("hide_windows_taskbar", False)
        self.save()
        self._sync_windows_taskbar()

    # -------------------------------------------------------- raccourci micro
    def _register_hotkey(self) -> None:
        if not self._persist or sys.platform != "win32" or not self.isVisible():
            return
        from core import winapi

        hwnd = int(self.winId())
        if self._hotkey:
            winapi.user32.UnregisterHotKey(hwnd, HOTKEY_MIC)
            self._hotkey = False
        text = str(self.ctx.widget_cfg("mic").get("hotkey") or "")
        parsed = shell.parse_hotkey(text)
        if parsed is None:
            if text.strip():
                log.warning("Raccourci du micro « %s » incompris.", text)
            return
        modifiers, key = parsed
        self._hotkey = bool(winapi.user32.RegisterHotKey(hwnd, HOTKEY_MIC,
                                                         modifiers | shell.MOD_NOREPEAT, key))
        if not self._hotkey:
            log.warning("Raccourci du micro « %s » déjà pris par une autre application.", text)

    def toggle_mic(self) -> None:
        """Coupe ou rouvre le micro (raccourci clavier global)."""
        params = self._vm.params
        index = mic_strip(self._cfg, self._vm.setup)
        if params is not None and index < len(params.strips):
            self._vm.set_mute(index, not params.strips[index].mute)

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32":
            try:
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_MIC:
                    self.toggle_mic()
                    return True, 0
                if self._appbar is not None and msg.message == self._appbar.callback_message:
                    self._on_appbar_event(int(msg.wParam), int(msg.lParam))
                    return True, 0
            except Exception:      # un message illisible ne doit jamais faire tomber la barre
                log.debug("Message Windows ignoré", exc_info=True)
        return False, 0

    def _on_appbar_event(self, code: int, value: int) -> None:
        if code == appbar.ABN_POSCHANGED:
            QTimer.singleShot(0, self.dock)
        elif code == appbar.ABN_FULLSCREENAPP and self._cfg.get("bar", {}).get(
                "hide_on_fullscreen", True):
            # Jeu ou vidéo en plein écran : la barre passe derrière, puis revient
            from core import winapi

            winapi.user32.SetWindowPos(int(self.winId()), HWND_BOTTOM if value else HWND_TOPMOST,
                                       0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # --------------------------------------------------------------- commandes
    def save(self) -> None:
        if self._persist:
            config.save_quietly(self._cfg)

    def open_mixer(self, anchor: QWidget | None = None) -> None:
        if self._mixer is not None:
            self._mixer.close()
        self._mixer = MixerPopup(self._vm, self._reka, self.open_reka, self)
        self._mixer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._mixer.destroyed.connect(lambda *_a: setattr(self, "_mixer", None))
        self._mixer.show_near(anchor or self.widgets.get("strips") or self)

    def open_settings(self, tab: str = "") -> None:
        from ui.settings_dialog import SettingsDialog

        if self._settings is None:
            self._settings = SettingsDialog(self._cfg, self._reka, self._vm)
            self._settings.applied.connect(self._on_settings_applied)
            self._settings.finished.connect(lambda *_a: setattr(self, "_settings", None))
            self._settings.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._settings.select_tab(tab)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _on_settings_applied(self) -> None:
        self.save()
        self.apply_config()

    def open_reka(self) -> None:
        """Affiche la console REKA, la lance si elle est fermée ; si la barre ne
        sait pas où elle est, propose de l'indiquer ou de la télécharger."""
        if self._reka.show_or_launch() != "missing":
            return
        box = QMessageBox(QMessageBox.Icon.Question, config.APP_NAME,
                          "REKA n'est pas ouverte, et la barre ne sait pas encore où se trouve "
                          "REKA.exe.\n\nIndique son emplacement (une seule fois) ou télécharge-la.")
        choose = box.addButton("Choisir REKA.exe…", QMessageBox.ButtonRole.AcceptRole)
        download = box.addButton("Télécharger REKA", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is choose:
            path, _filter = QFileDialog.getOpenFileName(None, "Où est REKA.exe ?", "",
                                                        "REKA (REKA.exe);;Programmes (*.exe)")
            if path:
                self._cfg.setdefault("reka", {})["exe_path"] = path
                self.save()
                self._reka.launch()
        elif box.clickedButton() is download:
            QDesktopServices.openUrl(QUrl(REKA_DOWNLOAD_URL))

    def quit(self) -> None:
        QApplication.instance().quit()

    def shutdown(self) -> None:
        """Rend à Windows ce que la barre lui a pris (place à l'écran, barre des
        tâches cachée, raccourci clavier)."""
        if self._closing:
            return
        self._closing = True
        self._rehide.stop()
        if self._mixer is not None:
            self._mixer.close()
        if self._settings is not None:
            self._settings.close()
        if sys.platform == "win32" and self._persist:
            if self._hotkey:
                from core import winapi

                winapi.user32.UnregisterHotKey(int(self.winId()), HOTKEY_MIC)
            if self._appbar is not None:
                self._appbar.remove()
            if self._taskbar_hidden:
                appbar.set_windows_taskbar_hidden(False, config.app_data_dir())
                self._taskbar_hidden = False

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------------- menu
    def contextMenuEvent(self, event) -> None:  # noqa: N802
        show_menu(self.build_menu(self.childAt(event.pos())), event.globalPos())
        event.accept()

    def build_menu(self, under: QWidget | None = None) -> QMenu:
        menu = QMenu(self)
        widget = under
        while widget is not None and not hasattr(widget, "menu_actions"):
            widget = widget.parentWidget()
        actions = widget.menu_actions() if widget is not None else []
        for label, callback in actions:
            action = menu.addAction(label)
            if callback is None:
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda _checked=False, c=callback: c())
        if actions:
            menu.addSeparator()
        menu.addAction("Mini-console…", lambda: self.open_mixer(None))
        menu.addAction("Réglages de la barre…", lambda: self.open_settings(""))
        if sys.platform == "win32" and self._persist:
            hidden = bool(self._cfg.get("bar", {}).get("hide_windows_taskbar", False))
            menu.addAction("Afficher la barre des tâches de Windows" if hidden
                           else "Cacher la barre des tâches de Windows",
                           self.toggle_windows_taskbar)
        menu.addSeparator()
        menu.addAction(f"Quitter {config.APP_NAME}", self.quit)
        return menu

    # ------------------------------------------------------------------ dessin
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            opacity = float(self._cfg.get("appearance", {}).get("opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        painter.fillRect(self.rect(), styles.color(styles.BG_WINDOW, max(0.2, min(1.0, opacity))))
        edge = appbar.normalize_edge(str(self._cfg.get("bar", {}).get("edge", appbar.EDGE_TOP)))
        y = self.height() - 1 if edge == appbar.EDGE_TOP else 0
        painter.fillRect(0, y, self.width(), 1, QColor(styles.BORDER_COLUMN))
