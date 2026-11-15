"""
Widgets reliés à REKA : le bouton REKA, les canaux de la console, le micro et
le casque.

Ils montrent ce que montre la console (mêmes canaux, mêmes noms, mêmes
couleurs) et agissent sur les mêmes réglages de Voicemeeter : un Muet posé
ici s'allume dans REKA, et l'inverse.
"""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from core import config
from core.reka_link import RekaSetup
from core.voicemeeter import (GAIN_MAX_DB, GAIN_MIN_DB, STATE_CONNECTED, STATE_MISSING,
                              MixerLevels, MixerParams)
from ui import styles
from ui.widgets.base import (Context, Icon, IconButton, LevelMeter, Pill, Text, format_db,
                             level_color, level_fraction)

CHIP_WIDTH = 40
SILENT = (-100.0, -100.0)


def abbreviate(name: str) -> str:
    """Nom d'un canal en trois caractères : « Microphone » → « MIC »,
    « Autres 2 » → « AU2 », « Jeu vidéo » → « JV »."""
    plain = "".join(c for c in unicodedata.normalize("NFD", name) if not unicodedata.combining(c))
    words = [w for w in plain.replace("-", " ").replace("_", " ").split() if w]
    if not words:
        return "?"
    if len(words) > 1 and words[-1].isdigit():
        return (words[0][:2] + words[-1][-1]).upper()
    if len(words) > 1:
        return "".join(w[0] for w in words[:3]).upper()
    return words[0][:3].upper()


def route_label(label: str) -> str:
    """Nom court d'un envoi de REKA : « Monitor » → « MON », « Mic Out » → « MIC »."""
    plain = "".join(c for c in unicodedata.normalize("NFD", label) if not unicodedata.combining(c))
    return "".join(c for c in plain if c.isalnum())[:3].upper() or "?"


def vm_state_text(state: str, setup: RekaSetup) -> str:
    if state == STATE_CONNECTED:
        return f"{setup.edition.label} connecté"
    if state == STATE_MISSING:
        return "Voicemeeter n'est pas installé"
    return "Voicemeeter est fermé"


def mic_strip(cfg: dict, setup: RekaSetup) -> int:
    """Canal du micro : celui des réglages de la barre, sinon celui que REKA
    synchronise avec Discord (le premier canal par défaut)."""
    try:
        chosen = int(cfg.get("widgets", {}).get("mic", {}).get("strip", -1))
    except (TypeError, ValueError, AttributeError):
        chosen = -1
    index = chosen if chosen >= 0 else setup.mic_strip
    return max(0, min(index, len(setup.strips) - 1))


def step_gain(current: float, steps: float, step_db: float) -> float:
    """Volume après `steps` crans de molette."""
    return max(GAIN_MIN_DB, min(GAIN_MAX_DB, round(current + steps * step_db, 1)))


def wheel_steps(event) -> float:
    """Crans de molette d'un événement (positif = vers le haut)."""
    delta = event.angleDelta().y() or event.angleDelta().x()
    return delta / 120.0


# --------------------------------------------------------------------------- #
# Bouton REKA
# --------------------------------------------------------------------------- #
class RekaWidget(Pill):
    """Logo de REKA et pastille d'état ; un clic affiche (ou lance) la console."""

    key = "reka"
    LOGO_HEIGHT = 20

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._logo = QPixmap(str(config.resource_path("assets/reka_mark.png")))
        self.clicked.connect(self.open_reka)
        ctx.reka.running_changed.connect(self._refresh)
        ctx.vm.state_changed.connect(self._refresh)
        ctx.vm.setup_changed.connect(self._refresh)
        self._refresh()

    def sizeHint(self) -> QSize:  # noqa: N802
        width = self.LOGO_HEIGHT * 2 if not self._logo.isNull() else 44
        return QSize(width + 34, 32)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def status(self) -> str:
        """« ok » (REKA ouverte et Voicemeeter connecté), « partial » ou « off »."""
        running, connected = self._ctx.reka.running, self._ctx.vm.connected
        if running and connected:
            return "ok"
        return "partial" if running or connected else "off"

    def _refresh(self, *_args) -> None:
        reka = ("REKA est ouverte — clic : afficher la console" if self._ctx.reka.running
                else "REKA est fermée — clic : la lancer")
        self.setToolTip(f"{reka}\n{vm_state_text(self._ctx.vm.state, self._ctx.vm.setup)}")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        height = self.LOGO_HEIGHT
        x = 10.0
        if not self._logo.isNull():
            width = height * self._logo.width() / self._logo.height()
            painter.drawPixmap(QRectF(x, (self.height() - height) / 2, width, height),
                               self._logo, QRectF(self._logo.rect()))
        else:
            width = 40.0
            painter.setFont(styles.font(13, QFont.Weight.DemiBold))
            painter.setPen(QColor(styles.TEXT_PRIMARY))
            painter.drawText(QRectF(x, 0, width, self.height()),
                             Qt.AlignmentFlag.AlignCenter, "REKA")
        color = {"ok": styles.STATUS_OK, "partial": styles.STATUS_WARN}.get(
            self.status(), styles.STATUS_OFF)
        center = QPointF(x + width + 11, self.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(styles.color(color, 0.25))
        painter.drawEllipse(center, 6.5, 6.5)
        painter.setBrush(QColor(color))
        painter.drawEllipse(center, 3.5, 3.5)

    def open_reka(self) -> None:
        self._ctx.open_reka()

    def menu_actions(self) -> list:
        vm = self._ctx.vm
        return [("Afficher REKA" if self._ctx.reka.running else "Lancer REKA", self.open_reka),
                ("Mini-console…", lambda: self._ctx.open_mixer(self)),
                ("Redémarrer le moteur audio de Voicemeeter",
                 vm.restart_audio_engine if vm.connected else None)]


# --------------------------------------------------------------------------- #
# Canaux de la console
# --------------------------------------------------------------------------- #
class StripChip(QWidget):
    """Un canal de REKA en miniature : son nom abrégé et son niveau."""

    toggled = Signal(int)            # clic : inverser le Muet
    wheeled = Signal(int, float)     # molette : (canal, crans)

    def __init__(self, index: int, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.name = name
        self.gain = 0.0
        self.muted = False
        self.connected = False
        self.levels = SILENT
        self._hover = False
        self.setFixedWidth(CHIP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_tooltip()

    def set_state(self, gain: float, muted: bool, connected: bool) -> None:
        if (gain, muted, connected) != (self.gain, self.muted, self.connected):
            self.gain, self.muted, self.connected = gain, muted, connected
            self._update_tooltip()
            self.update()

    def set_levels(self, levels: tuple[float, float]) -> None:
        if levels != self.levels:
            self.levels = levels
            self.update()

    def _update_tooltip(self) -> None:
        if not self.connected:
            self.setToolTip(f"{self.name}\nVoicemeeter est fermé")
            return
        state = "muet" if self.muted else format_db(self.gain)
        self.setToolTip(f"{self.name} — {state}\n"
                        "Clic : muet · Molette : volume · Clic droit : mini-console")

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.toggled.emit(self.index)
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.wheeled.emit(self.index, wheel_steps(event))
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 4, -1, -4)
        active = self.connected and not self.muted
        if self.connected and self.muted:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(styles.color(styles.accent("mute", self.index), 0.9))
            painter.drawRoundedRect(rect, 6, 6)
        elif self._hover and self.connected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(styles.BUTTON_HOVER))
            painter.drawRoundedRect(rect, 6, 6)

        if self.connected and self.muted:
            ink = styles.WHITE
        elif active:
            ink = styles.accent("name", self.index)
        else:
            ink = styles.TEXT_MUTED
        painter.setFont(styles.font(10, QFont.Weight.DemiBold))
        painter.setPen(QColor(ink))
        painter.drawText(QRectF(rect.left(), rect.top() + 1, rect.width(), 13),
                         Qt.AlignmentFlag.AlignCenter, abbreviate(self.name))

        # VU-mètre : deux traits (gauche, droite) sous le nom
        base = styles.accent("vu", self.index)
        track = styles.color(styles.WHITE, 0.25) if self.connected and self.muted \
            else QColor(styles.GREEN_SCALE if self.connected else styles.BORDER_COLUMN)
        left, width = rect.left() + 5, rect.width() - 10
        painter.setPen(Qt.PenStyle.NoPen)
        for n, db in enumerate(self.levels):
            y = rect.bottom() - 8 + n * 3
            painter.fillRect(QRectF(left, y, width, 2), track)
            if active:
                fraction = level_fraction(db)
                if fraction > 0:
                    painter.fillRect(QRectF(left, y, width * fraction, 2),
                                     QColor(level_color(db, base)))


class StripsWidget(Pill):
    """Les canaux de REKA : muet d'un clic, volume à la molette, et la
    mini-console complète derrière le bouton à curseurs."""

    key = "strips"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._chips: list[StripChip] = []
        self.row.setContentsMargins(4, 0, 6, 0)
        self.row.setSpacing(1)
        self.mixer_button = IconButton("sliders", "Mini-console : faders, muets et routing",
                                       role="TEXT_SECONDARY")
        self.mixer_button.clicked.connect(lambda: ctx.open_mixer(self))
        self.row.addWidget(self.mixer_button)
        ctx.vm.setup_changed.connect(self._rebuild)
        ctx.vm.params_changed.connect(self._on_params)
        ctx.vm.levels_changed.connect(self._on_levels)
        ctx.vm.state_changed.connect(self._on_state)
        self._rebuild(ctx.vm.setup)

    @property
    def chips(self) -> list[StripChip]:
        return list(self._chips)

    def _rebuild(self, setup: RekaSetup) -> None:
        for chip in self._chips:
            self.row.removeWidget(chip)
            chip.deleteLater()
        self._chips = []
        for index in range(len(setup.strips)):
            chip = StripChip(index, setup.name(index))
            chip.toggled.connect(self._toggle_mute)
            chip.wheeled.connect(self._nudge)
            self.row.addWidget(chip)
            self._chips.append(chip)
        self._on_params(self._ctx.vm.params)
        if self._ctx.vm.levels is not None:
            self._on_levels(self._ctx.vm.levels)
        self.updateGeometry()

    def _on_params(self, params: MixerParams | None) -> None:
        connected = self._ctx.vm.connected and params is not None
        for chip in self._chips:
            if connected and chip.index < len(params.strips):
                strip = params.strips[chip.index]
                chip.set_state(strip.gain, strip.mute, True)
            else:
                chip.set_state(chip.gain, chip.muted, False)
                chip.set_levels(SILENT)

    def _on_levels(self, levels: MixerLevels) -> None:
        for chip, value in zip(self._chips, levels.strips):
            chip.set_levels(value)

    def _on_state(self, _state: str) -> None:
        self._on_params(self._ctx.vm.params)

    def _toggle_mute(self, index: int) -> None:
        params = self._ctx.vm.params
        if params is not None and index < len(params.strips):
            self._ctx.vm.set_mute(index, not params.strips[index].mute)

    def _nudge(self, index: int, steps: float) -> None:
        params = self._ctx.vm.params
        if params is not None and index < len(params.strips):
            step = float(self._ctx.widget_cfg("strips").get("gain_step_db", 1.0) or 1.0)
            self._ctx.vm.set_gain(index, step_gain(params.strips[index].gain, steps, step))

    def menu_actions(self) -> list:
        return [("Mini-console…", lambda: self._ctx.open_mixer(self))]


# --------------------------------------------------------------------------- #
# Micro
# --------------------------------------------------------------------------- #
class MicWidget(Pill):
    """Le micro : un clic le coupe (dans REKA aussi, donc dans Discord si la
    synchro de REKA est activée) ; la barre de niveau montre qu'il capte."""

    key = "mic"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._muted = False
        self._connected = False
        self.icon = Icon("mic", role="TEXT_PRIMARY", size=18)
        self.meter = LevelMeter(horizontal=False, length=18, thickness=2)
        self.row.addWidget(self.icon)
        self.row.addWidget(self.meter)
        self.clicked.connect(self.toggle)
        ctx.vm.setup_changed.connect(self._refresh)
        ctx.vm.params_changed.connect(self._refresh)
        ctx.vm.state_changed.connect(self._refresh)
        ctx.vm.levels_changed.connect(self._on_levels)
        self._refresh()

    def strip(self) -> int:
        return mic_strip(self._ctx.cfg, self._ctx.vm.setup)

    @property
    def muted(self) -> bool:
        return self._muted

    def _refresh(self, *_args) -> None:
        params = self._ctx.vm.params
        index = self.strip()
        self._connected = self._ctx.vm.connected and params is not None \
            and index < len(params.strips)
        self._muted = bool(self._connected and params.strips[index].mute)
        self.meter.scope = index
        self.meter.dimmed = not self._connected or self._muted
        self.icon.set_icon("mic_off" if self._muted else "mic")
        self.icon.set_color(styles.WHITE if self._muted else
                            (None if self._connected else styles.TEXT_MUTED))
        self.set_tint(styles.accent("mute", index) if self._muted else None)
        name = self._ctx.vm.setup.name(index)
        if not self._connected:
            self.setToolTip(f"{name}\nVoicemeeter est fermé")
        else:
            self.setToolTip(f"{name} — {'coupé' if self._muted else 'ouvert'}\n"
                            "Clic : couper / rouvrir le micro · Molette : volume")
        self.meter.update()

    refresh_theme = _refresh

    def _on_levels(self, levels: MixerLevels) -> None:
        index = self.strip()
        if index < len(levels.strips):
            self.meter.set_levels(*levels.strips[index])

    def toggle(self) -> None:
        if self._connected:
            self._ctx.vm.set_mute(self.strip(), not self._muted)

    def wheelEvent(self, event) -> None:  # noqa: N802
        params = self._ctx.vm.params
        if self._connected and params is not None:
            index = self.strip()
            self._ctx.vm.set_gain(index, step_gain(params.strips[index].gain,
                                                   wheel_steps(event), 1.0))
        event.accept()

    def menu_actions(self) -> list:
        return [("Rouvrir le micro" if self._muted else "Couper le micro",
                 self.toggle if self._connected else None),
                ("Choisir le canal du micro…", lambda: self._ctx.open_settings("reka"))]


# --------------------------------------------------------------------------- #
# Casque
# --------------------------------------------------------------------------- #
class HeadphoneWidget(Pill):
    """Volume du casque (le knob Casque du Master de REKA) et niveau de sortie."""

    key = "headphone"

    def __init__(self, ctx: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent, clickable=True)
        self._ctx = ctx
        self._gain = 0.0
        self._muted = False
        self._connected = False
        self.icon = Icon("headphones", role="TEXT_PRIMARY", size=17)
        self.value = Text("", size=12, weight=QFont.Weight.Medium, min_chars=7)
        self.meter = LevelMeter(horizontal=False, length=18, thickness=2,
                                element="vu", scope=styles.MASTER_SCOPE)
        self.row.addWidget(self.icon)
        self.row.addWidget(self.value)
        self.row.addWidget(self.meter)
        self.clicked.connect(self.toggle_mute)
        ctx.vm.params_changed.connect(self._refresh)
        ctx.vm.state_changed.connect(self._refresh)
        ctx.vm.setup_changed.connect(self._refresh)
        ctx.vm.levels_changed.connect(self._on_levels)
        self._refresh()

    @property
    def muted(self) -> bool:
        return self._muted

    def _refresh(self, *_args) -> None:
        params = self._ctx.vm.params
        self._connected = self._ctx.vm.connected and params is not None
        if self._connected:
            self._gain, self._muted = params.headphone_gain, params.headphone_mute
        else:
            self._muted = False
        self.meter.dimmed = not self._connected or self._muted
        self.meter.update()
        bus = self._ctx.vm.setup.headphone_bus
        if not self._connected:
            self.value.set_text("—")
            self.value.set_color(styles.TEXT_MUTED)
            self.icon.set_color(styles.TEXT_MUTED)
            self.set_tint(None)
            self.setToolTip(f"Casque ({bus})\nVoicemeeter est fermé")
            return
        self.value.set_text("Muet" if self._muted else format_db(self._gain))
        self.value.set_color(styles.WHITE if self._muted else None)
        self.icon.set_color(styles.WHITE if self._muted
                            else styles.accent("headphone", styles.MASTER_SCOPE))
        self.set_tint(styles.accent("mute") if self._muted else None)
        self.setToolTip(f"Casque ({bus}) — {'muet' if self._muted else format_db(self._gain)}\n"
                        "Molette : volume · Clic : muet · Clic du milieu : 0 dB")

    refresh_theme = _refresh

    def _on_levels(self, levels: MixerLevels) -> None:
        self.meter.set_levels(*levels.master)

    def toggle_mute(self) -> None:
        if self._connected:
            self._ctx.vm.set_headphone_mute(not self._muted)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._connected:
            self._ctx.vm.set_headphone_gain(step_gain(self._gain, wheel_steps(event), 1.0))
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._connected:
            self._ctx.vm.set_headphone_gain(0.0)
            event.accept()
            return
        super().mousePressEvent(event)

    def menu_actions(self) -> list:
        return [("Rétablir le son du casque" if self._muted else "Couper le casque",
                 self.toggle_mute if self._connected else None),
                ("Volume à 0 dB",
                 (lambda: self._ctx.vm.set_headphone_gain(0.0)) if self._connected else None)]
