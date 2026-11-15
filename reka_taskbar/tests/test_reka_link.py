"""Lien avec REKA : lecture de sa config, détection, demande d'affichage."""

import json

import pytest
from PySide6.QtNetwork import QLocalServer

from conftest import pump, wait_for
from core import reka_link
from core.reka_link import RekaLink, RekaSetup, parse_setup, read_setup


def reka_config(appdata, data: dict):
    folder = appdata / "REKA"
    folder.mkdir(exist_ok=True)
    path = folder / "config.json"
    tmp = path.with_suffix(".tmp")           # écriture atomique, comme REKA
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return path


def test_defaults_match_reka():
    setup = parse_setup({})
    assert setup.kind == "potato"
    assert setup.strips == (0, 1, 5, 6, 2, 7)
    assert setup.names[:2] == ("Microphone", "Musique")
    assert setup.routes == (("Monitor", "A1"), ("Mic Out", "B1"), ("Discord", "B2"), ("Obs", "A2"))
    assert setup.headphone_bus == "A1" and setup.mic_strip == 0 and setup.theme == "studio"


def test_banana_and_custom_values():
    setup = parse_setup({
        "voicemeeter": {"kind": "Banana", "strip_maps": {"banana": [0, 3, 9]},
                        "routing": [{"label": "Casque", "bus": "a2"}, {"label": "X", "bus": "A5"}],
                        "headphone_bus": "A2"},
        "ui": {"strip_names": ["Voix", ""], "theme": "#b266ff", "colors": {"vu": "#00e5ff"}},
        "discord": {"mute_strip": 7}})
    assert setup.kind == "banana"
    assert setup.strips == (0, 3)                     # 9 n'existe pas sur Banana : ignoré
    assert setup.names == ("Voix", "Musique")         # nom vide : celui par défaut
    assert setup.routes == (("Casque", "A2"), ("X", "B1"))   # A5 absent de Banana : repli de REKA
    assert setup.headphone_bus == "A2"
    assert setup.mic_strip == 1                       # borné au dernier canal
    assert setup.theme == "#b266ff" and setup.colors == {"vu": "#00e5ff"}


def test_garbage_falls_back_to_defaults():
    setup = parse_setup({"voicemeeter": {"kind": "basic", "strip_maps": {"potato": "abc"},
                                         "routing": "x", "headphone_bus": 3},
                         "ui": [], "discord": {"mute_strip": "x"}})
    assert setup.kind == "potato" and setup.strips == (0, 1, 5, 6, 2, 7)
    assert len(setup.routes) == 4 and setup.headphone_bus == "A1" and setup.mic_strip == 0


def test_read_setup_without_reka(appdata):
    setup = read_setup(appdata / "REKA" / "config.json")
    assert not setup.found and setup.strips == (0, 1, 5, 6, 2, 7)


def test_for_kind_adapts_to_running_edition():
    setup = RekaSetup(found=True, mic_strip=5)
    banana = setup.for_kind("banana")
    assert banana.strips == (0, 1, 3, 4, 2) and banana.mic_strip == 4
    assert banana.routes == (("Monitor", "A1"), ("Mic Out", "B1"), ("Discord", "B2"), ("Obs", "A2"))
    basic = setup.for_kind("basic")
    assert basic.strips == (0, 1, 2) and basic.routes == () and basic.headphone_bus == "A"
    assert setup.for_kind("potato") is setup
    assert setup.name(0) == "Microphone" and setup.name(9) == "Canal 10"


def test_link_follows_config_changes(qapp, cfg, appdata):
    link = RekaLink(cfg)
    assert not link.setup.found
    seen = []
    link.setup_changed.connect(seen.append)
    reka_config(appdata, {"ui": {"strip_names": ["Voix"], "theme": "neon"}})
    link.refresh()
    assert seen and seen[-1].found and seen[-1].names[0] == "Voix" and seen[-1].theme == "neon"
    count = len(seen)
    link.refresh()                                    # rien n'a changé : pas de signal
    assert len(seen) == count


def test_custom_config_path(qapp, cfg, tmp_path):
    other = tmp_path / "ailleurs"
    other.mkdir()
    (other / "config.json").write_text(json.dumps({"voicemeeter": {"kind": "banana"}}),
                                       encoding="utf-8")
    cfg["reka"]["config_path"] = str(other)           # un dossier ou le fichier lui-même
    assert RekaLink(cfg).setup.kind == "banana"
    cfg["reka"]["config_path"] = str(other / "config.json")
    assert RekaLink(cfg).setup.kind == "banana"


@pytest.fixture
def fake_reka(qapp):
    """Le canal local que REKA ouvre : toute connexion vaut demande d'affichage."""
    server = QLocalServer()
    name = reka_link.instance_name()
    QLocalServer.removeServer(name)
    assert server.listen(name), server.errorString()
    shows = []

    def on_connection() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            shows.append(1)
            connection.write(b"ok\n")
            connection.flush()
            connection.disconnectFromServer()

    server.newConnection.connect(on_connection)
    yield shows
    server.close()


def test_running_detection_never_asks_reka_to_show(qapp, fake_reka):
    assert reka_link.is_reka_running()
    pump(qapp, 0.1)
    assert fake_reka == []                            # détecter n'affiche pas la console


def test_not_running_without_channel(qapp):
    QLocalServer.removeServer(reka_link.instance_name())
    assert not reka_link.is_reka_running()
    assert not reka_link.request_show(timeout_ms=200)


def test_show_request_reaches_reka(qapp, cfg, fake_reka):
    import threading

    link = RekaLink(cfg)
    result = {}
    thread = threading.Thread(target=lambda: result.update(outcome=link.show_or_launch()))
    thread.start()                                    # la demande bloque : le serveur répond ici
    assert wait_for(qapp, lambda: not thread.is_alive())
    thread.join()
    assert result["outcome"] == "shown" and fake_reka == [1]


def test_running_changed_signal(qapp, cfg, fake_reka):
    link = RekaLink(cfg)
    seen = []
    link.running_changed.connect(seen.append)
    link.refresh()
    assert seen == [True] and link.running


def test_launch_needs_known_exe(qapp, cfg, tmp_path):
    link = RekaLink(cfg)
    assert link.exe_path() is None and not link.launch()
    QLocalServer.removeServer(reka_link.instance_name())
    assert link.show_or_launch() == "missing"
    cfg["reka"]["exe_path"] = str(tmp_path / "absent.exe")
    assert link.exe_path() is None                    # chemin périmé : ignoré
