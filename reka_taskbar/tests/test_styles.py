"""Thèmes : la barre doit obtenir exactement les couleurs de REKA."""

from PySide6.QtGui import QColor

from ui import styles

# Valeurs calculées par ui/styles.py de REKA (theme_palette) pour les mêmes thèmes
REKA_PALETTES = {
    "studio": {"GREEN_NEON": "#3b82f6", "BG_COLUMN": "#161920", "BG_WINDOW": "#0f1115",
               "TEXT_PRIMARY": "#f8fafc", "BORDER_COLUMN": "#2a2f3d", "GREEN_BRIGHT": "#60a5fa"},
    "rose": {"GREEN_NEON": "#ff4fb8", "BG_COLUMN": "#160e13", "BG_WINDOW": "#0b0409",
             "TEXT_PRIMARY": "#e8e2e6", "BORDER_COLUMN": "#20161c", "GREEN_BRIGHT": "#ff76c8"},
    "#b266ff": {"GREEN_NEON": "#b266ff", "BG_COLUMN": "#120e16", "BG_WINDOW": "#07040b",
                "TEXT_PRIMARY": "#e5e2e8", "BORDER_COLUMN": "#1b1620", "GREEN_BRIGHT": "#c388ff"},
    # Un bleu pur serait illisible : REKA l'éclaircit jusqu'au contraste voulu
    "#0000ff": {"GREEN_NEON": "#7070ff", "BG_COLUMN": "#0e0e16", "BG_WINDOW": "#04050b",
                "TEXT_PRIMARY": "#e2e2e8", "BORDER_COLUMN": "#161620", "GREEN_BRIGHT": "#8f8fff"},
}


def test_palettes_match_reka(qapp):
    for theme, expected in REKA_PALETTES.items():
        _name, values = styles.theme_palette(theme)
        assert {key: values[key] for key in expected} == expected, theme


def test_unknown_theme_falls_back_to_default(qapp):
    assert styles.theme_palette("inconnu")[0] == "studio"
    assert styles.theme_palette(None)[0] == "studio"


def test_set_theme_reports_changes_and_element_colors(qapp):
    try:
        assert styles.set_theme("rose", {"vu": "#00e5ff", "name@2": "#5865F2", "faux": "rouge"})
        assert styles.GREEN_NEON == "#ff4fb8" and styles.current_theme() == "rose"
        assert not styles.set_theme("rose", {"vu": "#00e5ff", "name@2": "#5865f2"})   # identique
        assert styles.accent("vu", 0) == "#00e5ff"            # couleur de toute la console
        assert styles.accent("name", 2) == "#5865f2"          # couleur d'un canal
        assert styles.accent("name", 1) == styles.TEXT_PRIMARY
        assert styles.accent("fader", 1) == "#ff4fb8"         # suit le thème
        assert styles.accent("mute") == styles.MUTE_ON
        assert "faux" not in styles.COLORS
    finally:
        styles.set_theme("studio")
        styles.apply(qapp)


def test_ink_is_readable(qapp):
    for background in ("#ffffff", "#ffd23f", "#3b82f6", "#111111"):
        ink = styles.ink_on(background)
        assert styles.contrast(QColor(background), QColor(ink)) >= 3.0
