"""Custom JARVIS HUD chrome — pulse ring, frameless title bar, holo panels."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# —— Palette (luxury Stark: cool cyan metal + sparingly gold/amber) ——
C_BG = "#04060a"
C_PANEL = "#070b12"
C_PANEL_INSET = "#05080e"
C_BORDER = "#1a3048"
C_BORDER_BRIGHT = "#2e5578"
C_CYAN = "#3de0ff"
C_CYAN_DIM = "#00d4ff"
C_CYAN_SOFT = "#1a8aaa"
C_CYAN_GLOW = "#7af0ff"
C_GOLD = "#d4a84b"
C_GOLD_SOFT = "#a87a30"
C_AMBER = "#ffb84d"
C_TEXT = "#d8e6f0"
C_MUTED = "#6a8498"
C_USER = "#3de0ff"
C_ASSIST = "#e8f0f8"
C_DANGER = "#ff5a5a"
C_WARN = "#ffb84d"
C_SPEAK = "#c8e8f4"  # soft white/cyan — never traffic-light green

MONO = '"Menlo", "SF Mono", "Consolas", "Courier New", monospace'

HUD_STYLESHEET = f"""
QWidget#hudRoot {{
    background: transparent;
}}
QWidget#titleBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(12, 18, 28, 240), stop:1 rgba(6, 10, 16, 220));
    border: none;
    border-bottom: 1px solid rgba(46, 85, 120, 120);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QLabel#wordmark {{
    color: {C_CYAN};
    font-family: {MONO};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 10px;
}}
QLabel#titleMeta {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 2.5px;
}}
QPushButton#winClose, QPushButton#winMin {{
    background: transparent;
    border: none;
    border-radius: 6px;
    min-width: 12px;
    max-width: 12px;
    min-height: 12px;
    max-height: 12px;
    padding: 0;
}}
QPushButton#winClose {{
    background: #ff5f57;
}}
QPushButton#winClose:hover {{
    background: #ff7a73;
}}
QPushButton#winMin {{
    background: #febc2e;
}}
QPushButton#winMin:hover {{
    background: #ffd060;
}}
QWidget#statusStripRoot {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(6, 12, 20, 220), stop:0.5 rgba(8, 14, 22, 200),
        stop:1 rgba(6, 12, 20, 220));
    border: 1px solid rgba(46, 85, 120, 140);
    border-left: 2px solid {C_CYAN_SOFT};
    border-radius: 10px;
}}
QLabel#statusStrip {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 1.8px;
    padding: 4px 8px 4px 4px;
    background: transparent;
    border: none;
}}
QLabel#telemetryBit {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1.2px;
}}
QLabel#ringCaption {{
    color: {C_CYAN_SOFT};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 4px;
    font-weight: 600;
}}
QLabel#fieldLabel {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 2.5px;
}}
QLabel#awaitWatermark {{
    color: rgba(61, 224, 255, 42);
    font-family: {MONO};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 5px;
    background: transparent;
}}
QTextEdit#chatLog {{
    background: transparent;
    color: {C_ASSIST};
    border: none;
    padding: 12px 16px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 12px;
}}
QLineEdit#msgInput {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0a1018, stop:1 #05080e);
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
    padding: 11px 16px 11px 14px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 13px;
}}
QLineEdit#msgInput:focus {{
    border: 1px solid {C_CYAN_DIM};
}}
QLineEdit#msgInput:disabled {{
    color: #445566;
    border-color: #152030;
}}
QLineEdit#modelInput {{
    background: #05080e;
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    padding: 5px 10px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 10px;
    max-width: 160px;
}}
QLineEdit#modelInput:focus {{
    border: 1px solid {C_CYAN_DIM};
}}
QPushButton#sendBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(61, 224, 255, 28), stop:1 rgba(61, 224, 255, 10));
    color: {C_CYAN};
    font-weight: 700;
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 3px;
    padding: 10px 22px;
    border: 1px solid {C_CYAN};
    border-radius: 16px;
    min-width: 110px;
}}
QPushButton#sendBtn:hover {{
    background: rgba(61, 224, 255, 55);
    color: #a8f4ff;
    border-color: #5aebff;
}}
QPushButton#sendBtn:pressed {{
    background: rgba(61, 224, 255, 80);
}}
QPushButton#sendBtn:disabled {{
    color: #3a5060;
    border-color: #1a2838;
    background: transparent;
}}
QPushButton#micBtn {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
        stop:0 #0e1a28, stop:1 #060c14);
    color: {C_CYAN};
    font-family: {MONO};
    font-size: 15px;
    font-weight: 700;
    border: 2px solid {C_CYAN_DIM};
    border-radius: 24px;
    min-width: 48px;
    max-width: 48px;
    min-height: 48px;
    max-height: 48px;
    padding: 0;
}}
QPushButton#micBtn:hover {{
    background: #122033;
    border-color: {C_CYAN};
    color: {C_CYAN_GLOW};
}}
QPushButton#micBtn:disabled {{
    background: #0a1018;
    color: #445566;
    border-color: #1a2430;
}}
QPushButton#micBtn[recording="true"] {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.85,
        stop:0 #2a1c08, stop:1 #0c1014);
    color: {C_AMBER};
    border: 2px solid {C_AMBER};
}}
QCheckBox#speakBox {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1.5px;
    spacing: 6px;
}}
QCheckBox#speakBox::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    background: #05080e;
}}
QCheckBox#speakBox::indicator:checked {{
    background: {C_CYAN_DIM};
    border-color: {C_CYAN};
}}
QCheckBox#speakBox::indicator:disabled {{
    border-color: #1a2430;
    background: #0a1018;
}}
QLabel#chevron {{
    color: {C_CYAN};
    font-family: {MONO};
    font-size: 18px;
    font-weight: 300;
    padding: 0 2px 0 8px;
}}
QLabel#footLabel {{
    color: #3a5060;
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 1.2px;
}}
QMessageBox {{
    background: {C_BG};
    color: {C_TEXT};
}}
QMessageBox QLabel {{
    color: {C_TEXT};
}}
QMessageBox QPushButton {{
    background: #0c1522;
    color: {C_CYAN};
    border: 1px solid {C_CYAN_DIM};
    border-radius: 10px;
    padding: 6px 16px;
    font-family: {MONO};
}}
"""


def _draw_double_bracket(
    painter: QPainter,
    x: int,
    y: int,
    arm: int,
    *,
    h_dir: int,
    v_dir: int,
    color: QColor,
    thick: float = 1.5,
    gap: int = 3,
) -> None:
    """Double-L corner bracket with a rivet dot at the joint."""
    painter.setPen(QPen(color, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
    # Outer L
    painter.drawLine(x, y, x + h_dir * arm, y)
    painter.drawLine(x, y, x, y + v_dir * arm)
    # Inner L
    ix, iy = x + h_dir * gap, y + v_dir * gap
    inner_arm = arm - gap - 2
    painter.setPen(QPen(color, 1.0))
    painter.drawLine(ix, iy, ix + h_dir * inner_arm, iy)
    painter.drawLine(ix, iy, ix, iy + v_dir * inner_arm)
    # Rivet
    rivet = QColor(color)
    rivet.setAlpha(min(255, color.alpha() + 40))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(rivet)
    painter.drawEllipse(QPointF(x + h_dir * 2.5, y + v_dir * 2.5), 1.6, 1.6)


class HudRoot(QWidget):
    """Root canvas: delicate hex/grid + constellation marks + double-L brackets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Deep void with subtle vertical vignette
        painter.fillRect(0, 0, w, h, QColor(C_BG))
        vig = QLinearGradient(0, 0, 0, h)
        vig.setColorAt(0.0, QColor(8, 14, 24, 55))
        vig.setColorAt(0.5, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(4, 8, 14, 70))
        painter.fillRect(0, 0, w, h, vig)

        # Delicate grid
        grid = QColor(61, 224, 255, 10)
        painter.setPen(QPen(grid, 1.0))
        step = 32
        for x in range(0, w + 1, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h + 1, step):
            painter.drawLine(0, y, w, y)

        # Sparse hex-ish diagonals
        diag = QColor(0, 160, 200, 7)
        painter.setPen(QPen(diag, 1.0))
        for i in range(-h, w + h, step * 3):
            painter.drawLine(i, 0, i + h, h)

        # Sparse constellation ticks
        ticks = QColor(61, 224, 255, 45)
        gold_tick = QColor(212, 168, 75, 50)
        painter.setPen(QPen(ticks, 1.0))
        for i, (fx, fy, gold) in enumerate(
            (
                (0.18, 0.22, False),
                (0.82, 0.18, True),
                (0.12, 0.72, False),
                (0.88, 0.78, False),
                (0.55, 0.12, True),
                (0.40, 0.88, False),
            )
        ):
            px, py = int(w * fx), int(h * fy)
            painter.setPen(QPen(gold_tick if gold else ticks, 1.0))
            painter.drawLine(px - 5, py, px + 5, py)
            painter.drawLine(px, py - 5, px, py + 5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gold_tick if gold else ticks)
            painter.drawEllipse(QPointF(px, py), 1.2, 1.2)

        # Double-L corner brackets + rivets
        margin = 12
        arm = 32
        cyan = QColor(61, 224, 255, 170)
        _draw_double_bracket(painter, margin, margin, arm, h_dir=1, v_dir=1, color=cyan)
        _draw_double_bracket(
            painter, w - margin, margin, arm, h_dir=-1, v_dir=1, color=cyan
        )
        _draw_double_bracket(
            painter, margin, h - margin, arm, h_dir=1, v_dir=-1, color=cyan
        )
        _draw_double_bracket(
            painter, w - margin, h - margin, arm, h_dir=-1, v_dir=-1, color=cyan
        )

        # Mid-edge ranging marks
        tick = QColor(61, 224, 255, 80)
        gold = QColor(212, 168, 75, 90)
        painter.setPen(QPen(tick, 1.0))
        mid_y, mid_x = h // 2, w // 2
        for dy in (-14, -6, 0, 6, 14):
            painter.drawLine(margin, mid_y + dy, margin + (6 if dy == 0 else 3), mid_y + dy)
            painter.drawLine(
                w - margin, mid_y + dy, w - margin - (6 if dy == 0 else 3), mid_y + dy
            )
        painter.setPen(QPen(gold, 1.0))
        painter.drawLine(mid_x - 10, margin, mid_x + 10, margin)
        painter.drawLine(mid_x - 10, h - margin, mid_x + 10, h - margin)

        # Soft rounded outer frame accent (less boxy chrome)
        painter.setPen(QPen(QColor(46, 85, 120, 120), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(4.5, 4.5, w - 9.0, h - 9.0), 16.0, 16.0)
        # Faint inner glow line
        painter.setPen(QPen(QColor(61, 224, 255, 28), 1.0))
        painter.drawRoundedRect(QRectF(7.5, 7.5, w - 15.0, h - 15.0), 13.0, 13.0)

        painter.end()


class StatusStrip(QWidget):
    """Status text with animated live pip on the left."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusStripRoot")
        self.setFixedHeight(28)
        self._phase = 0.0
        self._active = True

        row = QHBoxLayout(self)
        self._pip = _LivePip()
        row.setContentsMargins(10, 0, 8, 0)
        row.setSpacing(8)
        row.addWidget(self._pip)
        self._label = QLabel("SYS // STANDBY")
        self._label.setObjectName("statusStrip")
        row.addWidget(self._label, stretch=1)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt naming
        self._label.setText(text)
        lower = text.lower()
        hot = any(
            k in lower
            for k in ("listening", "thinking", "synthesiz", "speaking", "transcrib", "process")
        )
        self._pip.set_hot(hot)

    def text(self) -> str:
        return self._label.text()


class _LivePip(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._hot = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_hot(self, hot: bool) -> None:
        self._hot = hot
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + (0.18 if self._hot else 0.05)) % (math.pi * 2)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        if self._hot:
            c = QColor(61, 224, 255, int(160 + 95 * pulse))
            glow = QColor(61, 224, 255, int(40 * pulse))
        else:
            c = QColor(26, 140, 170, int(90 + 40 * pulse))
            glow = QColor(26, 140, 170, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(5, 5), 4.5, 4.5)
        painter.setBrush(c)
        painter.drawEllipse(QPointF(5, 5), 2.4, 2.4)
        painter.end()


class TitleBar(QWidget):
    """Frameless drag bar with macOS-style traffic lights + JARVIS wordmark."""

    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(38)
        self._drag_pos: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)

        self._btn_close = QPushButton()
        self._btn_close.setObjectName("winClose")
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setToolTip("Close")
        self._btn_close.clicked.connect(self.close_requested.emit)
        row.addWidget(self._btn_close)

        self._btn_min = QPushButton()
        self._btn_min.setObjectName("winMin")
        self._btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_min.setToolTip("Minimize")
        self._btn_min.clicked.connect(self.minimize_requested.emit)
        row.addWidget(self._btn_min)

        row.addSpacing(14)

        mark = QLabel("JARVIS")
        mark.setObjectName("wordmark")
        row.addWidget(mark)

        meta = QLabel("HUD  //  LOCAL  //  v3")
        meta.setObjectName("titleMeta")
        row.addWidget(meta)

        row.addStretch(1)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            delta = event.globalPosition().toPoint() - self._drag_pos
            win.move(win.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        event.accept()


class PulseRing(QWidget):
    """Cinematic multi-layer radar — idle / listening / thinking / speaking.

    Palette: idle=cool dim cyan; thinking=bright cyan; listening=amber;
    speaking=soft white/cyan (never traffic-light green). Gold accents sparingly.
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._state = self.IDLE
        self._phase = 0.0
        self._dash_phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _tick(self) -> None:
        speed = {
            self.IDLE: 0.028,
            self.LISTENING: 0.10,
            self.THINKING: 0.20,
            self.SPEAKING: 0.13,
        }.get(self._state, 0.028)
        dash_speed = {
            self.IDLE: 0.6,
            self.LISTENING: 2.2,
            self.THINKING: 4.0,
            self.SPEAKING: 2.8,
        }.get(self._state, 0.6)
        self._phase = (self._phase + speed) % (math.pi * 2)
        self._dash_phase = (self._dash_phase + dash_speed) % 360.0
        self.update()

    def _palette(self) -> tuple[QColor, QColor, QColor, float]:
        """primary, secondary, accent(gold), intensity."""
        if self._state == self.LISTENING:
            return (
                QColor(255, 184, 77),
                QColor(255, 160, 50, 200),
                QColor(212, 168, 75, 160),
                1.0,
            )
        if self._state == self.THINKING:
            return (
                QColor(90, 230, 255),
                QColor(61, 224, 255, 230),
                QColor(212, 168, 75, 100),
                1.1,
            )
        if self._state == self.SPEAKING:
            # Soft white/cyan — not green
            return (
                QColor(200, 232, 244),
                QColor(122, 240, 255, 210),
                QColor(212, 168, 75, 120),
                1.05,
            )
        # Idle: cool dim cyan
        return (
            QColor(40, 100, 130),
            QColor(0, 140, 180, 90),
            QColor(168, 122, 48, 60),
            0.48,
        )

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) * 0.40

        primary, secondary, accent, intensity = self._palette()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        if self._state == self.THINKING:
            pulse = 0.7 + 0.3 * abs(math.sin(self._phase * 1.5))
        elif self._state == self.SPEAKING:
            pulse = 0.6 + 0.4 * abs(math.sin(self._phase * 2.2))
        alpha_scale = intensity * pulse

        # Soft radial core (arc-reactor feel)
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.3)
        core = QColor(primary)
        core.setAlpha(int(60 * alpha_scale))
        mid = QColor(primary)
        mid.setAlpha(int(16 * alpha_scale))
        glow.setColorAt(0.0, core)
        glow.setColorAt(0.4, mid)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.25, radius * 1.25)

        # Sparse constellation / ranging marks around radar
        mark = QColor(accent)
        mark.setAlpha(int(70 + 50 * alpha_scale))
        painter.setPen(QPen(mark, 1.0))
        for ang_deg in (15, 75, 105, 165, 195, 255, 285, 345):
            ang = math.radians(ang_deg + self._dash_phase * 0.15)
            r0, r1 = radius * 1.14, radius * 1.22
            painter.drawLine(
                QPointF(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0),
                QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
            )

        # Outer dashed rotating ring
        dash_pen = QPen(primary)
        da = int(150 * alpha_scale)
        dc = QColor(primary)
        dc.setAlpha(max(35, min(255, da)))
        dash_pen.setColor(dc)
        dash_pen.setWidthF(1.35)
        dash_pen.setStyle(Qt.PenStyle.CustomDashLine)
        dash_pen.setDashPattern([3, 6])
        painter.setPen(dash_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer_r = radius * 1.08
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._dash_phase)
        painter.drawEllipse(QPointF(0, 0), outer_r, outer_r)
        painter.restore()

        # Gold accent arc (Iron Man) — sparse
        gold_pen = QPen(accent)
        ga = QColor(accent)
        ga.setAlpha(int(90 * alpha_scale))
        gold_pen.setColor(ga)
        gold_pen.setWidthF(1.8)
        gold_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(gold_pen)
        gr = radius * 1.02
        grect = QRectF(cx - gr, cy - gr, gr * 2, gr * 2)
        painter.drawArc(grect, int((-self._dash_phase * 0.5) * 16), int(28 * 16))
        painter.drawArc(grect, int((-self._dash_phase * 0.5 + 180) * 16), int(18 * 16))

        # Concentric arc layers
        layers = (
            (1.00, 2.3, 1.0, 95),
            (0.86, 1.7, -1.3, 70),
            (0.70, 1.5, 1.7, 55),
            (0.54, 1.35, -2.1, 45),
            (0.38, 1.15, 2.4, 35),
        )
        for i, (r_frac, width, spin, base_span) in enumerate(layers):
            pen = QPen(primary if i % 2 == 0 else secondary)
            a = int((195 - i * 22) * alpha_scale)
            c = QColor(pen.color())
            c.setAlpha(max(22, min(255, a)))
            pen.setColor(c)
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            r = radius * r_frac
            wobble = 25 * math.sin(self._phase * (1.0 + i * 0.25) + i)
            span = base_span + wobble
            start = math.degrees(self._phase * spin) + i * 32
            rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawArc(rect, int(start * 16), int(span * 16))
            painter.drawArc(rect, int((start + 180) * 16), int(span * 16))

        # Crosshair
        ch = QColor(primary)
        ch.setAlpha(int(85 * alpha_scale))
        painter.setPen(QPen(ch, 1.0))
        gap, arm = 14, 22
        painter.drawLine(QPointF(cx - gap - arm, cy), QPointF(cx - gap, cy))
        painter.drawLine(QPointF(cx + gap, cy), QPointF(cx + gap + arm, cy))
        painter.drawLine(QPointF(cx, cy - gap - arm), QPointF(cx, cy - gap))
        painter.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + gap + arm))

        # Center glyph "J"
        glyph = QColor(primary)
        glyph.setAlpha(int(215 * alpha_scale))
        font = QFont("Menlo", int(radius * 0.28))
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        painter.setFont(font)
        painter.setPen(glyph)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance("J")
        th = fm.ascent()
        painter.drawText(QPointF(cx - tw / 2.0, cy + th / 2.5), "J")

        # Inner arc-reactor pip
        pip = QColor(primary)
        pip.setAlpha(int(180 * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip)
        pip_r = 2.2 + 1.2 * pulse
        painter.drawEllipse(QPointF(cx, cy + radius * 0.22), pip_r, pip_r)

        # Tiny gold tip under pip
        tip = QColor(accent)
        tip.setAlpha(int(120 * alpha_scale))
        painter.setBrush(tip)
        painter.drawEllipse(QPointF(cx, cy + radius * 0.30), 1.1, 1.1)

        painter.end()


class HoloPanel(QWidget):
    """Inset panel with multi-stop fill, inner glow, double frame, corner brackets."""

    def __init__(self, parent: QWidget | None = None, *, scanlines: bool = False) -> None:
        super().__init__(parent)
        self._scanlines = scanlines
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rad = 14.0
        outer = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        inner = QRectF(3.5, 3.5, w - 7.0, h - 7.0)

        # Multi-stop inset fill (rounded)
        fill = QLinearGradient(0, 0, 0, h)
        fill.setColorAt(0.0, QColor(10, 16, 26))
        fill.setColorAt(0.35, QColor(5, 8, 14))
        fill.setColorAt(1.0, QColor(4, 7, 12))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(outer, rad, rad)

        # Soft cyan rim glow
        glow_pen = QPen(QColor(61, 224, 255, 28))
        glow_pen.setWidthF(2.0)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outer.adjusted(1, 1, -1, -1), rad - 1, rad - 1)

        # Soft inner glow along top edge (clipped to rounded shape)
        painter.save()
        painter.setClipRect(outer.toRect())
        top_glow = QLinearGradient(0, 0, 0, 22)
        top_glow.setColorAt(0.0, QColor(61, 224, 255, 28))
        top_glow.setColorAt(1.0, QColor(61, 224, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(top_glow)
        painter.drawRoundedRect(outer.adjusted(1, 1, -1, -1), rad - 1, rad - 1)
        painter.restore()

        # Outer border — subtler
        painter.setPen(QPen(QColor(46, 85, 120, 160), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outer, rad, rad)

        # Inner frame — soft, not a hard second box
        painter.setPen(QPen(QColor(C_BORDER_BRIGHT), 1.0))
        painter.drawRoundedRect(inner, rad - 3, rad - 3)

        # Corner brackets (inset so they sit on the rounded chrome)
        tick = QColor(61, 224, 255, 160)
        inset = 6
        arm = 12
        _draw_double_bracket(
            painter, inset, inset, arm, h_dir=1, v_dir=1, color=tick, thick=1.3, gap=2
        )
        _draw_double_bracket(
            painter, w - 1 - inset, inset, arm, h_dir=-1, v_dir=1, color=tick, thick=1.3, gap=2
        )
        _draw_double_bracket(
            painter, inset, h - 1 - inset, arm, h_dir=1, v_dir=-1, color=tick, thick=1.3, gap=2
        )
        _draw_double_bracket(
            painter,
            w - 1 - inset,
            h - 1 - inset,
            arm,
            h_dir=-1,
            v_dir=-1,
            color=tick,
            thick=1.3,
            gap=2,
        )

        if self._scanlines and h > 4:
            painter.setPen(Qt.PenStyle.NoPen)
            line = QColor(0, 0, 0, 18)
            for y in range(8, h - 8, 3):
                painter.fillRect(10, y, w - 20, 1, line)

        painter.end()


class ChatStack(QWidget):
    """Transcript area with faint AWAITING INPUT watermark when empty."""

    def __init__(self, chat_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chat = chat_widget
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(chat_widget)

        self._await = QLabel("AWAITING INPUT", self)
        self._await.setObjectName("awaitWatermark")
        self._await.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._await.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._empty = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._await.setGeometry(0, 0, self.width(), self.height())
        self._await.raise_()

    def set_empty(self, empty: bool) -> None:
        self._empty = empty
        self._await.setVisible(empty)
