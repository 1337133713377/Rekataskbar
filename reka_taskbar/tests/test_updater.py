"""Mises à jour : description en ligne, téléchargement vérifié, remplacement de
l'exe, et le cycle complet dans la barre (sans réseau)."""

import hashlib
import io
import json

import pytest

from conftest import pump, wait_for
from core import updater
from core.updater import (STATE_AVAILABLE, STATE_IDLE, STATE_READY, BuildInfo, UpdateError,
                          UpdateInfo, UpdateManager, cleanup_previous, download, install,
                          is_newer, load_build_info, old_exe_path, parse_update, version_key,
                          version_url)

EXE = b"MZ nouvelle version de la barre" * 100


def info(version="1.1.0", data=EXE, **changes) -> UpdateInfo:
    values = dict(version=version, url="https://github.com/o/r/releases/download/v1/REKA-Taskbar.exe",
                  sha256=hashlib.sha256(data).hexdigest(), size=len(data), notes="Nouveautés")
    values.update(changes)
    return UpdateInfo(**values)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_version_order():
    assert version_key("1.10.0") > version_key("1.9.9")
    assert version_key("v1.2") == (1, 2, 0) and version_key("2") == (2, 0, 0)
    assert is_newer(info("1.0.1"), "1.0.0") and not is_newer(info("1.0.0"), "1.0.0")
    assert not is_newer(info("0.9.0"), "1.0.0")
    assert not is_newer(info("1.1.0"), "1.0.0", skipped="1.1.0")
    assert is_newer(info("1.2.0"), "1.0.0", skipped="1.1.0")


def test_build_info_and_url(tmp_path):
    assert load_build_info(tmp_path / "absent.json") is None
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps({"version": "1.0.0", "repo": "o/r", "commit": "abc"}), "utf-8")
    build = load_build_info(path)
    assert build == BuildInfo("1.0.0", "o/r", "abc")
    assert version_url({}, build) == "https://github.com/o/r/releases/latest/download/version.json"
    assert version_url({"update": {"url": "https://x/v.json"}}, build) == "https://x/v.json"
    assert version_url({}, None) is None
    path.write_text("{}", "utf-8")
    assert load_build_info(path) is None


def test_parse_update_rejects_bad_descriptions():
    good = {"version": "1.1.0", "url": "https://a/b.exe", "sha256": "ab" * 32, "size": 10}
    assert parse_update(good).size == 10
    for bad in ({**good, "url": "http://a/b.exe"},         # pas de https : refusé
                {**good, "sha256": "zz" * 32}, {**good, "sha256": "ab"},
                {**good, "size": 0}, {"version": "1"}):
        with pytest.raises(UpdateError):
            parse_update(bad)


def test_fetch_update(monkeypatch):
    body = json.dumps({"version": "1.1.0", "url": "https://a/b.exe", "sha256": "cd" * 32,
                       "size": 5, "notes": "x"}).encode()
    monkeypatch.setattr(updater, "_open", lambda url, timeout: FakeResponse(body))
    assert updater.fetch_update("https://a/version.json").version == "1.1.0"
    monkeypatch.setattr(updater, "_open", lambda url, timeout: FakeResponse(b"pas du json"))
    with pytest.raises(UpdateError):
        updater.fetch_update("https://a/version.json")

    def offline(url, timeout):
        raise OSError("pas de réseau")

    monkeypatch.setattr(updater, "_open", offline)
    with pytest.raises(UpdateError, match="joindre"):
        updater.fetch_update("https://a/version.json")


def test_download_checks_size_and_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_open", lambda url, timeout: FakeResponse(EXE))
    seen = []
    dest = download(info(), tmp_path / "new.exe", lambda got, total: seen.append(got))
    assert dest.read_bytes() == EXE and seen[-1] == len(EXE)
    with pytest.raises(UpdateError, match="abîmé"):                # mauvaise empreinte
        download(info(sha256="0" * 64), tmp_path / "bad.exe")
    with pytest.raises(UpdateError, match="plus gros"):             # plus gros qu'annoncé
        download(info(size=10), tmp_path / "big.exe")
    with pytest.raises(UpdateError, match="annulé"):
        download(info(), tmp_path / "stop.exe", cancelled=lambda: True)
    assert not list(tmp_path.glob("*.part")) and not (tmp_path / "bad.exe").exists()


def test_install_replaces_the_running_exe(tmp_path):
    current = tmp_path / "REKA-Taskbar.exe"
    current.write_bytes(b"ancienne")
    new = tmp_path / "update" / "new.exe"
    new.parent.mkdir()
    new.write_bytes(EXE)
    install(new, current)
    assert current.read_bytes() == EXE
    assert old_exe_path(current).read_bytes() == b"ancienne"
    assert old_exe_path(current).name == "REKA-Taskbar.old.exe"
    assert cleanup_previous(current) and not old_exe_path(current).exists()


def test_install_failure_puts_the_old_exe_back(tmp_path, monkeypatch):
    current = tmp_path / "REKA-Taskbar.exe"
    current.write_bytes(b"ancienne")

    def broken_move(src, dst):
        raise OSError("disque plein")

    monkeypatch.setattr(updater.shutil, "move", broken_move)
    with pytest.raises(UpdateError, match="installer"):
        install(tmp_path / "new.exe", current)
    assert current.read_bytes() == b"ancienne" and not old_exe_path(current).exists()


def test_install_in_a_missing_folder_fails_cleanly(tmp_path):
    with pytest.raises(UpdateError, match="remplacer"):
        install(tmp_path / "new.exe", tmp_path / "absent" / "REKA-Taskbar.exe")


# --- gestionnaire ----------------------------------------------------------------
def manager(cfg, online=None, error=None, self_update=True, exe_error=None):
    def fetch(url):
        if error:
            raise UpdateError(error)
        return online

    def fetch_exe(update, dest):
        if exe_error:
            raise UpdateError(exe_error)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(EXE)
        return dest

    return UpdateManager(cfg, BuildInfo("1.0.0", "o/r"), fetch=fetch, fetch_exe=fetch_exe,
                         self_update=self_update)


def test_disabled_without_build_info(qapp, cfg):
    updates = UpdateManager(cfg, None)
    assert not updates.enabled and not updates.check()
    updates.start()            # ne fait rien


def test_auto_install_downloads_then_signals_ready(qapp, cfg):
    updates = manager(cfg, info())
    ready = []
    updates.ready.connect(lambda update, path: ready.append((update, path)))
    assert updates.check()
    assert wait_for(qapp, lambda: bool(ready))
    assert updates.state == STATE_READY and ready[0][1].read_bytes() == EXE
    assert not updates.check()            # déjà prête : pas de nouvelle vérification


def test_manual_mode_shows_the_button(qapp, cfg):
    cfg["update"]["auto_install"] = False
    updates = manager(cfg, info())
    available = []
    updates.available.connect(available.append)
    updates.check()
    assert wait_for(qapp, lambda: updates.state == STATE_AVAILABLE)
    assert available and updates.latest.version == "1.1.0"


def test_not_frozen_never_installs_by_itself(qapp, cfg):
    updates = manager(cfg, info(), self_update=False)
    updates.check()
    assert wait_for(qapp, lambda: updates.state == STATE_AVAILABLE)


def test_up_to_date_skipped_and_errors(qapp, cfg):
    results = []
    updates = manager(cfg, info("1.0.0"))
    updates.checked.connect(lambda update, error: results.append((update, error)))
    updates.check()
    assert wait_for(qapp, lambda: bool(results)) and results[-1] == (None, "")
    assert updates.state == STATE_IDLE

    cfg["update"]["skipped_version"] = "1.1.0"
    skipped = manager(cfg, info("1.1.0"))
    skipped.check()
    pump(qapp, 0.2)
    assert skipped.state == STATE_IDLE and skipped.latest is None
    skipped.check(manual=True)            # demandée à la main : proposée quand même
    assert wait_for(qapp, lambda: skipped.state == STATE_AVAILABLE)

    broken = manager(cfg, error="pas de réseau")
    errors = []
    broken.checked.connect(lambda update, error: errors.append(error))
    broken.check()
    assert wait_for(qapp, lambda: bool(errors)) and errors[0] == "pas de réseau"


def test_failed_download_falls_back_to_the_button(qapp, cfg):
    updates = manager(cfg, info(), exe_error="Téléchargement interrompu")
    updates.check()
    assert wait_for(qapp, lambda: updates.state == STATE_AVAILABLE)
    assert "interrompu" in updates.error


def test_skip_is_remembered(qapp, cfg):
    updates = manager(cfg, info())
    updates.skip(info())
    assert cfg["update"]["skipped_version"] == "1.1.0" and updates.latest is None


# --- dans la barre -------------------------------------------------------------------
def test_bar_installs_and_restarts(qapp, taskbar, tmp_path):
    bar = taskbar.bar
    bar.executable = tmp_path / "REKA-Taskbar.exe"
    bar.executable.write_bytes(b"ancienne")
    restarted, quit_calls = [], []
    bar.restart_after_update = lambda previous: restarted.append(previous) or True
    bar.quit = lambda: quit_calls.append(1)
    new = tmp_path / "new.exe"
    new.write_bytes(EXE)
    bar.install_ready_update(info(), new)
    assert bar.executable.read_bytes() == EXE
    assert restarted == [taskbar.updates.current_version] and quit_calls == [1]


def test_bar_waits_while_busy(qapp, taskbar, tmp_path, monkeypatch):
    bar = taskbar.bar
    installs = []
    bar.install_update = lambda new, current: installs.append(new)
    bar.restart_after_update = lambda previous: True
    bar.quit = lambda: None
    monkeypatch.setattr(updater, "BUSY_RETRY_MS", 50)
    bar.open_mixer(None)                     # l'utilisateur se sert de la mini-console
    bar.install_ready_update(info(), tmp_path / "new.exe")
    pump(qapp, 0.15)
    assert installs == []
    bar._mixer.close()
    assert wait_for(qapp, lambda: len(installs) == 1)


def test_install_failure_shows_the_update_button(qapp, taskbar, tmp_path):
    bar = taskbar.bar
    updates = taskbar.updates
    updates.latest = info()

    def refuse(new, current):
        raise UpdateError("Impossible de remplacer REKA Taskbar dans C:\\Program Files")

    bar.install_update = refuse
    bar.install_ready_update(info(), tmp_path / "new.exe")
    pump(qapp, 0.05)
    assert updates.state == STATE_AVAILABLE and "Program Files" in updates.error
    assert bar.update_widget.isVisible()
    assert bar.update_widget.label.text == "Mise à jour 1.1.0"
    labels = [a.text() for a in bar.build_menu(None).actions()]
    assert "Installer la version 1.1.0…" in labels


def test_update_button_hidden_by_default(qapp, taskbar):
    assert not taskbar.bar.update_widget.isVisible()
    labels = [a.text() for a in taskbar.bar.build_menu(None).actions()]
    assert "Rechercher les mises à jour…" in labels


def test_update_dialog(qapp, cfg):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(info(), "1.0.0", self_update=True, error="dossier protégé")
    assert dialog.install_button.isVisibleTo(dialog)
    assert "dossier protégé" in dialog.status.text()
    dialog._skip()
    assert dialog.skipped
    manual = UpdateDialog(info(), "1.0.0", self_update=False)
    assert not manual.install_button.isVisibleTo(manual)
    assert manual.browser_button.text() == "Télécharger"
    assert not manual.grab().isNull()
