"""Configuration commune des tests : chemins, Qt hors écran, %APPDATA% temporaire."""

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    """Chaque test a son propre %APPDATA% : ni la vraie config de la barre ni
    celle de REKA ne sont touchées."""
    path = tmp_path / "appdata"
    path.mkdir()
    monkeypatch.setenv("APPDATA", str(path))
    return path


@pytest.fixture(autouse=True)
def private_reka_channel(monkeypatch):
    """Canal local propre aux tests : une REKA réellement ouverte sur cette
    machine n'est ni détectée ni dérangée (une connexion l'afficherait)."""
    from core import reka_link

    monkeypatch.setattr(reka_link, "instance_name", lambda: f"REKA-test-{os.getpid()}-show")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from ui import styles

    app = QApplication.instance() or QApplication([])
    styles.load_fonts()
    styles.set_theme("studio")
    styles.apply(app)
    return app


@pytest.fixture
def cfg(appdata):
    from core import config

    return config.load_config()


def pump(app, seconds: float) -> None:
    """Fait tourner la boucle Qt (les signaux venant d'autres threads arrivent en file)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def wait_for(app, condition, timeout: float = 3.0) -> bool:
    """Fait tourner la boucle Qt jusqu'à ce que `condition()` soit vraie."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


@pytest.fixture
def taskbar(qapp, cfg):
    """La barre en démo (Voicemeeter, REKA, fenêtres… simulés), affichée."""
    import main

    cfg["shortcuts"] = [{"name": "Jeux", "path": str(ROOT)}]
    app = main.TaskbarApp(cfg, demo=True, animate=False)
    app.start()
    app.bar.setFixedWidth(1920)
    assert wait_for(qapp, lambda: app.vm.connected and app.vm.params is not None)
    pump(qapp, 0.1)
    yield app
    app.shutdown()
    app.bar.close()
