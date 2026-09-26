"""Custom JARVIS HUD chrome — pulse ring, frameless title bar, holo panels."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

# —— Palette ——
C_BG = "#05070c"
C_PANEL = "#070b12"
C_PANEL_INSET = "#060910"
C_BORDER = "#1a3048"
C_BORDER_BRIGHT = "#2a4a68"
C_CYAN = "#3de0ff"
C_CYAN_DIM = "#00d4ff"
C_CYAN_SOFT = "#1a8aaa"
C_TEXT = "#d8e6f0"
C_MUTED = "#6a8498"
C_USER = "#3de0ff"
C_ASSIST = "#e8f0f8"
C_DANGER = "#ff5a5a"
C_WARN = "#ffb84d"

MONO = '"Menlo", "SF Mono", "Consolas", "Courier New", monospace'

HUD_STYLESHEET = f"""
QWidget#hudRoot {{
    background: transparent;
}}
QWidget#titleBar {{
    background: rgba(8, 12, 20, 220);
    border: none;
    border-bottom: 1px solid {C_BORDER};
}}
QLabel#wordmark {{
    color: {C_CYAN};
    font-family: {MONO};
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 9px;
}}
QLabel#titleMeta {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 2px;
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
QLabel#statusStrip {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 1.5px;
    padding: 6px 10px;
    background: rgba(6, 10, 16, 180);
    border: 1px solid {C_BORDER};
}}
QLabel#telemetryBit {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel#ringCaption {{
    color: {C_CYAN_SOFT};
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 3px;
}}
QLabel#fieldLabel {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 2px;
}}
QTextEdit#chatLog {{
    background: transparent;
    color: {C_ASSIST};
    border: none;
    padding: 10px 14px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 12px;
}}
QLineEdit#msgInput {{
    background: #060910;
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 2px;
    padding: 11px 14px 11px 8px;
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
    background: #060910;
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 2px;
    padding: 4px 8px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 10px;
    max-width: 160px;
}}
QLineEdit#modelInput:focus {{
    border: 1px solid {C_CYAN_DIM};
}}
QPushButton#sendBtn {{
    background: transparent;
    color: {C_CYAN};
    font-weight: 600;
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 3px;
    padding: 10px 18px;
    border: 1px solid {C_CYAN};
    border-radius: 2px;
    min-width: 110px;
}}
QPushButton#sendBtn:hover {{
    background: rgba(61, 224, 255, 35);
    color: #a8f4ff;
    border-color: #5aebff;
}}
QPushButton#sendBtn:pressed {{
    background: rgba(61, 224, 255, 55);
}}
QPushButton#sendBtn:disabled {{
    color: #3a5060;
    border-color: #1a2838;
    background: transparent;
}}
QPushButton#micBtn {{
    background: #0a121c;
    color: {C_CYAN};
    font-family: {MONO};
    font-size: 14px;
    font-weight: 600;
    border: 1px solid {C_CYAN_DIM};
    border-radius: 22px;
    min-width: 44px;
    max-width: 44px;
    min-height: 44px;
    max-height: 44px;
    padding: 0;
}}
QPushButton#micBtn:hover {{
    background: #122033;
    border-color: {C_CYAN};
}}
QPushButton#micBtn:disabled {{
    background: #0a1018;
    color: #445566;
    border-color: #1a2430;
}}
QPushButton#micBtn[recording="true"] {{
    background: #0a2820;
    color: #5dffb0;
    border: 1px solid #3dff9a;
}}
QCheckBox#speakBox {{
    color: {C_MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1px;
    spacing: 6px;
}}
QCheckBox#speakBox::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {C_BORDER};
    border-radius: 2px;
    background: #060910;
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
    letter-spacing: 1px;
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
    border-radius: 2px;
    padding: 6px 16px;
    font-family: {MONO};
}}
"""


class HudRoot(QWidget):
    """Root canvas: hex/grid backdrop + L-shaped corner brackets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Deep void background
        painter.fillRect(0, 0, w, h, QColor(C_BG))

        # Subtle vertical vignette / scan feel via faint grid
        grid = QColor(61, 224, 255, 14)
        painter.setPen(QPen(grid, 1.0))
        step = 28
        for x in range(0, w + 1, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h + 1, step):
            painter.drawLine(0, y, w, y)

        # Very faint hex-ish diagonal hatch (every other cell)
        diag = QColor(0, 180, 220, 10)
        painter.setPen(QPen(diag, 1.0))
        for i in range(-h, w + h, step * 2):
            painter.drawLine(i, 0, i + h, h)

        # Corner brackets (L-shaped)
        margin = 10
        arm = 28
        thick = 1.6
        cyan = QColor(61, 224, 255, 160)
        painter.setPen(QPen(cyan, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))

        # TL
        painter.drawLine(margin, margin, margin + arm, margin)
        painter.drawLine(margin, margin, margin, margin + arm)
        # TR
        painter.drawLine(w - margin, margin, w - margin - arm, margin)
        painter.drawLine(w - margin, margin, w - margin, margin + arm)
        # BL
        painter.drawLine(margin, h - margin, margin + arm, h - margin)
        painter.drawLine(margin, h - margin, margin, h - margin - arm)
        # BR
        painter.drawLine(w - margin, h - margin, w - margin - arm, h - margin)
        painter.drawLine(w - margin, h - margin, w - margin, h - margin - arm)

        # Inner tick marks mid-edges
        tick = QColor(61, 224, 255, 70)
        painter.setPen(QPen(tick, 1.0))
        mid_y, mid_x = h // 2, w // 2
        painter.drawLine(margin, mid_y - 8, margin, mid_y + 8)
        painter.drawLine(w - margin, mid_y - 8, w - margin, mid_y + 8)
        painter.drawLine(mid_x - 8, margin, mid_x + 8, margin)
        painter.drawLine(mid_x - 8, h - margin, mid_x + 8, h - margin)

        painter.end()


class TitleBar(QWidget):
    """Frameless drag bar with macOS-style traffic lights + JARVIS wordmark."""

    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(36)
        self._drag_pos: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
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

        meta = QLabel("HUD  //  LOCAL")
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
        # Ignore double-click maximize to keep HUD sizing intentional
        event.accept()


class PulseRing(QWidget):
    """Cinematic multi-layer radar / pulse — idle / listening / thinking / speaking."""

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

    def _palette(self) -> tuple[QColor, QColor, float]:
        if self._state == self.LISTENING:
            return QColor(61, 224, 255), QColor(0, 212, 255, 200), 1.0
        if self._state == self.THINKING:
            return QColor(140, 190, 255), QColor(61, 224, 255, 220), 1.05
        if self._state == self.SPEAKING:
            return QColor(80, 255, 210), QColor(61, 224, 255, 230), 1.05
        return QColor(50, 110, 140), QColor(0, 160, 200, 100), 0.5

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dpr = self.devicePixelRatioF()
        if dpr > 1.0:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) * 0.40

        primary, secondary, intensity = self._palette()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        if self._state == self.THINKING:
            pulse = 0.7 + 0.3 * abs(math.sin(self._phase * 1.5))
        elif self._state == self.SPEAKING:
            pulse = 0.6 + 0.4 * abs(math.sin(self._phase * 2.2))
        alpha_scale = intensity * pulse

        # Soft radial core
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.25)
        core = QColor(primary)
        core.setAlpha(int(55 * alpha_scale))
        mid = QColor(primary)
        mid.setAlpha(int(18 * alpha_scale))
        glow.setColorAt(0.0, core)
        glow.setColorAt(0.45, mid)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.2, radius * 1.2)

        # Outer dashed rotating ring
        dash_pen = QPen(primary)
        da = int(160 * alpha_scale)
        dc = QColor(primary)
        dc.setAlpha(max(40, min(255, da)))
        dash_pen.setColor(dc)
        dash_pen.setWidthF(1.4)
        dash_pen.setStyle(Qt.PenStyle.CustomDashLine)
        dash_pen.setDashPattern([4, 5])
        painter.setPen(dash_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer_r = radius * 1.08
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._dash_phase)
        painter.drawEllipse(QPointF(0, 0), outer_r, outer_r)
        painter.restore()

        # 5 concentric arc layers
        layers = (
            (1.00, 2.4, 1.0, 95),
            (0.86, 1.8, -1.3, 70),
            (0.70, 1.6, 1.7, 55),
            (0.54, 1.4, -2.1, 45),
            (0.38, 1.2, 2.4, 35),
        )
        for i, (r_frac, width, spin, base_span) in enumerate(layers):
            pen = QPen(primary if i % 2 == 0 else secondary)
            a = int((200 - i * 22) * alpha_scale)
            c = QColor(pen.color())
            c.setAlpha(max(25, min(255, a)))
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
        ch.setAlpha(int(90 * alpha_scale))
        painter.setPen(QPen(ch, 1.0))
        gap, arm = 14, 22
        painter.drawLine(QPointF(cx - gap - arm, cy), QPointF(cx - gap, cy))
        painter.drawLine(QPointF(cx + gap, cy), QPointF(cx + gap + arm, cy))
        painter.drawLine(QPointF(cx, cy - gap - arm), QPointF(cx, cy - gap))
        painter.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + gap + arm))

        # Center glyph "J"
        glyph = QColor(primary)
        glyph.setAlpha(int(210 * alpha_scale))
        font = QFont("Menlo", int(radius * 0.28))
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        painter.setFont(font)
        painter.setPen(glyph)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance("J")
        th = fm.ascent()
        painter.drawText(QPointF(cx - tw / 2.0, cy + th / 2.5), "J")

        # Tiny inner pip under glyph
        pip = QColor(primary)
        pip.setAlpha(int(180 * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip)
        pip_r = 2.2 + 1.2 * pulse
        painter.drawEllipse(QPointF(cx, cy + radius * 0.22), pip_r, pip_r)

        painter.end()


class HoloPanel(QWidget):
    """Dark inset panel with corner ticks and optional scanline overlay."""

    def __init__(self, parent: QWidget | None = None, *, scanlines: bool = False) -> None:
        super().__init__(parent)
        self._scanlines = scanlines
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Inset fill
        painter.fillRect(0, 0, w, h, QColor(C_PANEL_INSET))

        # Border
        painter.setPen(QPen(QColor(C_BORDER), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)

        # Corner ticks (brighter)
        tick = QColor(61, 224, 255, 180)
        painter.setPen(QPen(tick, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        t = 10
        # TL
        painter.drawLine(0, 0, t, 0)
        painter.drawLine(0, 0, 0, t)
        # TR
        painter.drawLine(w - 1, 0, w - 1 - t, 0)
        painter.drawLine(w - 1, 0, w - 1, t)
        # BL
        painter.drawLine(0, h - 1, t, h - 1)
        painter.drawLine(0, h - 1, 0, h - 1 - t)
        # BR
        painter.drawLine(w - 1, h - 1, w - 1 - t, h - 1)
        painter.drawLine(w - 1, h - 1, w - 1, h - 1 - t)

        if self._scanlines and h > 4:
            painter.setPen(Qt.PenStyle.NoPen)
            line = QColor(0, 0, 0, 28)
            for y in range(0, h, 3):
                painter.fillRect(1, y, w - 2, 1, line)

        painter.end()
