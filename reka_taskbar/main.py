"""
REKA Taskbar — point d'entrée.

Une barre des tâches personnalisée pour Windows, avec des widgets d'usage
courant (fenêtres ouvertes, musique, processeur, réseau, météo, horloge…) et
des widgets reliés à REKA, la console de mixage : canaux, micro, casque,
mini-console.

Options :
  --demo              la barre avec des moteurs simulés (sans Voicemeeter ni REKA)
  --selftest IMAGE    rend la barre en démo dans IMAGE puis quitte (vérif de build)
  --settings          ouvre les réglages au démarrage
  --restore-taskbar   rend la barre des tâches de Windows (si elle est restée cachée)
  --restart           (après une mise à jour) attend la fin de l'instance précédente
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from core import appbar, config
from core.media import create_media_backend
from core.reka_link import RekaLink
from core.system import SystemMonitor
from core.updater import UpdateManager, cleanup_previous, load_build_info
from core.voicemeeter import VoicemeeterLink
from core.weather import WeatherService
from core.windows import create_window_backend
from ui import styles
from ui.bar import TaskbarWindow

log = logging.getLogger("reka_taskbar")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s : %(message)s"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 2
WINDOWS_APP_ID = "REKA.Taskbar"
RESTART_WAIT_MS = 30_000      # --restart : l'instance précédente finit de se fermer
OLD_EXE_RETRY_MS = 10_000     # ancien exe encore verrouillé : nouvel essai de suppression
OLD_EXE_RETRIES = 6


# --------------------------------------------------------------------------- #
# Journalisation et erreurs non gérées
# --------------------------------------------------------------------------- #
def setup_logging() -> Path:
    """Journal dans %APPDATA%/REKA Taskbar/app.log (rotation 2 × 1 Mo)."""
    log_path = config.app_data_dir() / "app.log"
    formatter = logging.Formatter(LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                  encoding="utf-8")
    handler.setFormatter(formatter)
    root.addHandler(handler)
    if sys.stderr is not None:        # dans l'exe sans console, sys.stderr vaut None
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    return log_path


def install_exception_hooks() -> None:
    def main_hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Exception non gérée", exc_info=(exc_type, exc, tb))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread else "?"
        log.critical("Exception non gérée dans le thread %s", name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def qt_message_handler(mode: QtMsgType, _context, message: str) -> None:
    level = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
             QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
             QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode, logging.INFO)
    logging.getLogger("qt").log(level, message)


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError) as exc:
        log.debug("AppUserModelID non défini : %s", exc)


def retry_cleanup(attempts: int) -> None:
    """Supprime l'ancien exe d'une mise à jour ; tant que l'instance précédente
    le tient encore, nouvel essai un peu plus tard (puis au prochain lancement)."""
    if not cleanup_previous() and attempts > 1:
        QTimer.singleShot(OLD_EXE_RETRY_MS, lambda: retry_cleanup(attempts - 1))


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
class TaskbarApp:
    """Crée les services, la barre et l'icône de notification ; les arrête."""

    def __init__(self, cfg: dict, *, demo: bool = False, animate: bool = True) -> None:
        self.cfg = cfg
        self.demo = demo
        weather_cfg = cfg.get("widgets", {}).get("weather", {})
        if demo:
            from core import demo as demo_engines
            from core.media import DemoMedia
            from core.windows import DemoWindows

            self.reka = demo_engines.DemoRekaLink(cfg)
            self.vm, self.remote = demo_engines.demo_link(self.reka.setup, animate)
            self.media = DemoMedia()
            self.system = demo_engines.DemoSystem(animate)
            self.windows = DemoWindows()
            self.weather = WeatherService("Paris", fetch=demo_engines.demo_weather)
        else:
            self.reka = RekaLink(cfg)
            self.vm = VoicemeeterLink(self.reka.setup,
                                      float(cfg.get("reka", {}).get("poll_hz", 20) or 20))
            self.remote = None
            self.media = create_media_backend()
            self.system = SystemMonitor(
                float(cfg.get("widgets", {}).get("system", {}).get("interval_s", 1.5) or 1.5))
            self.windows = create_window_backend()
            self.weather = WeatherService(str(weather_cfg.get("city") or ""),
                                          float(weather_cfg.get("refresh_min", 20) or 20))
        # Démo : pas de mises à jour (aucun build_info)
        self.updates = UpdateManager(cfg, None if demo else load_build_info())
        self.bar = TaskbarWindow(cfg, self.vm, self.reka, self.media, self.system, self.windows,
                                 self.weather, self.updates, persist=not demo)
        self.tray: QSystemTrayIcon | None = None
        self._stopped = False

    def start(self) -> None:
        self.reka.start()
        self.vm.start()
        self.media.start()
        self.system.start()
        self.weather.start()
        self.updates.start()
        self.bar.show()
        self.bar.dock()

    def add_tray_icon(self, icon: QIcon) -> None:
        """Icône près de l'horloge de Windows : un moyen d'atteindre les réglages
        et de quitter, même si la barre est sur un autre écran."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip(config.APP_NAME)
        menu = QMenu()
        menu.addAction("Mini-console…", lambda: self.bar.open_mixer(None))
        menu.addAction("Réglages de la barre…", lambda: self.bar.open_settings(""))
        menu.addAction("Rechercher les mises à jour…", self.bar.check_for_updates)
        menu.addSeparator()
        menu.addAction(f"Quitter {config.APP_NAME}", self.bar.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu            # gardé en vie
        self.tray.show()

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        log.info("Arrêt…")
        self.bar.shutdown()
        if self.tray is not None:
            self.tray.hide()
        for service in (self.updates, self.weather, self.system, self.media, self.reka, self.vm):
            try:
                service.stop()
            except Exception:
                log.exception("Arrêt incomplet de %s", type(service).__name__)
        if not self.demo:
            config.save_quietly(self.cfg)


# --------------------------------------------------------------------------- #
# Auto-test (vérification de build)
# --------------------------------------------------------------------------- #
def run_selftest(app: QApplication, taskbar: TaskbarApp, image: Path) -> int:
    """Rend la barre et la mini-console en démo dans des images, vérifie que
    les widgets reliés à REKA réagissent, et sonde les services de Windows.
    Le compte rendu est écrit à côté de l'image (.txt)."""
    report: list[str] = [f"{config.APP_NAME} {config.APP_VERSION} — auto-test",
                         f"Python {platform.python_version()}, {platform.platform()}"]
    failures: list[str] = []

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def check(label: str, ok: bool, detail: str = "") -> None:
        report.append(f"[{'OK' if ok else 'ÉCHEC'}] {label}{' : ' + detail if detail else ''}")
        if not ok:
            failures.append(label)

    try:
        image.parent.mkdir(parents=True, exist_ok=True)
        bar = taskbar.bar
        bar.setFixedWidth(1920)
        pump(1.2)

        from ui.bar import normalized_layout
        wanted = [key for keys in normalized_layout(taskbar.cfg).values() for key in keys]
        check("Widgets créés", sorted(bar.widgets) == sorted(wanted),
              f"{len(bar.widgets)} sur {len(wanted)}")
        check("Voicemeeter simulé connecté", taskbar.vm.connected)
        strips = bar.widgets.get("strips")
        chips = strips.chips if strips is not None else []
        check("Canaux de REKA", len(chips) == len(taskbar.vm.setup.strips), f"{len(chips)} canaux")
        check("Niveaux reçus", any(max(chip.levels) > -60 for chip in chips))

        if chips:      # un clic sur un canal coupe bien la strip de Voicemeeter
            vm_strip = taskbar.vm.setup.strips[0]
            before = taskbar.remote.peek(f"Strip[{vm_strip}].Mute")
            chips[0].toggled.emit(0)
            pump(0.4)
            after = taskbar.remote.peek(f"Strip[{vm_strip}].Mute")
            check("Muet d'un canal envoyé à Voicemeeter", before != after)
            check("Muet affiché dans la barre", chips[0].muted == (after >= 0.5))
            chips[0].toggled.emit(0)
            pump(0.4)

        check("Image de la barre", bar.grab().save(str(image)), str(image))
        bar.open_mixer(None)
        pump(0.5)
        mixer = bar._mixer
        check("Mini-console", mixer is not None and len(mixer.columns) == len(chips))
        if mixer is not None:
            mixer_image = image.with_name(image.stem + "-mixer.png")
            check("Image de la mini-console", mixer.grab().save(str(mixer_image)), str(mixer_image))
            mixer.close()

        from ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(taskbar.cfg, taskbar.reka, taskbar.vm)
        dialog.show()
        pump(0.2)
        settings_image = image.with_name(image.stem + "-reglages.png")
        check("Image des réglages", dialog.grab().save(str(settings_image)), str(settings_image))
        dialog.close()

        failures.extend(_selftest_system(report))
    except Exception as exc:
        log.exception("Auto-test interrompu")
        report.append(f"[ÉCHEC] Auto-test interrompu : {exc!r}")
        failures.append("exception")

    report.append("RÉSULTAT : " + ("OK" if not failures else f"ÉCHEC ({', '.join(failures)})"))
    text = "\n".join(report) + "\n"
    image.with_suffix(".txt").write_text(text, encoding="utf-8")
    log.info("Auto-test :\n%s", text)
    taskbar.shutdown()
    return 0 if not failures else 1


def _selftest_system(report: list[str]) -> list[str]:
    """Services réels de la machine : chaque sonde est notée ; seules celles
    qui doivent marcher partout (psutil) comptent comme des échecs."""
    failures: list[str] = []
    try:
        monitor = SystemMonitor()
        stats = monitor._read()
        report.append(f"[OK] État du système : mémoire {stats.ram:.0f} %, "
                      f"batterie {'aucune' if stats.battery is None else f'{stats.battery:.0f} %'}")
    except Exception as exc:
        report.append(f"[ÉCHEC] État du système : {exc!r}")
        failures.append("psutil")
    if sys.platform != "win32":
        report.append("[--] Sondes Windows ignorées (autre système)")
        return failures

    def probe(label: str, function, required: bool = True) -> None:
        try:
            report.append(f"[OK] {label} : {function()}")
        except Exception as exc:
            report.append(f"[{'ÉCHEC' if required else '--'}] {label} : {exc!r}")
            if required:
                failures.append(label)

    def windows_probe() -> str:
        from core.windows import Win32Windows
        return f"{len(Win32Windows().windows())} fenêtre(s) ouverte(s)"

    def monitors_probe() -> str:
        monitors = appbar.list_monitors()
        if not monitors:
            raise RuntimeError("aucun écran")
        return ", ".join(f"{m.device} {m.rect}" for m in monitors)

    def media_probe() -> str:
        from core.media import probe_media_controls
        return probe_media_controls()

    def voicemeeter_probe() -> str:
        from core.voicemeeter import RemoteApi
        api = RemoteApi()
        running = api.login()
        api.logout()
        return "installé, " + ("en marche" if running else "fermé")

    def reka_probe() -> str:
        from core.reka_link import is_reka_running, reka_config_path
        return (f"{'ouverte' if is_reka_running() else 'fermée'}, config "
                f"{'présente' if reka_config_path({}).is_file() else 'absente'}")

    def autostart_probe() -> str:
        from core import shell
        return f"{'activé' if shell.autostart_enabled() else 'désactivé'} ({shell.autostart_command()})"

    def update_probe() -> str:
        from core.updater import load_build_info, version_url
        build = load_build_info()
        if build is None:
            if getattr(sys, "frozen", False):
                raise RuntimeError("build_info.json absent de l'exe")
            return "développement (pas de build_info.json)"
        if build.version != config.APP_VERSION:
            raise RuntimeError(f"build_info {build.version} ≠ version {config.APP_VERSION}")
        return f"{build.version}, vérifie {version_url({}, build)}"

    probe("Mises à jour", update_probe)
    probe("Fenêtres ouvertes (Win32)", windows_probe)
    probe("Écrans", monitors_probe)
    probe("Démarrage avec Windows", autostart_probe)
    probe("REKA", reka_probe)
    probe("Contrôles média (WinRT)", media_probe, required=False)
    probe("Voicemeeter", voicemeeter_probe, required=False)
    return failures


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=config.APP_NAME, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true",
                        help="moteurs simulés (sans Voicemeeter ni REKA)")
    parser.add_argument("--selftest", metavar="IMAGE",
                        help="rend la barre en démo dans IMAGE puis quitte")
    parser.add_argument("--settings", action="store_true", help="ouvre les réglages au démarrage")
    parser.add_argument("--restore-taskbar", action="store_true",
                        help="rend la barre des tâches de Windows puis quitte")
    parser.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--updated-from", metavar="VERSION", default="", help=argparse.SUPPRESS)
    return parser.parse_args(argv[1:])


def main() -> int:
    args = parse_args(sys.argv)
    log_path = setup_logging()
    install_exception_hooks()
    log.info("=== %s %s — Python %s, %s ===", config.APP_NAME, config.APP_VERSION,
             platform.python_version(), platform.platform())

    if args.restore_taskbar:
        restored = appbar.set_windows_taskbar_hidden(False, config.app_data_dir())
        log.info("Barre des tâches de Windows %s.", "rendue" if restored else "inchangée")
        return 0

    set_windows_app_id()
    qInstallMessageHandler(qt_message_handler)
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setQuitOnLastWindowClosed(False)     # fermer une fenêtre volante ne quitte pas la barre
    icon = QIcon(str(config.resource_path("assets/icon.ico")))
    app.setWindowIcon(icon)
    styles.load_fonts()

    try:
        cfg = config.load_config()
    except (OSError, ValueError) as exc:
        log.critical("Configuration illisible : %s", exc)
        QMessageBox.critical(None, config.APP_NAME,
                             f"Configuration par défaut illisible :\n{exc}\n\nRéinstalle l'application.")
        return 1
    level = logging.getLevelName(str(cfg.get("log_level", "INFO")).upper())
    if isinstance(level, int):
        logging.getLogger().setLevel(level)

    if args.demo or args.selftest:
        taskbar = TaskbarApp(config.default_config() if args.selftest else cfg, demo=True,
                             animate=not args.selftest)
        app.aboutToQuit.connect(taskbar.shutdown)
        taskbar.start()
        if args.selftest:
            return run_selftest(app, taskbar, Path(args.selftest))
        return app.exec()

    # Une session précédente a pu laisser la barre de Windows cachée (plantage)
    appbar.restore_windows_taskbar_if_needed(config.app_data_dir())

    lock = QLockFile(str(config.app_data_dir() / "instance.lock"))
    if not lock.tryLock(RESTART_WAIT_MS if args.restart else 200):
        QMessageBox.information(None, config.APP_NAME, f"{config.APP_NAME} est déjà ouverte.")
        return 0
    if args.restart:
        cfg = config.load_config()      # relue : l'instance précédente l'a écrite en partant
    # Après une mise à jour : l'ancien exe (encore verrouillé un instant) est supprimé
    retry_cleanup(OLD_EXE_RETRIES)

    try:
        taskbar = TaskbarApp(cfg)
    except Exception as exc:
        log.exception("Impossible de créer la barre")
        QMessageBox.critical(None, config.APP_NAME,
                             f"Impossible d'afficher la barre :\n{exc}\n\n"
                             f"Détails dans le journal :\n{log_path}")
        lock.unlock()
        return 1
    app.aboutToQuit.connect(taskbar.shutdown)
    app.commitDataRequest.connect(lambda _manager: taskbar.bar.shutdown())   # fermeture de session
    taskbar.start()
    taskbar.add_tray_icon(icon)
    if args.updated_from:
        log.info("Mise à jour : %s → %s", args.updated_from, config.APP_VERSION)
        if taskbar.tray is not None:
            taskbar.tray.showMessage(config.APP_NAME,
                                     f"Mise à jour installée : version {config.APP_VERSION}.",
                                     icon, 5000)
    if args.settings:
        taskbar.bar.open_settings("")
    exit_code = app.exec()

    taskbar.shutdown()
    lock.unlock()
    log.info("=== %s arrêtée (code %d) ===", config.APP_NAME, exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
