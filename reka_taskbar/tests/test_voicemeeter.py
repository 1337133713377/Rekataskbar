"""Contrôle de Voicemeeter : le vrai VoicemeeterLink sur une API Remote simulée."""

import pytest

from conftest import pump, wait_for
from core.demo import FakeRemote, demo_link
from core.reka_link import RekaSetup
from core.voicemeeter import (STATE_CONNECTED, STATE_MISSING, STATE_STOPPED, VoicemeeterLink,
                              VoicemeeterMissing, amp_to_db, clamp_gain, input_channel)


@pytest.fixture
def link(qapp):
    vm, remote = demo_link(animate=False, poll_hz=60)
    vm.start()
    assert wait_for(qapp, lambda: vm.connected and vm.params is not None)
    yield vm, remote
    vm.stop()


def test_helpers():
    assert input_channel(0, 5) == 0 and input_channel(4, 5) == 8
    assert input_channel(5, 5) == 10 and input_channel(7, 5) == 26     # entrées virtuelles : 8 canaux
    assert input_channel(3, 3) == 6 and input_channel(4, 3) == 14      # Banana
    assert clamp_gain(40) == 12.0 and clamp_gain(-99) == -60.0 and clamp_gain(1.26) == 1.3
    assert amp_to_db(1.0) == 0.0 and amp_to_db(0.0) == -100.0


def test_reads_reka_channels_in_reka_order(link):
    vm, remote = link
    params = vm.params
    assert len(params.strips) == 6
    assert [s.gain for s in params.strips] == [2.0, -9.0, -3.0, -6.0, -14.0, -20.0]
    assert [s.mute for s in params.strips] == [False, False, True, False, False, False]
    assert params.strips[0].routes == (True, True, True, False)       # Monitor, Mic Out, Discord
    assert vm.levels is not None and len(vm.levels.strips) == 6


def test_commands_use_reka_strip_map(qapp, link):
    vm, remote = link
    vm.set_mute(2, False)             # canal 3 de REKA = strip 5 de Voicemeeter Potato
    vm.set_gain(3, 4.26)              # canal 4 = strip 6
    vm.set_route(1, 3, True)          # Musique → Obs (A2)
    vm.set_headphone_gain(-7)
    vm.set_headphone_mute(True)
    assert wait_for(qapp, lambda: remote.peek("Bus[0].Mute") == 1.0)
    assert remote.peek("Strip[5].Mute") == 0.0
    assert remote.peek("Strip[6].Gain") == pytest.approx(4.3)
    assert remote.peek("Strip[1].A2") == 1.0
    assert remote.peek("Bus[0].Gain") == -7.0
    assert wait_for(qapp, lambda: vm.params.headphone_mute and not vm.params.strips[2].mute)
    assert vm.params.strips[3].gain == 4.3 and vm.params.headphone_gain == -7.0


def test_only_last_value_of_a_parameter_is_sent(qapp, link):
    vm, remote = link
    remote.sets.clear()
    for db in range(-20, 1):
        vm.set_gain(0, db)            # un glissé de fader : 21 valeurs en rafale
    assert wait_for(qapp, lambda: remote.peek("Strip[0].Gain") == 0.0)
    assert len([s for s in remote.sets if s[0] == "Strip[0].Gain"]) <= 3


def test_change_made_in_reka_shows_up(qapp, link):
    vm, remote = link
    seen = []
    vm.params_changed.connect(seen.append)
    remote.poke("Strip[0].Mute", 1.0)            # Muet cliqué dans la console REKA
    assert wait_for(qapp, lambda: bool(seen) and seen[-1].strips[0].mute)


def test_out_of_range_indexes_are_ignored(qapp, link):
    vm, remote = link
    remote.sets.clear()
    vm.set_mute(12, True)
    vm.set_gain(-1, 3)
    vm.set_route(0, 9, True)
    pump(qapp, 0.15)
    assert remote.sets == []


def test_restart_audio_engine(qapp, link):
    vm, remote = link
    vm.restart_audio_engine()
    assert wait_for(qapp, lambda: ("Command.Restart", 1.0) in remote.sets)


def test_reconnects_when_voicemeeter_restarts(qapp, monkeypatch):
    monkeypatch.setattr("core.voicemeeter.RETRY_STOPPED_S", 0.05)
    vm, remote = demo_link(animate=False, poll_hz=60)
    states = []
    vm.state_changed.connect(states.append)
    vm.start()
    try:
        assert wait_for(qapp, lambda: vm.connected)
        remote.running = False                        # Voicemeeter fermé
        assert wait_for(qapp, lambda: vm.state == STATE_STOPPED)
        assert vm.params is None and vm.levels is None
        vm.set_mute(0, True)                          # demandé pendant la coupure
        remote.running = True                         # Voicemeeter relancé
        assert wait_for(qapp, lambda: vm.connected and vm.params is not None)
        assert wait_for(qapp, lambda: remote.peek("Strip[0].Mute") == 1.0)
        assert states[:3] == [STATE_CONNECTED, STATE_STOPPED, STATE_CONNECTED]
    finally:
        vm.stop()


def test_never_launches_voicemeeter(qapp, monkeypatch):
    monkeypatch.setattr("core.voicemeeter.RETRY_STOPPED_S", 0.05)
    remote = FakeRemote(running=False)
    vm = VoicemeeterLink(RekaSetup(), 60, remote_factory=lambda: remote)
    vm.start()
    try:
        pump(qapp, 0.3)
        assert vm.state == STATE_STOPPED and not remote.logged_in and remote.sets == []
    finally:
        vm.stop()


def test_voicemeeter_not_installed(qapp):
    def missing():
        raise VoicemeeterMissing("absent")

    vm = VoicemeeterLink(RekaSetup(), 60, remote_factory=missing)
    vm.start()
    try:
        assert wait_for(qapp, lambda: vm.state == STATE_MISSING)
    finally:
        vm.stop()


def test_adapts_to_the_edition_actually_running(qapp):
    remote = FakeRemote("banana", animate=False)      # REKA réglée sur Potato, Banana lancé
    vm = VoicemeeterLink(RekaSetup(found=True), 60, remote_factory=lambda: remote)
    setups = []
    vm.setup_changed.connect(setups.append)
    vm.start()
    try:
        assert wait_for(qapp, lambda: vm.connected and vm.params is not None)
        assert vm.setup.kind == "banana" and len(vm.params.strips) == 5
        assert setups and setups[-1].strips == (0, 1, 3, 4, 2)
        vm.set_mute(2, True)                          # canal 3 = strip 3 sur Banana
        assert wait_for(qapp, lambda: remote.peek("Strip[3].Mute") == 1.0)
    finally:
        vm.stop()


def test_configure_follows_new_reka_settings(qapp, link):
    vm, remote = link
    vm.configure(RekaSetup(found=True, strips=(1, 0), names=("B", "A"), headphone_bus="A2"))
    assert wait_for(qapp, lambda: vm.params is not None and len(vm.params.strips) == 2)
    assert vm.params.strips[0].gain == -9.0           # strip 1 de Voicemeeter en premier
    vm.set_headphone_gain(-3)
    assert wait_for(qapp, lambda: remote.peek("Bus[1].Gain") == -3.0)   # A2 = bus 1


def test_stop_sends_pending_changes(qapp):
    vm, remote = demo_link(animate=False, poll_hz=2)  # scrutation lente : le clic attend
    vm.start()
    assert wait_for(qapp, lambda: vm.connected)
    vm.set_mute(0, True)
    vm.stop()
    assert remote.peek("Strip[0].Mute") == 1.0 and not remote.logged_in
