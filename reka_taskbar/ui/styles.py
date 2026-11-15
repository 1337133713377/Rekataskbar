"""
Palette, thèmes et feuille de style de la barre : les mêmes que REKA.

Les noms et le calcul des couleurs reprennent ui/styles.py de REKA : avec
« suivre le thème de REKA », la barre lit ui.theme et ui.colors dans la config
de la console et obtient exactement ses teintes (thème prédéfini, couleur
d'accent libre, couleur par élément ou par canal).

La palette de référence est verte ; un thème donne une couleur d'accent, et
toutes les teintes vertes tournent vers elle en gardant leur luminosité. Les
widgets dessinés à la main lisent ces variables à chaque dessin.
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from core import config

log = logging.getLogger(__name__)

# --- Palette de référence (thème « Néon » de REKA) ---------------------------
BG_PANEL = "#0a1510"
BG_PILL = "#0a1510"
GREEN_NEON = "#00ff88"        # accent
GREEN_BRIGHT = "#00d4aa"      # survol
GREEN_DIM = "#1a4030"         # éléments inactifs
GREEN_TEXT = "#00ff88"
GREEN_LABEL = "#4d8870"
GREEN_SCALE = "#004d2a"
BG_WINDOW = "#040b07"
BG_GLOW = "#001a0f"
BG_COLUMN = "#0e1612"
BG_SECTION = "#070e0a"
BORDER_COLUMN = "#16201b"
BORDER_SECTION = "#111a15"
TEXT_PRIMARY = "#e2e8e5"
TEXT_SECONDARY = "#a3ada8"
TEXT_MUTED = "#5f6b65"
BUTTON_BG = "#1b2a24"
BUTTON_HOVER = "#223630"
PILL_BG = "#15201b"
PILL_BORDER = "#24332c"
KNOB_CAP_TOP = "#3a4642"
KNOB_CAP_BOTTOM = "#1c2421"
BG_DEEP = "#030b06"
ON_ACCENT = "#00341c"
ON_ACCENT_DARK = "#00140a"
BADGE_OFF = "#0d1a14"
WHITE = "#ffffff"
RED_MUTE = "#ff2d2d"

STUDIO_PALETTE = {
    "BG_WINDOW": "#0f1115", "BG_GLOW": "#141821", "BG_COLUMN": "#161920",
    "BG_SECTION": "#12151b", "BORDER_COLUMN": "#2a2f3d", "BORDER_SECTION": "#232836",
    "BG_PANEL": "#161920", "BG_PILL": "#1c2029", "BG_DEEP": "#0b0d11",
    "GREEN_NEON": "#3b82f6", "GREEN_TEXT": "#3b82f6", "GREEN_BRIGHT": "#60a5fa",
    "GREEN_DIM": "#1e3a68", "GREEN_LABEL": "#94a3b8", "GREEN_SCALE": "#3a4152",
    "TEXT_PRIMARY": "#f8fafc", "TEXT_SECONDARY": "#94a3b8", "TEXT_MUTED": "#5b6577",
    "BUTTON_BG": "#1f2430", "BUTTON_HOVER": "#272d3b", "PILL_BG": "#1c2029",
    "PILL_BORDER": "#2a2f3d", "KNOB_CAP_TOP": "#3a4150", "KNOB_CAP_BOTTOM": "#1b1f28",
    "ON_ACCENT": "#0b1220", "ON_ACCENT_DARK": "#0b1220", "BADGE_OFF": "#1a1e27",
}

# Couleurs fixes (indépendantes du thème)
VU_GREEN = "#22c55e"
VU_YELLOW = "#facc15"
VU_RED = "#ef4444"
MUTE_ON = "#b91c1c"
MUTE_ON_HOVER = "#dc2626"
STATUS_OK = "#22c55e"
STATUS_WARN = "#f59e0b"
STATUS_OFF = "#64748b"

DEFAULT_THEME = "studio"
THEMES = {                    # clé (ui.theme de REKA) → (nom affiché, accent)
    "studio": ("Dark Studio Pro", "#3b82f6"),
    "neon": ("Vert néon", "#00ff88"),
    "cyan": ("Cyan", "#00e5ff"),
    "bleu": ("Bleu", "#3d8bff"),
    "violet": ("Violet", "#a66bff"),
    "rose": ("Rose", "#ff4fb8"),
    "rouge": ("Rouge", "#ff3b4f"),
    "orange": ("Orange", "#ff9a1f"),
    "or": ("Or", "#ffd23f"),
    "blanc": ("Blanc", "#e9eef0"),
}
_THEMED = ("BG_PANEL", "BG_PILL", "GREEN_NEON", "GREEN_BRIGHT", "GREEN_DIM", "GREEN_TEXT",
           "GREEN_LABEL", "GREEN_SCALE", "BG_WINDOW", "BG_GLOW", "BG_COLUMN", "BG_SECTION",
           "BORDER_COLUMN", "BORDER_SECTION", "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
           "BUTTON_BG", "BUTTON_HOVER", "PILL_BG", "PILL_BORDER", "KNOB_CAP_TOP",
           "KNOB_CAP_BOTTOM", "BG_DEEP", "ON_ACCENT", "ON_ACCENT_DARK", "BADGE_OFF")
_BASE = {name: globals()[name] for name in _THEMED}
MIN_ACCENT_CONTRAST = 4.5
HOVER_TOWARD_WHITE = 0.22
_current_theme = DEFAULT_THEME

DEFAULT_FONT = "Inter"
FONT_FAMILY = DEFAULT_FONT
FONT_FALLBACK = "Segoe UI"
FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf")

# Couleurs par élément de REKA (ui.colors) : « vu », « mute@2 », « headphone »…
MASTER_SCOPE = "master"
COLORS: dict[str, str] = {}


def _valid_colors(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    colors = {}
    for key, raw in value.items():
        c = QColor(str(raw)) if isinstance(raw, str) and raw.startswith("#") else QColor()
        if isinstance(key, str) and c.isValid():
            colors[key] = c.name()
    return colors


def element_color(element: str, scope: int | str | None = None) -> str | None:
    """Couleur choisie dans REKA pour un élément : celle de son canal, sinon
    celle de toute la console ; None s'il suit le thème."""
    if scope is not None and f"{element}@{scope}" in COLORS:
        return COLORS[f"{element}@{scope}"]
    return COLORS.get(element)


def accent(element: str = "", scope: int | str | None = None) -> str:
    """Couleur principale d'un élément (ou l'accent du thème)."""
    custom = element_color(element, scope) if element else None
    if custom:
        return custom
    return {"mute": MUTE_ON, "name": TEXT_PRIMARY}.get(element, GREEN_NEON)


def mix(a: str, b: str, amount: float) -> str:
    """Couleur entre `a` (0) et `b` (1)."""
    return _mix(QColor(a), QColor(b), amount).name()


def color(value: str, alpha: float = 1.0) -> QColor:
    c = QColor(value)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def ink_on(value: str) -> str:
    """Encre lisible sur une couleur de fond."""
    background, dark = QColor(value), QColor(ON_ACCENT_DARK)
    return dark.name() if contrast(background, dark) >= contrast(background, QColor(WHITE)) else WHITE


def font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies([FONT_FAMILY, FONT_FALLBACK])
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def load_fonts() -> bool:
    loaded = False
    for name in FONT_FILES:
        path = config.resource_path(f"assets/{name}")
        if path.is_file() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded = True
        else:
            log.warning("Police introuvable ou illisible : %s", path)
    return loaded


def theme_accent(theme: str | None) -> QColor | None:
    """Accent d'un thème (clé de THEMES ou « #rrggbb »), None si invalide."""
    if theme in THEMES:
        return QColor(THEMES[theme][1])
    value = QColor(str(theme or ""))
    return value if str(theme or "").startswith("#") and value.isValid() else None


def luminance(c: QColor) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c.red()) + 0.7152 * channel(c.green()) + 0.0722 * channel(c.blue())


def contrast(a: QColor, b: QColor) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * amount),
                  round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount))


def _rotate(value: str, hue_shift: float, saturation: float) -> str:
    h, s, l, _a = QColor(value).getHslF()
    if h < 0:
        return value
    return QColor.fromHslF((h + hue_shift) % 1.0, max(0.0, min(1.0, s * saturation)), l).name()


def theme_palette(theme: str | None) -> tuple[str, dict[str, str]]:
    """(thème retenu, couleurs de sa palette) : le calcul de REKA, à l'identique."""
    accent_color = theme_accent(theme)
    if accent_color is None:
        theme, accent_color = DEFAULT_THEME, QColor(THEMES[DEFAULT_THEME][1])
    values = dict(_BASE)
    if theme == "studio":
        values.update(STUDIO_PALETTE)
    elif theme != "neon":
        ah, as_, al, _ = accent_color.getHslF()
        bh, bs, _bl, _ = QColor(_BASE["GREEN_NEON"]).getHslF()
        shift = ah - bh if ah >= 0 else 0.0
        saturation = as_ / bs if ah >= 0 and bs > 0 else 0.0
        values = {name: _rotate(value, shift, saturation) for name, value in _BASE.items()}
        background = QColor(values["BG_COLUMN"])
        while contrast(accent_color, background) < MIN_ACCENT_CONTRAST and al < 0.95:
            al = min(0.95, al + 0.02)
            accent_color = QColor.fromHslF(max(ah, 0.0), as_, al)
        values["GREEN_NEON"] = values["GREEN_TEXT"] = accent_color.name()
        values["GREEN_BRIGHT"] = _mix(accent_color, QColor("#ffffff"), HOVER_TOWARD_WHITE).name()
        if contrast(accent_color, QColor(values["ON_ACCENT"])) < 4.5:
            values["ON_ACCENT"] = values["ON_ACCENT_DARK"]
    return theme, values


def set_theme(theme: str | None, colors: dict | None = None, font_family: str = "") -> bool:
    """Applique un thème, les couleurs par élément et la police ; True si
    quelque chose a changé (il faut alors redessiner)."""
    global _current_theme, COLORS, FONT_FAMILY
    theme, values = theme_palette(theme)
    colors = _valid_colors(colors)
    family = font_family.strip() or DEFAULT_FONT
    changed = (theme != _current_theme or colors != COLORS or family != FONT_FAMILY
               or any(globals()[name] != value for name, value in values.items()))
    globals().update(values)
    _current_theme, COLORS, FONT_FAMILY = theme, colors, family
    return changed


def current_theme() -> str:
    return _current_theme


def rgba(value: str, alpha: float) -> str:
    c = QColor(value)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {max(0.0, min(1.0, alpha)):.3f})"


def apply(app: QApplication) -> None:
    """Palette Qt, police et feuille de style aux couleurs du thème en cours."""
    palette = QPalette()
    for role, value in (
            (QPalette.ColorRole.Window, BG_WINDOW), (QPalette.ColorRole.WindowText, TEXT_PRIMARY),
            (QPalette.ColorRole.Base, BG_SECTION), (QPalette.ColorRole.AlternateBase, BG_COLUMN),
            (QPalette.ColorRole.Text, TEXT_PRIMARY), (QPalette.ColorRole.Button, BUTTON_BG),
            (QPalette.ColorRole.ButtonText, TEXT_PRIMARY),
            (QPalette.ColorRole.Highlight, GREEN_NEON),
            (QPalette.ColorRole.HighlightedText, ink_on(GREEN_NEON)),
            (QPalette.ColorRole.ToolTipBase, BG_COLUMN),
            (QPalette.ColorRole.ToolTipText, TEXT_PRIMARY),
            (QPalette.ColorRole.PlaceholderText, TEXT_MUTED)):
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_MUTED))
    app.setPalette(palette)
    app.setFont(font(12))
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    return f"""
QToolTip {{
    background: {BG_COLUMN}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    padding: 5px 8px; border-radius: 6px;
}}
QMenu {{
    background: {BG_COLUMN}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {BUTTON_HOVER}; }}
QMenu::item:disabled {{ color: {TEXT_MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER_COLUMN}; margin: 5px 8px; }}
QDialog, QWidget#popup {{ background: {BG_WINDOW}; color: {TEXT_PRIMARY}; }}
QFrame#popupFrame {{
    background: {BG_WINDOW}; border: 1px solid {BORDER_COLUMN}; border-radius: 12px;
}}
QFrame#column {{
    background: {BG_COLUMN}; border: 1px solid {BORDER_COLUMN}; border-radius: 10px;
}}
QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
QLabel#secondary {{ color: {TEXT_SECONDARY}; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#heading {{ font-size: 13px; font-weight: 600; color: {TEXT_PRIMARY}; }}
QPushButton {{
    background: {BUTTON_BG}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    border-radius: 7px; padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {BUTTON_HOVER}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; }}
QPushButton#primary {{
    background: {GREEN_NEON}; color: {ink_on(GREEN_NEON)}; border: 1px solid {GREEN_NEON};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {GREEN_BRIGHT}; border-color: {GREEN_BRIGHT}; }}
QPushButton#muteButton {{ padding: 4px 6px; font-weight: 600; }}
QPushButton#muteButton:checked {{
    background: {accent("mute")}; border: 1px solid {MUTE_ON_HOVER}; color: {WHITE};
}}
QPushButton#routeButton {{
    padding: 2px 4px; font-size: 10px; min-height: 14px; border-radius: 5px;
    color: {TEXT_MUTED}; background: {BG_SECTION};
}}
QPushButton#routeButton:checked {{
    color: {ink_on(GREEN_NEON)}; background: {GREEN_NEON}; border-color: {GREEN_NEON};
    font-weight: 600;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG_SECTION}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    border-radius: 6px; padding: 5px 8px; min-height: 18px;
    selection-background-color: {GREEN_NEON}; selection-color: {ink_on(GREEN_NEON)};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {GREEN_NEON};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {BG_COLUMN}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    selection-background-color: {BUTTON_HOVER}; selection-color: {TEXT_PRIMARY}; outline: none;
}}
QCheckBox {{ color: {TEXT_PRIMARY}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid {PILL_BORDER};
    background: {BG_SECTION};
}}
QCheckBox::indicator:checked {{ background: {GREEN_NEON}; border-color: {GREEN_NEON}; }}
QListWidget {{
    background: {BG_SECTION}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLUMN};
    border-radius: 8px; padding: 4px; outline: none;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {BUTTON_HOVER}; color: {TEXT_PRIMARY}; }}
QTabWidget::pane {{ border: 1px solid {BORDER_COLUMN}; border-radius: 10px; top: -1px;
    background: {BG_COLUMN}; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_SECONDARY}; padding: 8px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; border: 1px solid transparent;
}}
QTabBar::tab:selected {{
    color: {TEXT_PRIMARY}; background: {BG_COLUMN}; border: 1px solid {BORDER_COLUMN};
    border-bottom-color: {BG_COLUMN};
}}
QTabBar::tab:hover:!selected {{ color: {TEXT_PRIMARY}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {BG_COLUMN}; }}
QCalendarWidget QToolButton {{
    color: {TEXT_PRIMARY}; background: transparent; border: none; padding: 4px 8px;
    font-weight: 600;
}}
QCalendarWidget QToolButton:hover {{ background: {BUTTON_HOVER}; border-radius: 5px; }}
QCalendarWidget QAbstractItemView {{
    background: {BG_SECTION}; color: {TEXT_PRIMARY}; outline: none;
    selection-background-color: {GREEN_NEON}; selection-color: {ink_on(GREEN_NEON)};
    alternate-background-color: {BG_COLUMN};
}}
QCalendarWidget QAbstractItemView:disabled {{ color: {TEXT_MUTED}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {PILL_BORDER}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""
