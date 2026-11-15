"""
Mini-console : les canaux de REKA sans ouvrir REKA.

Une colonne par canal (fader, VU-mètre, Muet, envois Monitor / Mic Out /
Discord / Obs) et une colonne Casque. Tout passe par Voicemeeter : la console
REKA, si elle est ouverte, suit en direct.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from core.reka_link import RekaSetup
from core.voicemeeter import GAIN_MAX_DB, GAIN_MIN_DB, MixerLevels, MixerParams
from ui import styles
from ui.popup import Popup
from ui.widgets.base import format_db, level_color
from ui.widgets.reka import route_label, vm_state_text, wheel_steps

FADER_HEIGHT = 168
# Échelle des faders : (dB, position de 0 en haut à 1 en bas), comme la console
SCALE = ((12.0, 0.0), (6.0, 0.075), (0.0, 0.15), (-6.0, 0.28), (-12.0, 0.39),
         (-24.0, 0.56), (-48.0, 0.80), (-60.0, 1.0))
SCALE_MARKS = (12, 0, -12, -24, -48)


def _pen(color: str, width: float) -> QPen:
    return QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)


def db_to_position(db: float) -> float:
    """Position d'un volume sur l'échelle (0 = tout en haut, 1 = tout en bas)."""
    db = max(GAIN_MIN_DB, min(GAIN_MAX_DB, float(db)))
    for (high_db, high_pos), (low_db, low_pos) in zip(SCALE, SCALE[1:]):
        if db >= low_db:
            return high_pos + (high_db - db) / (high_db - low_db) * (low_pos - high_pos)
    return 1.0


def position_to_db(position: float) -> float:
    position = max(0.0, min(1.0, float(position)))
    for (high_db, high_pos), (low_db, low_pos) in zip(SCALE, SCALE[1:]):
        if position <= low_pos:
            return round(high_db - (position - high_pos) / (low_pos - high_pos)
                         * (high_db - low_db), 1)
    return GAIN_MIN_DB


class Fader(QWidget):
    """Fader vertical : glisser (Maj = précis), molette, double-clic = 0 dB."""

    moved = Signal(float)        # volume choisi par l'utilisateur (dB)
    CAP_W, CAP_H = 24, 14
    PAD = 9                      # marge haute et basse de la piste

    def __init__(self, element: str = "fader", scope: int | str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.element, self.scope = element, scope
        self._value = 0.0
        self._drag: tuple[float, float] | None = None    # (y de départ, position de départ)
        self.setFixedSize(46, FADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Glisser (Maj : précis) · molette · double-clic : 0 dB")

    @property
    def value(self) -> float:
        return self._value

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    def set_value(self, db: float) -> None:
        """Valeur venue de Voicemeeter ; ignorée pendant que l'utilisateur glisse."""
        if self._drag is None and db != self._value:
            self._value = db
            self.update()

    def _track(self) -> tuple[float, float]:
        return float(self.PAD), float(self.height() - self.PAD)

    def _y(self, db: float) -> float:
        top, bottom = self._track()
        return top + db_to_position(db) * (bottom - top)

    def _choose(self, db: float) -> None:
        db = max(GAIN_MIN_DB, min(GAIN_MAX_DB, round(db, 1)))
        if db != self._value:
            self._value = db
            self.update()
            self.moved.emit(db)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            event.ignore()
            return
        top, bottom = self._track()
        y = event.position().y()
        if abs(y - self._y(self._value)) > self.CAP_H:      # clic sur la piste : on y va
            self._choose(position_to_db((y - top) / (bottom - top)))
        self._drag = (y, db_to_position(self._value))
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        top, bottom = self._track()
        start_y, start_position = self._drag
        fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        delta = (event.position().y() - start_y) / (bottom - top) * (0.2 if fine else 1.0)
        self._choose(position_to_db(start_position + delta))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._drag = None
        self._choose(0.0)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled():
            fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._choose(self._value + wheel_steps(event) * (0.1 if fine else 1.0))
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top, bottom = self._track()
        x = self.width() - self.CAP_W / 2 - 2
        enabled = self.isEnabled()
        accent = styles.accent(self.element, self.scope) if enabled else styles.TEXT_MUTED

        painter.setFont(styles.font(9))
        metrics = QFontMetrics(painter.font())
        for mark in SCALE_MARKS:
            y = self._y(mark)
            painter.setPen(QColor(styles.TEXT_MUTED))
            label = f"+{mark}" if mark > 0 else str(mark)
            painter.drawText(QRectF(0, y - metrics.height() / 2, x - self.CAP_W / 2 - 3,
                                    metrics.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        y = self._y(self._value)
        painter.setPen(_pen(styles.GREEN_SCALE, 3))
        painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        painter.setPen(_pen(accent, 3))
        painter.drawLine(QPointF(x, y), QPointF(x, bottom))

        cap = QRectF(x - self.CAP_W / 2, y - self.CAP_H / 2, self.CAP_W, self.CAP_H)
        gradient = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        gradient.setColorAt(0.0, QColor("#ffffff" if enabled else styles.KNOB_CAP_TOP))
        gradient.setColorAt(1.0, QColor("#d7dde6" if enabled else styles.KNOB_CAP_BOTTOM))
        painter.setPen(QColor(styles.BG_DEEP))
        painter.setBrush(gradient)
        painter.drawRoundedRect(cap, 4, 4)
        painter.setPen(_pen(accent, 2))
        painter.drawLine(QPointF(cap.left() + 6, y), QPointF(cap.right() - 6, y))


class ScaleMeter(QWidget):
    """VU-mètre vertical à la même échelle que les faders."""

    def __init__(self, element: str = "vu", scope: int | str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.element, self.scope = element, scope
        self._levels = (-100.0, -100.0)
        self.setFixedSize(11, FADER_HEIGHT)

    def set_levels(self, left: float, right: float) -> None:
        if (left, right) != self._levels:
            self._levels = (left, right)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        top, bottom = float(Fader.PAD), float(self.height() - Fader.PAD)
        base = styles.accent(self.element, self.scope)
        for n, db in enumerate(self._levels):
            x = n * 6
            painter.fillRect(QRectF(x, top, 5, bottom - top), QColor(styles.BG_DEEP))
            if not self.isEnabled() or db <= GAIN_MIN_DB:
                continue
            # Trois zones empilées : accent, jaune au-dessus de -9 dB, rouge au-dessus de 0
            level_y = top + db_to_position(db) * (bottom - top)
            for zone_db, color in ((GAIN_MIN_DB, base), (-9.0, level_color(-9.0, base)),
                                   (0.0, level_color(0.0, base))):
                if db <= zone_db:
                    break
                zone_y = top + db_to_position(zone_db) * (bottom - top)
                painter.fillRect(QRectF(x, level_y, 5, zone_y - level_y), QColor(color))


class _Column(QFrame):
    """Colonne d'un canal ou du casque : nom, volume, fader + VU, Muet."""

    WIDTH = 92

    def __init__(self, name: str, element: str, scope: int | str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("column")
        self.setFixedWidth(self.WIDTH)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(8, 10, 8, 10)
        self.layout_.setSpacing(7)
        self.name = QLabel(name)
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setFont(styles.font(12, QFont.Weight.DemiBold))
        self.name.setToolTip(name)
        self._name_text = name
        self.value = QLabel("")
        self.value.setObjectName("secondary")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fader = Fader(element, scope)
        self.meter = ScaleMeter("vu", scope)
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addStretch(1)
        row.addWidget(self.fader)
        row.addWidget(self.meter)
        row.addStretch(1)
        self.mute = QPushButton("Muet")
        self.mute.setObjectName("muteButton")
        self.mute.setCheckable(True)
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.layout_.addWidget(self.name)
        self.layout_.addWidget(self.value)
        self.layout_.addLayout(row)
        self.layout_.addWidget(self.mute)
        self.fader.moved.connect(lambda db: self.value.setText(format_db(db)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        metrics = QFontMetrics(self.name.font())
        self.name.setText(metrics.elidedText(self._name_text, Qt.TextElideMode.ElideRight,
                                             self.WIDTH - 18))

    def show_state(self, gain: float, muted: bool, connected: bool) -> None:
        self.setEnabled(connected)
        self.fader.set_value(gain)
        if not self.fader.dragging:
            self.value.setText(format_db(gain) if connected else "—")
        self.mute.setChecked(connected and muted)
        self.fader.update()
        self.meter.update()


class MixerPopup(Popup):
    """La mini-console, ouverte contre la barre."""

    def __init__(self, vm, reka, open_reka=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._reka = reka
        self._open_reka_callback = open_reka or reka.show_or_launch
        self.columns: list[_Column] = []
        self.routes: list[list[QPushButton]] = []
        self.master: _Column | None = None

        header = QHBoxLayout()
        title = QLabel("Mini-console")
        title.setObjectName("title")
        self.state = QLabel("")
        self.state.setObjectName("secondary")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.state)
        self.body.addLayout(header)

        self._strips = QHBoxLayout()
        self._strips.setSpacing(8)
        self.body.addLayout(self._strips)

        footer = QHBoxLayout()
        self.open_reka = QPushButton("Ouvrir REKA")
        self.open_reka.setObjectName("primary")
        self.open_reka.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart = QPushButton("Redémarrer le moteur audio")
        self.restart.setToolTip("Relance le moteur audio de Voicemeeter : utile quand le son "
                                "craque ou qu'un périphérique vient d'être rebranché.")
        self.restart.setCursor(Qt.CursorShape.PointingHandCursor)
        hint = QLabel("Les réglages sont ceux de REKA : elle suit en direct.")
        hint.setObjectName("muted")
        footer.addWidget(hint)
        footer.addStretch(1)
        footer.addWidget(self.restart)
        footer.addWidget(self.open_reka)
        self.body.addLayout(footer)

        self.open_reka.clicked.connect(self._open_reka)
        self.restart.clicked.connect(self._vm.restart_audio_engine)
        vm.setup_changed.connect(self._rebuild)
        vm.params_changed.connect(self._on_params)
        vm.levels_changed.connect(self._on_levels)
        vm.state_changed.connect(self._on_state)
        reka.running_changed.connect(self._on_state)
        self._rebuild(vm.setup)

    def _rebuild(self, setup: RekaSetup) -> None:
        while self._strips.count():
            item = self._strips.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.columns, self.routes = [], []
        for index in range(len(setup.strips)):
            column = _Column(setup.name(index), "fader", index)
            column.name.setStyleSheet(f"color: {styles.accent('name', index)};")
            column.fader.moved.connect(lambda db, i=index: self._vm.set_gain(i, db))
            column.mute.clicked.connect(lambda checked, i=index: self._vm.set_mute(i, checked))
            buttons = []
            if setup.routes:
                grid = QGridLayout()
                grid.setSpacing(4)
                for n, (label, bus) in enumerate(setup.routes):
                    button = QPushButton(route_label(label))
                    button.setObjectName("routeButton")
                    button.setCheckable(True)
                    button.setCursor(Qt.CursorShape.PointingHandCursor)
                    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    button.setToolTip(f"Envoyer {setup.name(index)} vers {label} ({bus})")
                    button.clicked.connect(
                        lambda checked, i=index, r=n: self._vm.set_route(i, r, checked))
                    grid.addWidget(button, n // 2, n % 2)
                    buttons.append(button)
                column.layout_.addLayout(grid)
            self.routes.append(buttons)
            self.columns.append(column)
            self._strips.addWidget(column)
        master = _Column("Casque", "headphone", styles.MASTER_SCOPE)
        master.fader.moved.connect(self._vm.set_headphone_gain)
        master.mute.clicked.connect(self._vm.set_headphone_mute)
        master.layout_.addStretch(1)
        bus = QLabel(setup.headphone_bus)
        bus.setObjectName("muted")
        bus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        master.layout_.addWidget(bus)
        self.master = master
        self._strips.addWidget(master)
        self._on_state()

    def _on_state(self, *_args) -> None:
        self.state.setText(vm_state_text(self._vm.state, self._vm.setup))
        self.restart.setEnabled(self._vm.connected)
        self.open_reka.setText("Afficher REKA" if self._reka.running else "Lancer REKA")
        self._on_params(self._vm.params)
        if self._vm.levels is not None:
            self._on_levels(self._vm.levels)

    def _on_params(self, params: MixerParams | None) -> None:
        connected = self._vm.connected and params is not None
        for index, column in enumerate(self.columns):
            if connected and index < len(params.strips):
                strip = params.strips[index]
                column.show_state(strip.gain, strip.mute, True)
                for button, enabled in zip(self.routes[index], strip.routes):
                    button.setChecked(enabled)
            else:
                column.show_state(column.fader.value, False, False)
        if self.master is not None:
            if connected:
                self.master.show_state(params.headphone_gain, params.headphone_mute, True)
            else:
                self.master.show_state(self.master.fader.value, False, False)

    def _on_levels(self, levels: MixerLevels) -> None:
        for column, value in zip(self.columns, levels.strips):
            column.meter.set_levels(*value)
        if self.master is not None:
            self.master.meter.set_levels(*levels.master)

    def _open_reka(self) -> None:
        self.close()
        self._open_reka_callback()
