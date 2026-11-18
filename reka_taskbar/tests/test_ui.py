"""La barre en démo : widgets, mini-console, réglages."""

import sys

from PySide6.QtCore import QDate, QLocale, QPoint, QPointF, QRect, QSize, Qt, QTime
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import pump, wait_for
from core.reka_link import RekaSetup
from ui import styles
from ui.bar import WIDGETS, bar_geometry, bar_height, centered_columns, normalized_layout
from ui.mixer_popup import db_to_position, position_to_db
from ui.popup import place
from ui.widgets.base import format_db, level_fraction
from ui.widgets.general import clock_texts
from ui.widgets.reka import abbreviate, mic_strip, route_label, step_gain


def wheel(widget, steps: int) -> None:
    center = QPointF(widget.rect().center())
    event = QWheelEvent(center, QPointF(widget.mapToGlobal(center.toPoint())), QPoint(0, 0),
                        QPoint(0, 120 * steps), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


# --- fonctions pures ---------------------------------------------------------------
def test_names_and_formats():
    assert [abbreviate(n) for n in ("Microphone", "Musique", "Autres 1", "Autres 2", "Jeu vidéo",
                                    "Écran", "", "DJ")] == ["MIC", "MUS", "AU1", "AU2", "JV",
                                                            "ECR", "?", "DJ"]
    assert [route_label(n) for n in ("Monitor", "Mic Out", "Discord", "Obs")] == \
        ["MON", "MIC", "DIS", "OBS"]
    assert format_db(2) == "+2,0 dB" and format_db(-9.04) == "-9,0 dB" and format_db(0) == "0,0 dB"
    assert step_gain(11.5, 1, 1.0) == 12.0 and step_gain(-59.5, -3, 1.0) == -60.0
    assert level_fraction(-100) == 0.0 and level_fraction(6) == 1.0


def test_fader_scale_round_trips():
    assert db_to_position(12) == 0.0 and db_to_position(-60) == 1.0
    assert db_to_position(0) == 0.15
    for db in (12.0, 6.0, 0.0, -3.5, -12.0, -30.0, -59.0, -60.0):
        assert abs(position_to_db(db_to_position(db)) - db) <= 0.1
    assert db_to_position(-20) < db_to_position(-30)      # plus fort = plus haut


def test_layout_is_cleaned():
    cfg = {"layout": {"left": ["start", "inconnu", "clock"], "center": ["clock", "media"],
                      "right": "pas une liste"}}
    assert normalized_layout(cfg) == {"left": ["start", "clock"], "center": ["media"], "right": []}
    assert normalized_layout({}) == {"left": [], "center": [], "right": []}
    assert bar_height({"bar": {"height": 500}}) == 72 and bar_height({"bar": {"height": "x"}}) == 44


def test_compact_layout_replaces_the_main_one(taskbar):
    cfg = taskbar.cfg
    cfg["layout"] = {"left": ["start", "media", "shortcuts"], "center": [], "right": ["clock"]}
    cfg["compact_layout"] = {"left": ["reka", "tasks"], "center": [], "right": ["mic", "clock"]}
    assert normalized_layout(cfg)["left"] == ["start", "media", "shortcuts"]
    cfg["bar"]["compact"] = True
    assert normalized_layout(cfg) == {"left": ["reka", "tasks"], "center": [],
                                      "right": ["mic", "clock"]}
    cfg["bar"]["height"] = 30
    taskbar.bar.apply_config()
    pump(qapp_of(taskbar), 0.05)
    assert sorted(taskbar.bar.widgets) == ["clock", "mic", "reka", "tasks"]
    assert taskbar.bar.height() == 30
    cfg["bar"]["compact"] = False
    taskbar.bar.apply_config()
    assert "media" in taskbar.bar.widgets and "start" in taskbar.bar.widgets and "reka" not in taskbar.bar.widgets


def qapp_of(taskbar):
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


def test_guard_is_harmless_outside_windows(taskbar):
    taskbar.bar._guard_stacking()          # ne lève rien, ne fait rien hors Windows
    taskbar.bar.summon()
    assert taskbar.bar._behind is False


class FakeWinApi:
    """Ce que la barre demande à Windows pour se placer, sans Windows."""

    HWND_TOP, HWND_TOPMOST, HWND_BOTTOM = 0, -1, 1
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10

    def __init__(self):
        self.calls = []
        self.topmost = True
        self.foreground = []
        api = self

        class User32:
            def SetWindowPos(self, _hwnd, after, *_rest):     # noqa: N802
                api.calls.append(after)
                api.topmost = after == api.HWND_TOPMOST
                return True

        self.user32 = User32()

    def is_topmost(self, _hwnd):
        return self.topmost

    def force_foreground(self, hwnd):
        self.foreground.append(hwnd)
        return True


def test_bar_goes_behind_fullscreen_games_and_can_be_summoned(qapp, taskbar, monkeypatch):
    import types

    import core
    import ui.bar as bar_module
    from core import appbar

    bar = taskbar.bar
    api = FakeWinApi()
    monkeypatch.setitem(sys.modules, "core.winapi", api)
    monkeypatch.setattr(core, "winapi", api, raising=False)
    monkeypatch.setattr(bar_module, "sys", types.SimpleNamespace(platform="win32",
                                                                 executable=sys.executable))
    monkeypatch.setattr(bar_module, "QCursor", types.SimpleNamespace(pos=lambda: QPoint(-999, -999)))
    game = {"hwnd": 0}
    monkeypatch.setattr(appbar, "fullscreen_foreground", lambda _own: game["hwnd"])
    monkeypatch.setattr(bar, "_persist", True)
    try:
        bar._guard_stacking()
        assert not bar.behind and api.calls == []              # déjà devant : rien demandé
        game["hwnd"] = 777                                     # un jeu passe en plein écran
        bar._guard_stacking()
        assert bar.behind and api.calls == [api.HWND_BOTTOM] and not bar.updatesEnabled()
        assert bar.is_busy()                                   # pas de mise à jour en plein jeu
        bar._guard_stacking(tick=True)
        bar._guard_stacking(tick=True)
        assert api.calls == [api.HWND_BOTTOM]                  # pas de va-et-vient chaque seconde
        tasks = bar.widgets["tasks"]
        before = len(tasks.buttons)
        taskbar.windows.close(tasks.buttons[0].info.hwnd)
        tasks.refresh()
        assert len(tasks.buttons) == before                    # derrière le jeu : plus de relevé

        bar.summon()                                           # raccourci : la barre revient
        assert not bar.behind and api.calls[-1] == api.HWND_TOPMOST and bar.updatesEnabled()
        for _second in range(bar_module.SUMMON_IDLE_S - 1):
            bar._guard_stacking(tick=True)
        assert not bar.behind                                  # encore un instant…
        bar._guard_stacking(tick=True)
        assert bar.behind and api.calls[-1] == api.HWND_BOTTOM  # …puis elle repart seule

        bar.summon()
        bar.summon()                                           # deuxième appui : renvoyée
        assert bar.behind

        api.topmost = True                                     # Qt l'a remontée : on la recache
        bar._guard_stacking()
        assert api.calls[-1] == api.HWND_BOTTOM

        game["hwnd"] = 0                                       # le jeu quitte le plein écran
        bar._guard_stacking()
        assert not bar.behind and api.calls[-1] == api.HWND_TOPMOST
        api.topmost = False                                    # quelqu'un lui a retiré « au-dessus »
        bar._guard_stacking()
        assert api.calls[-1] == api.HWND_TOPMOST and api.topmost

        bar.open_settings("")                                  # fenêtre de la barre : devant tout
        assert api.foreground and api.foreground[-1] == int(bar._settings.winId())
        bar._settings.close()
    finally:
        bar._behind = False
        bar.setUpdatesEnabled(True)


def test_geometry_helpers():
    screen = QRect(0, 0, 1920, 1080)
    assert bar_geometry(screen, "top", 44) == QRect(0, 0, 1920, 44)
    assert bar_geometry(screen, "bottom", 44) == QRect(0, 1036, 1920, 44)
    below = place(QRect(900, 6, 100, 32), QSize(400, 300), screen)       # barre en haut
    assert below == QPoint(749, 46)
    above = place(QRect(1850, 1042, 60, 32), QSize(400, 300), screen)    # barre en bas, au bord
    assert above.y() == 1042 - 8 - 300 and above.x() == 1920 - 8 - 400


def test_centered_columns():
    assert centered_columns(1904, 300, 200, 700, 12) == 790    # 790 + 12 + 300 + 12 + 790
    assert centered_columns(1904, 300, 200, 900, 12) == 0      # pas la place : pas de centrage forcé
    assert centered_columns(1904, 0, 200, 300, 12) == 0        # rien au milieu


def test_clock_texts():
    locale = QLocale(QLocale.Language.French)
    assert clock_texts(QTime(14, 5, 9), QDate(2026, 11, 15), False, locale) == \
        ("14:05", "dim. 15 nov.")
    assert clock_texts(QTime(14, 5, 9), QDate(2026, 11, 15), True, locale)[0] == "14:05:09"


def test_mic_strip_choice():
    setup = RekaSetup(found=True, mic_strip=3)
    assert mic_strip({}, setup) == 3                                   # comme dans REKA
    assert mic_strip({"widgets": {"mic": {"strip": 1}}}, setup) == 1   # choisi dans la barre
    assert mic_strip({"widgets": {"mic": {"strip": 40}}}, setup) == 5  # borné
    assert mic_strip({"widgets": {"mic": {"strip": "x"}}}, setup) == 3


# --- la barre ----------------------------------------------------------------------
def test_bar_builds_every_widget_of_the_layout(taskbar):
    bar = taskbar.bar
    wanted = [key for keys in normalized_layout(taskbar.cfg).values() for key in keys]
    assert sorted(bar.widgets) == sorted(wanted)
    assert bar.height() == 44
    for key in ("reka", "strips", "mic", "headphone", "media", "clock", "tasks", "start"):
        assert bar.widgets[key].isVisible(), key
    assert not bar.grab().isNull()


def test_every_known_widget_can_be_placed(qapp, taskbar):
    taskbar.cfg["layout"] = {"left": list(WIDGETS), "center": [], "right": []}
    taskbar.bar.build_widgets()
    pump(qapp, 0.1)
    assert sorted(taskbar.bar.widgets) == sorted(WIDGETS)


def test_strip_chip_mutes_the_reka_channel(qapp, taskbar):
    chips = taskbar.bar.widgets["strips"].chips
    assert [c.name for c in chips] == ["Microphone", "Musique", "Appels", "Bureau",
                                       "Autres 1", "Autres 2"]
    assert chips[2].muted and not chips[1].muted               # Appels est coupé dans la démo
    QTest.mouseClick(chips[1], Qt.MouseButton.LeftButton)      # clic sur « Musique »
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[1].Mute") == 1.0)
    assert wait_for(qapp, lambda: chips[1].muted)
    QTest.mouseClick(chips[2], Qt.MouseButton.LeftButton)      # « Appels » = strip 5 de Potato
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[5].Mute") == 0.0)


def test_wheel_changes_the_channel_volume(qapp, taskbar):
    chip = taskbar.bar.widgets["strips"].chips[1]              # Musique : -9 dB
    wheel(chip, 2)
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[1].Gain") == -7.0)
    assert wait_for(qapp, lambda: chip.gain == -7.0)


def test_mic_widget_toggles_the_mic(qapp, taskbar):
    mic = taskbar.bar.widgets["mic"]
    assert not mic.muted
    QTest.mouseClick(mic, Qt.MouseButton.LeftButton)
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[0].Mute") == 1.0 and mic.muted)
    assert mic.tint is not None and mic.icon.name == "mic_off"
    taskbar.bar.toggle_mic()                                   # le raccourci clavier global
    assert wait_for(qapp, lambda: not mic.muted)
    taskbar.cfg["widgets"]["mic"]["strip"] = 1                 # micro sur un autre canal
    taskbar.bar.toggle_mic()
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[1].Mute") == 1.0)


def test_headphone_widget(qapp, taskbar):
    headphone = taskbar.bar.widgets["headphone"]
    assert headphone.value.text == "0,0 dB"
    wheel(headphone, -3)
    assert wait_for(qapp, lambda: taskbar.remote.peek("Bus[0].Gain") == -3.0)
    assert wait_for(qapp, lambda: headphone.value.text == "-3,0 dB")
    QTest.mouseClick(headphone, Qt.MouseButton.LeftButton)
    assert wait_for(qapp, lambda: headphone.muted and headphone.value.text == "Muet")
    QTest.mouseClick(headphone, Qt.MouseButton.MiddleButton)   # clic du milieu : 0 dB
    assert wait_for(qapp, lambda: taskbar.remote.peek("Bus[0].Gain") == 0.0)


def test_widgets_follow_voicemeeter_stopping(qapp, taskbar, monkeypatch):
    monkeypatch.setattr("core.voicemeeter.RETRY_STOPPED_S", 0.05)
    bar = taskbar.bar
    assert bar.widgets["reka"].status() == "ok"
    taskbar.remote.running = False
    assert wait_for(qapp, lambda: not taskbar.vm.connected)
    pump(qapp, 0.05)
    assert bar.widgets["reka"].status() == "partial"           # REKA ouverte, Voicemeeter fermé
    assert not bar.widgets["strips"].chips[0].connected
    assert bar.widgets["headphone"].value.text == "—"
    QTest.mouseClick(bar.widgets["mic"], Qt.MouseButton.LeftButton)     # sans effet
    taskbar.remote.running = True
    assert wait_for(qapp, lambda: taskbar.vm.connected and bar.widgets["strips"].chips[0].connected)
    assert taskbar.remote.peek("Strip[0].Mute") == 0.0


def test_reka_button_shows_the_console(qapp, taskbar):
    QTest.mouseClick(taskbar.bar.widgets["reka"], Qt.MouseButton.LeftButton)
    assert taskbar.reka.shown == 1
    assert "REKA est ouverte" in taskbar.bar.widgets["reka"].toolTip()


def full_media(qapp, taskbar):
    """Le lecteur dans le style « pochette, titre et artiste, boutons »."""
    taskbar.cfg["widgets"]["media"]["style"] = "full"
    taskbar.bar.build_widgets()
    pump(qapp, 0.1)
    return taskbar.bar.widgets["media"]


def test_media_widget(qapp, taskbar):
    media = full_media(qapp, taskbar)
    assert media.title.text == "Néons de minuit — Les Ondes" and media.play.name == "pause"
    media.next.click()
    assert media.title.text == "Ligne de basse — Studio 206"
    media.play.click()
    assert media.play.name == "play"
    taskbar.media._publish(None)                               # plus rien ne joue
    assert media.isVisible() and media.title.text == "Aucune lecture"   # le lecteur reste
    assert not media.play.isVisible() and media.progress == 0.0
    media.show_idle = False                                    # option « toujours afficher »
    media._show(None)
    assert not media.isVisible()


def test_media_widget_shows_track_progress(qapp, taskbar):
    media = full_media(qapp, taskbar)
    info = taskbar.media.current
    assert info.duration == 214.0 and info.can_seek
    assert 0.3 < media.progress < 0.4                          # 71 s sur 214
    assert media.title.two_lines                               # barre de 44 px : titre / artiste
    taskbar.media.seek(107.0)
    assert abs(media.progress - 0.5) < 0.02
    assert not media.grab().isNull()


def test_media_wave_style_is_the_default(qapp, taskbar):
    from ui.widgets.general import music_strip

    media = taskbar.bar.widgets["media"]
    assert media.style == "wave"
    assert media.badge.isVisible() and media.wave.isVisible() and media.title.isVisible()
    assert not media.cover.isVisible() and not media.play.isVisible()
    assert media.title.text == "Néons de minuit"                # le nom du morceau seul
    assert media.badge.source == "app:C:/Apps/Spotify.exe"       # icône de l'application qui joue
    assert "Les Ondes" in media.toolTip()

    assert music_strip(taskbar.cfg, taskbar.vm.setup) == 1       # « Musique » de REKA
    taskbar.cfg["widgets"]["media"]["level_strip"] = 3
    assert music_strip(taskbar.cfg, taskbar.vm.setup) == 3
    taskbar.cfg["widgets"]["media"]["level_strip"] = -1

    wave = media.wave
    assert wave.playing and not wave.simulated                   # la démo envoie des niveaux
    wave._real_at = -1e9                                         # canal Musique muet longtemps
    assert wave.simulated
    for _frame in range(20):
        wave.step()
    assert max(wave.heights) > 0.3                               # elle danse toute seule
    wave.set_level_db(-6.0)                                      # canal Musique fort
    assert not wave.simulated
    for _frame in range(20):
        wave.step()
    loud = max(wave.heights)
    wave.set_level_db(-40.0)                                     # canal Musique faible
    for _frame in range(40):
        wave.step()
    assert max(wave.heights) < loud

    QTest.mouseClick(media, Qt.MouseButton.MiddleButton, pos=QPoint(4, media.height() // 2))
    assert not taskbar.media.current.playing and not wave.playing   # clic du milieu : pause
    for _frame in range(80):
        wave.step()
    assert wave.heights == [0.12] * wave.BARS                     # en pause, elle se pose
    assert not media.grab().isNull()


def test_media_wave_follows_the_music_channel(qapp, taskbar):
    from core.voicemeeter import MixerLevels

    media = taskbar.bar.widgets["media"]
    strips = [(-60.0, -60.0)] * len(taskbar.vm.setup.strips)
    strips[1] = (-12.0, -10.0)                                   # Musique
    taskbar.vm.levels_changed.emit(MixerLevels(tuple(strips)))
    assert not media.wave.simulated and abs(media.wave._target - 0.905 ** 0.6) < 0.01   # -10 dB


def test_media_player_popup(qapp, taskbar):
    media = taskbar.bar.widgets["media"]
    QTest.mouseClick(media, Qt.MouseButton.LeftButton, pos=QPoint(8, media.height() // 2))
    popup = media._popup
    assert popup is not None and popup.isVisible()
    assert popup.title.text() == "Néons de minuit" and popup.artist.text() == "Les Ondes"
    assert popup.album.text() == "Nuit blanche" and popup.cover.has_cover
    assert popup.total.text() == "3:34" and popup.seek.seekable
    popup.seek.seeked.emit(30.0)                               # clic sur la frise
    assert abs(taskbar.media.current.position_at() - 30.0) < 1.0
    popup.next.click()
    assert popup.title.text() == "Ligne de basse" and media.title.text.startswith("Ligne de basse")
    popup.play.click()
    assert popup.play.name == "play" and media.play.name == "play"
    assert not popup.grab().isNull()
    taskbar.media._publish(None)
    assert popup.title.text() == "Rien en lecture" and not popup.seek.isVisible()
    popup.close()
    pump(qapp, 0.05)


def test_media_player_shows_the_playing_app(qapp, taskbar):
    from ui.media_player import MediaPopup

    popup = MediaPopup(taskbar.media, taskbar.windows)
    assert popup.open_app.text() == "Afficher Spotify"
    spotify = next(w for w in taskbar.windows.windows() if w.app == "Spotify")
    taskbar.windows.minimize(spotify.hwnd)
    assert popup.show_app()
    window = next(w for w in taskbar.windows.windows() if w.app == "Spotify")
    assert window.active and not window.minimized
    actions = [label for label, _c in taskbar.bar.widgets["media"].menu_actions()]
    assert actions == ["Ouvrir le lecteur…", "Afficher Spotify"]


def test_media_player_is_in_the_middle_of_the_bar(qapp, taskbar):
    bar = taskbar.bar
    assert "media" in normalized_layout(taskbar.cfg)["center"]
    media = bar.widgets["media"]

    def offset() -> float:
        pump(qapp, 0.1)
        return media.mapTo(bar, media.rect().center()).x() - bar.width() / 2

    # Démo : la zone de droite (tout affiché) dépasse la moitié de la barre ; le
    # lecteur est alors aussi près du centre que possible, la droite au plus juste
    right = bar._zones["right"]
    assert abs(offset()) < 110 and right.width() == right.minimumSizeHint().width()
    taskbar.cfg["layout"]["right"] = ["strips", "mic", "headphone", "clock"]
    bar.build_widgets()
    media = bar.widgets["media"]
    assert abs(offset()) <= 1                                  # la place : centre exact
    taskbar.media.next()                                       # titre d'une autre longueur
    assert abs(offset()) <= 1


def test_tasks_widget(qapp, taskbar):
    tasks = taskbar.bar.widgets["tasks"]
    buttons = tasks.buttons
    assert len(buttons) == 6 and buttons[1].info.active
    QTest.mouseClick(buttons[3], Qt.MouseButton.LeftButton)    # afficher OBS
    assert tasks.buttons[3].info.active and not tasks.buttons[1].info.active
    QTest.mouseClick(tasks.buttons[3], Qt.MouseButton.LeftButton)   # déjà devant : réduire
    assert tasks.buttons[3].info.minimized
    QTest.mouseClick(tasks.buttons[0], Qt.MouseButton.MiddleButton)  # clic du milieu : fermer
    assert wait_for(qapp, lambda: len(tasks.buttons) == 5)


def test_tasks_overflow_keeps_the_active_window(qapp, taskbar):
    tasks = taskbar.bar.widgets["tasks"]
    taskbar.windows.activate(tasks.buttons[5].info.hwnd)
    tasks.setMaximumWidth(120)
    tasks.resize(120, tasks.height())
    tasks.refresh()
    pump(qapp, 0.05)
    shown = [b for b in tasks.buttons if b.isVisible()]
    assert tasks.buttons[5] in shown and len(shown) < 6
    assert tasks.overflow.isVisible() and tasks.overflow.text == f"+{6 - len(shown)}"


def test_tasks_overflow_menu_opens_hidden_and_minimized_windows(qapp, taskbar):
    tasks = taskbar.bar.widgets["tasks"]
    taskbar.windows.minimize(tasks.buttons[4].info.hwnd)       # l'Explorateur, réduit
    tasks.setMaximumWidth(120)
    tasks.resize(120, tasks.height())
    tasks.refresh()
    pump(qapp, 0.05)
    hidden = tasks.hidden_windows
    assert hidden and len(hidden) == 6 - len([b for b in tasks.buttons if b.isVisible()])
    menu = tasks.overflow_menu()
    labels = [a.text() for a in menu.actions()]
    assert any(label.endswith("(réduite)") for label in labels)
    target = next(i for i, info in enumerate(hidden) if info.minimized)
    menu.actions()[target].trigger()
    window = next(w for w in taskbar.windows.windows() if w.hwnd == hidden[target].hwnd)
    assert window.active and not window.minimized


def test_minimized_window_comes_back_on_click(qapp, taskbar):
    tasks = taskbar.bar.widgets["tasks"]
    button = tasks.buttons[2]
    taskbar.windows.minimize(button.info.hwnd)
    tasks.refresh()
    assert tasks.buttons[2].info.minimized
    QTest.mouseClick(tasks.buttons[2], Qt.MouseButton.LeftButton)
    assert tasks.buttons[2].info.active and not tasks.buttons[2].info.minimized


def test_minimized_button_lists_and_restores(qapp, taskbar):
    tasks = taskbar.bar.widgets["tasks"]
    tasks.refresh()
    assert not tasks.minimized_button.isVisibleTo(tasks)
    for button in tasks.buttons[1:3]:
        taskbar.windows.minimize(button.info.hwnd)
    tasks.refresh()
    assert tasks.minimized_button.isVisibleTo(tasks) and tasks.minimized_button.text == "▾ 2"
    labels = [a.text() for a in tasks.minimized_menu().actions()]
    assert "Tout rouvrir" in labels
    tasks.restore_all()
    assert not tasks.minimized_windows and not tasks.minimized_button.isVisibleTo(tasks)


def test_shortcuts_weather_battery_and_system(qapp, taskbar):
    bar = taskbar.bar
    assert len(bar.widgets["shortcuts"].buttons) == 1
    assert wait_for(qapp, lambda: bar.widgets["weather"].isVisible())
    assert bar.widgets["weather"].value.text == "17°"
    assert bar.widgets["battery"].value.text == "82 %"
    assert bar.widgets["system"].cpu.text == "18 %"
    taskbar.cfg["shortcuts"] = []
    bar.build_widgets()
    pump(qapp, 0.05)
    assert not bar.widgets["shortcuts"].isVisible()            # aucun raccourci : widget caché


def test_bar_follows_reka_theme(qapp, taskbar):
    try:
        taskbar.reka._setup = RekaSetup(found=True, theme="rose", colors={"name@0": "#22c55e"})
        taskbar.reka.setup_changed.emit(taskbar.reka.setup)
        assert styles.GREEN_NEON == "#ff4fb8" and styles.accent("name", 0) == "#22c55e"
        taskbar.cfg["appearance"].update(follow_reka=False, theme="or")
        taskbar.bar.apply_theme()
        assert styles.GREEN_NEON == "#ffd23f" and styles.accent("name", 0) == styles.TEXT_PRIMARY
    finally:
        styles.set_theme("studio")
        styles.apply(qapp)


def test_renamed_channels_in_reka_rebuild_the_chips(qapp, taskbar):
    setup = RekaSetup(found=True, strips=(0, 1, 5), names=("Voix", "Zik", "Jeu"))
    taskbar.reka._setup = setup
    taskbar.reka.setup_changed.emit(setup)
    strips = taskbar.bar.widgets["strips"]
    assert wait_for(qapp, lambda: [c.name for c in strips.chips] == ["Voix", "Zik", "Jeu"])
    assert wait_for(qapp, lambda: strips.chips[2].muted)       # strip 5 est coupée dans la démo


def test_context_menu(qapp, taskbar):
    menu = taskbar.bar.build_menu(taskbar.bar.widgets["mic"].icon)
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels[0] == "Couper le micro"
    assert "Réglages de la barre…" in labels and labels[-1] == "Quitter REKA Taskbar"
    menu.actions()[0].trigger()
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[0].Mute") == 1.0)


# --- mini-console -------------------------------------------------------------------
def test_mixer_popup_controls_voicemeeter(qapp, taskbar):
    bar = taskbar.bar
    bar.widgets["strips"].mixer_button.click()
    mixer = bar._mixer
    assert mixer is not None and mixer.isVisible() and len(mixer.columns) == 6
    assert mixer.columns[2].mute.isChecked() and mixer.columns[0].fader.value == 2.0
    assert [b.text() for b in mixer.routes[0]] == ["MON", "MIC", "DIS", "OBS"]
    assert [b.isChecked() for b in mixer.routes[0]] == [True, True, True, False]

    mixer.columns[1].mute.click()
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[1].Mute") == 1.0)
    mixer.routes[1][3].click()                                 # Musique → Obs (A2)
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[1].A2") == 1.0)
    fader = mixer.columns[3].fader                             # Bureau = strip 6
    QTest.mouseDClick(fader, Qt.MouseButton.LeftButton)        # double-clic : 0 dB
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[6].Gain") == 0.0)
    wheel(mixer.master.fader, -5)
    assert wait_for(qapp, lambda: taskbar.remote.peek("Bus[0].Gain") == -5.0)

    taskbar.remote.poke("Strip[0].Gain", -12.0)                # fader bougé dans REKA
    assert wait_for(qapp, lambda: mixer.columns[0].fader.value == -12.0)
    assert not mixer.grab().isNull()
    mixer.open_reka.click()
    assert taskbar.reka.shown == 1
    pump(qapp, 0.05)


def test_fader_drag(qapp, taskbar):
    taskbar.bar.open_mixer(None)
    fader = taskbar.bar._mixer.columns[0].fader
    moved = []
    fader.moved.connect(moved.append)
    start = QPoint(fader.width() - 14, round(fader._y(fader.value)))
    QTest.mousePress(fader, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(fader, start + QPoint(0, 40))
    QTest.mouseRelease(fader, Qt.MouseButton.LeftButton, pos=start + QPoint(0, 40))
    assert moved and moved[-1] < 2.0 and not fader.dragging
    assert wait_for(qapp, lambda: taskbar.remote.peek("Strip[0].Gain") == moved[-1])
    taskbar.bar._mixer.close()


# --- réglages -----------------------------------------------------------------------
def test_settings_apply_writes_config_and_rebuilds(qapp, taskbar):
    from ui.settings_dialog import HIDDEN_ZONE, KEY_ROLE, SettingsDialog

    cfg = taskbar.cfg
    dialog = SettingsDialog(cfg, taskbar.reka, taskbar.vm)
    dialog.applied.connect(taskbar.bar.apply_config)
    assert dialog.layout_from_lists() == normalized_layout(cfg)
    hidden = dialog.zone_lists[HIDDEN_ZONE]
    assert [hidden.item(i).data(KEY_ROLE) for i in range(hidden.count())] == ["network"]

    right = dialog.zone_lists["right"]
    right.addItem(hidden.takeItem(0))                          # afficher le débit du réseau
    left = dialog.zone_lists["left"]
    left.takeItem(0)                                           # retirer Démarrer
    dialog.edge.setCurrentIndex(dialog.edge.findData("bottom"))
    dialog.height_box.setValue(52)
    dialog.clock_seconds.setChecked(True)
    dialog.task_labels.setChecked(True)
    dialog.city.setText("  Lyon ")
    dialog.hotkey.setText("Ctrl+Alt+M")
    assert dialog.show_hotkey.text() == "Ctrl+Alt+B" and dialog.media_idle.isChecked()
    assert dialog.media_style.currentData() == "wave" and dialog.media_strip.currentData() == -1
    dialog.media_style.setCurrentIndex(dialog.media_style.findData("full"))
    dialog.media_strip.setCurrentIndex(dialog.media_strip.findData(1))
    dialog.show_hotkey.setText(" F14 ")
    dialog.media_idle.setChecked(False)
    dialog.mic_strip.setCurrentIndex(dialog.mic_strip.findData(1))
    dialog.follow_reka.setChecked(False)
    dialog.theme.setCurrentIndex(dialog.theme.findData("violet"))
    dialog._add_shortcut("", "C:\\Jeux\\jeu.exe")
    try:
        dialog.apply()
        pump(qapp, 0.1)
        assert cfg["bar"]["edge"] == "bottom" and cfg["bar"]["height"] == 52
        assert "start" not in cfg["layout"]["left"] and cfg["layout"]["right"][-1] == "network"
        assert cfg["widgets"]["clock"]["seconds"] and cfg["widgets"]["tasks"]["labels"]
        assert cfg["widgets"]["weather"]["city"] == "Lyon"
        assert cfg["widgets"]["mic"] == {"strip": 1, "hotkey": "Ctrl+Alt+M"}
        assert cfg["bar"]["show_hotkey"] == "F14" and cfg["widgets"]["media"]["show_idle"] is False
        assert taskbar.bar.hotkey_texts()[2][0] == "F14"
        assert not taskbar.bar.widgets["media"].show_idle
        assert cfg["widgets"]["media"]["style"] == "full" and cfg["widgets"]["media"]["level_strip"] == 1
        assert taskbar.bar.widgets["media"].style == "full"
        assert cfg["shortcuts"][-1] == {"name": "jeu", "path": "C:\\Jeux\\jeu.exe"}
        bar = taskbar.bar
        assert "start" not in bar.widgets and "network" in bar.widgets
        assert bar.height() == 52 and styles.GREEN_NEON == "#a66bff"
        assert bar.widgets["clock"].time.text.count(":") == 2
        assert taskbar.weather.city == "Lyon"
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            assert not dialog.grab().isNull()
    finally:
        dialog.close()
        styles.set_theme("studio")
        styles.apply(qapp)


def test_selftest_passes(qapp, taskbar, tmp_path):
    import main

    image = tmp_path / "selftest" / "barre.png"
    assert main.run_selftest(qapp, taskbar, image) == 0
    report = image.with_suffix(".txt").read_text(encoding="utf-8")
    assert "RÉSULTAT : OK" in report and "ÉCHEC" not in report
    assert image.is_file() and image.with_name("barre-mixer.png").is_file()
