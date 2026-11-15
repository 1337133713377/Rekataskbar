"""Gardien des mises à jour : lancement surveillé, confirmation, retour en arrière."""

import json

import pytest

from core import config, update_guard
from core.update_guard import (broken_exe_path, cleanup_previous, old_exe_path, read_marker,
                               rollback, start_watched_restart, startup, watch)


@pytest.fixture
def installed(tmp_path):
    """Situation juste après install() : nouvel exe en place, ancien à côté."""
    exe = tmp_path / "REKA-Taskbar.exe"
    exe.write_bytes(b"nouvelle")
    old_exe_path(exe).write_bytes(b"ancienne")
    marker = {"from": "1.0.0", "to": "1.1.0", "exe": str(exe)}
    update_guard.write_marker(marker)
    return exe, marker


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_marker_round_trip_and_startup(installed):
    exe, marker = installed
    assert read_marker()["to"] == "1.1.0"
    assert startup("1.1.0")                   # la nouvelle version est surveillée
    assert read_marker() is not None
    update_guard.confirm()
    assert read_marker() is None and not startup("1.1.0")
    update_guard.write_marker(marker)
    assert not startup("1.0.0")               # reste d'une autre mise à jour : effacé
    assert read_marker() is None
    update_guard.write_marker({**marker, "to": "9.9.9"})
    assert startup("1.1.0", exe)              # reconnue à son exe, même si la version diffère
    assert not startup("1.1.0", exe.with_name("autre.exe"))


def test_start_watched_restart(installed, tmp_path):
    exe, _marker = installed
    update_guard.remove_marker()
    launched = []
    assert start_watched_restart("1.0.0", "1.1.0", exe, lambda path, args: launched.append(
        (path, args)) or 7)
    assert launched == [(old_exe_path(exe), ["--update-watchdog"])]
    assert read_marker()["from"] == "1.0.0"

    def broken_launcher(path, args):
        raise OSError("refusé")

    assert not start_watched_restart("1.0.0", "1.1.0", exe, broken_launcher)
    assert read_marker() is None              # rien ne surveille : pas de marqueur
    assert not start_watched_restart("1.0.0", "1.1.0", tmp_path / "ailleurs.exe")


def test_watch_ok_when_the_new_version_confirms(installed):
    exe, marker = installed
    clock = Clock()
    launched = []

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.now >= 5:
            update_guard.confirm()            # la nouvelle version confirme

    result = watch(marker, launcher=lambda path, args: launched.append(args) or 42,
                   alive=lambda pid: True, kill=lambda pid: None, clock=clock, sleep=sleep)
    assert result == "ok"
    assert launched == [["--restart", "--updated-from", "1.0.0"]]
    assert exe.read_bytes() == b"nouvelle" and old_exe_path(exe).exists()


def test_watch_rolls_back_when_the_new_version_dies(installed):
    exe, marker = installed
    clock = Clock()
    launched = []
    result = watch(marker, launcher=lambda path, args: launched.append(args) or 42,
                   alive=lambda pid: False, kill=lambda pid: None, clock=clock, sleep=clock.sleep)
    assert result == "rolled_back"
    assert exe.read_bytes() == b"ancienne"                    # ancienne version remise
    assert broken_exe_path(exe).read_bytes() == b"nouvelle"
    assert not old_exe_path(exe).exists() and read_marker() is None
    assert launched[-1] == ["--restart", "--rolled-back", "1.1.0"]
    saved = config.read_json(config.user_config_path())
    assert saved["update"]["skipped_version"] == "1.1.0"      # plus réinstallée d'office
    assert "retour" in (config.app_data_dir() / update_guard.LOG_FILE).read_text("utf-8")


def test_watch_kills_a_hung_version_then_rolls_back(installed):
    exe, marker = installed
    clock = Clock()
    killed = []
    result = watch(marker, launcher=lambda path, args: 42, alive=lambda pid: True,
                   kill=killed.append, clock=clock, sleep=clock.sleep, timeout=10)
    assert result == "rolled_back" and killed == [42]
    assert exe.read_bytes() == b"ancienne"


def test_rollback_keeps_existing_user_settings(installed):
    exe, marker = installed
    config.save_config({"bar": {"edge": "bottom"}, "update": {"auto_install": False}})
    assert rollback(marker, launcher=lambda path, args: 1, sleep=lambda s: None)
    saved = config.read_json(config.user_config_path())
    assert saved["bar"]["edge"] == "bottom" and saved["update"]["auto_install"] is False
    assert saved["update"]["skipped_version"] == "1.1.0"


def test_rollback_without_old_exe(installed):
    exe, marker = installed
    old_exe_path(exe).unlink()
    assert not rollback(marker, launcher=lambda path, args: 1, sleep=lambda s: None)
    assert exe.read_bytes() == b"nouvelle" and read_marker() is None


def test_rollback_waits_for_a_locked_exe(installed, monkeypatch):
    exe, marker = installed
    real_replace = update_guard.os.replace
    calls = []

    def replace(src, dst):
        calls.append(src)
        if len(calls) <= 2 and str(src) == str(exe):
            raise PermissionError("encore verrouillé")
        return real_replace(src, dst)

    monkeypatch.setattr(update_guard.os, "replace", replace)
    assert rollback(marker, launcher=lambda path, args: 1, sleep=lambda s: None)
    assert exe.read_bytes() == b"ancienne"


def test_cleanup_removes_old_and_broken(tmp_path):
    exe = tmp_path / "REKA-Taskbar.exe"
    exe.write_bytes(b"x")
    old_exe_path(exe).write_bytes(b"old")
    broken_exe_path(exe).write_bytes(b"broken")
    assert cleanup_previous(exe)
    assert not old_exe_path(exe).exists() and not broken_exe_path(exe).exists() and exe.exists()


def test_watchdog_main_without_marker_does_nothing():
    assert update_guard.watchdog_main() == 0


def test_real_processes(tmp_path):
    """launch / process_alive / kill_tree sur de vrais processus."""
    import sys
    import time

    script = tmp_path / "attend.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    pid = update_guard.launch(__import__("pathlib").Path(sys.executable), [str(script)])
    assert update_guard.process_alive(pid)
    update_guard.kill_tree(pid)
    for _ in range(50):
        if not update_guard.process_alive(pid):
            break
        time.sleep(0.1)
    assert not update_guard.process_alive(pid)
    assert not update_guard.process_alive(0)


def test_boot_dispatches_the_watchdog(monkeypatch):
    import boot

    monkeypatch.setattr(update_guard, "watchdog_main", lambda: 7)
    monkeypatch.setattr("sys.argv", ["REKA-Taskbar.old.exe", "--update-watchdog"])
    assert boot.run() == 7


def test_marker_ignores_garbage():
    update_guard.marker_path().write_text("pas du json", encoding="utf-8")
    assert read_marker() is None
    update_guard.marker_path().write_text(json.dumps({"to": "1.1.0"}), encoding="utf-8")
    assert read_marker() is None              # sans exe : inutilisable
