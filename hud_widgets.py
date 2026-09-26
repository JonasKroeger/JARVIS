"""JARVIS HUD chrome — holographic orb visualizer, frameless title, captions."""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
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

# —— Palette (Stark cyan + soft gold on near-black) ——
C_BG = "#020408"
C_PANEL = "#05080e"
C_BORDER = "#1a3048"
C_BORDER_BRIGHT = "#2e5578"
C_CYAN = "#3de0ff"
C_CYAN_DIM = "#00d4ff"
C_CYAN_SOFT = "#1a8aaa"
C_CYAN_GLOW = "#7af0ff"
C_GOLD = "#d4a84b"
C_GOLD_SOFT = "#c9a227"
C_AMBER = "#ffb84d"
C_TEXT = "#d8e6f0"
C_MUTED = "#6a8498"
C_USER = "#3de0ff"
C_ASSIST = "#e8f0f8"
C_DANGER = "#ff5a5a"
C_SPEAK = "#c8e8f4"

MONO = '"Menlo", "SF Mono", "Consolas", "Courier New", monospace'
# Prefer system UI for captions — slightly more premium than pure mono
UI_SANS = '"Helvetica Neue", "Avenir Next", ".AppleSystemUIFont", "Segoe UI", sans-serif'


def _a(x: float | int) -> int:
    """Clamp to a valid QColor alpha (0..255)."""
    try:
        v = int(x)
    except (TypeError, ValueError):
        return 0
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def _q(hex_or_name: str, alpha: int | float = 255) -> QColor:
    c = QColor(hex_or_name)
    c.setAlpha(_a(alpha))
    return c


HUD_STYLESHEET = f"""
QWidget#hudRoot {{
    background: transparent;
}}
QWidget#titleBar {{
    background: transparent;
    border: none;
}}
QLabel#wordmark {{
    color: rgba(61, 224, 255, 70);
    font-family: {MONO};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 8px;
}}
QPushButton#winClose, QPushButton#winMin {{
    background: transparent;
    border: none;
    border-radius: 5px;
    min-width: 10px;
    max-width: 10px;
    min-height: 10px;
    max-height: 10px;
    padding: 0;
}}
QPushButton#winClose {{
    background: rgba(255, 95, 87, 150);
}}
QPushButton#winClose:hover {{
    background: #ff7a73;
}}
QPushButton#winMin {{
    background: rgba(254, 188, 46, 130);
}}
QPushButton#winMin:hover {{
    background: #ffd060;
}}
QLabel#ringCaption {{
    color: {C_CYAN_SOFT};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 6px;
    font-weight: 600;
    background: transparent;
}}
QLabel#replyCaption {{
    color: rgba(220, 232, 242, 210);
    font-family: {UI_SANS};
    font-size: 13px;
    letter-spacing: 0.4px;
    font-weight: 400;
    background: transparent;
    padding: 8px 28px;
}}
QLabel#hintLabel {{
    color: rgba(106, 132, 152, 110);
    font-family: {MONO};
    font-size: 8px;
    letter-spacing: 3.5px;
    font-weight: 500;
    background: transparent;
    padding-top: 4px;
}}
QLineEdit#ghostInput {{
    background: rgba(4, 10, 18, 185);
    color: {C_TEXT};
    border: 1px solid rgba(61, 224, 255, 70);
    border-radius: 18px;
    padding: 11px 18px;
    selection-background-color: #1a3a50;
    font-family: {UI_SANS};
    font-size: 13px;
}}
QLineEdit#ghostInput:focus {{
    border: 1px solid rgba(61, 224, 255, 160);
    background: rgba(6, 14, 24, 210);
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


class HudRoot(QWidget):
    """Near-black canvas with soft vignette + corner chrome — orb lives on top."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG))

        # Soft center haze (holo field)
        haze = QRadialGradient(QPointF(w / 2.0, h * 0.42), max(w, h) * 0.55)
        haze.setColorAt(0.0, QColor(8, 28, 42, 55))
        haze.setColorAt(0.45, QColor(4, 14, 24, 18))
        haze.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, haze)

        # Soft vignette
        vig = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.78)
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.62, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 200))
        painter.fillRect(0, 0, w, h, vig)

        # Corner brackets (Stark HUD chrome) instead of a full boxy frame
        m = 10.0
        L = 22.0
        painter.setPen(QPen(QColor(61, 224, 255, 55), 1.15))
        # TL
        painter.drawLine(QPointF(m, m + L), QPointF(m, m))
        painter.drawLine(QPointF(m, m), QPointF(m + L, m))
        # TR
        painter.drawLine(QPointF(w - m - L, m), QPointF(w - m, m))
        painter.drawLine(QPointF(w - m, m), QPointF(w - m, m + L))
        # BL
        painter.drawLine(QPointF(m, h - m - L), QPointF(m, h - m))
        painter.drawLine(QPointF(m, h - m), QPointF(m + L, h - m))
        # BR
        painter.drawLine(QPointF(w - m - L, h - m), QPointF(w - m, h - m))
        painter.drawLine(QPointF(w - m, h - m), QPointF(w - m, h - m - L))

        # Tiny gold accent ticks on top corners
        painter.setPen(QPen(QColor(212, 168, 75, 70), 1.0))
        painter.drawLine(QPointF(m + 4, m + 4), QPointF(m + 10, m + 4))
        painter.drawLine(QPointF(w - m - 10, m + 4), QPointF(w - m - 4, m + 4))

        painter.end()


class TitleBar(QWidget):
    """Minimal frameless drag strip — tiny traffic lights only."""

    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(28)
        self._drag_pos: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(6)

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

        row.addSpacing(10)
        mark = QLabel("JARVIS")
        mark.setObjectName("wordmark")
        row.addWidget(mark)
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


class StatusStrip(QWidget):
    """Compat shim — thin status label (kept for older imports)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(22)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("SYS // STANDBY")
        self._label.setObjectName("ringCaption")
        lay.addWidget(self._label)

    def setText(self, text: str) -> None:  # noqa: N802
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()


class StatusChip(QWidget):
    """Soft holographic status pill under the orb (ONLINE / LISTENING / …)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setMinimumWidth(120)
        self._text = "ONLINE"
        self._phase = 0.0
        self._active = False  # listening / thinking / speaking
        self._danger = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def setText(self, text: str) -> None:  # noqa: N802
        t = (text or "").strip().upper() or "STANDBY"
        if t == self._text:
            return
        self._text = t
        lower = t.lower()
        self._active = any(
            k in lower
            for k in (
                "listen",
                "think",
                "speak",
                "synth",
                "transcrib",
                "process",
                "contact",
                "boot",
            )
        )
        self._danger = "error" in lower
        self.update()
        self.updateGeometry()

    def text(self) -> str:
        return self._text

    def sizeHint(self):  # noqa: N802
        from PyQt6.QtCore import QSize

        # Width tracks label length with generous padding
        return QSize(max(140, 28 + len(self._text) * 10), 34)

    def _tick(self) -> None:
        self._phase = (self._phase + (0.08 if self._active else 0.03)) % (math.pi * 2)
        if self._active or self._danger:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        # Measure text
        font = QFont()
        font.setFamilies(["Menlo", "SF Mono", "Consolas", "Courier New"])
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.2)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(self._text)
        pad_x = 18.0
        pad_y = 6.0
        chip_w = tw + pad_x * 2
        chip_h = fm.height() + pad_y * 2
        chip_w = min(chip_w, w - 4)
        cx = w / 2.0
        cy = h / 2.0
        rect = QRectF(cx - chip_w / 2.0, cy - chip_h / 2.0, chip_w, chip_h)
        radius = chip_h / 2.0

        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        if self._danger:
            base = QColor(255, 90, 90)
            glow_a = 50 + int(40 * pulse)
        elif self._active:
            base = QColor(61, 224, 255)
            glow_a = 40 + int(50 * pulse)
        else:
            base = QColor(45, 190, 220)
            glow_a = 22

        # Soft outer glow
        glow = QRadialGradient(QPointF(cx, cy), chip_w * 0.7)
        g0 = QColor(base)
        g0.setAlpha(_a(glow_a))
        glow.setColorAt(0.0, g0)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), chip_w * 0.55, chip_h * 1.4)

        # Glass fill
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, QColor(10, 24, 36, 190))
        fill.setColorAt(0.5, QColor(6, 14, 24, 170))
        fill.setColorAt(1.0, QColor(4, 10, 18, 200))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setBrush(fill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

        # Specular top edge
        spec = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + chip_h * 0.45))
        spec.setColorAt(0.0, QColor(180, 230, 255, 28))
        spec.setColorAt(1.0, QColor(180, 230, 255, 0))
        painter.setBrush(spec)
        painter.drawPath(path)

        # Border
        border = QColor(base)
        border.setAlpha(_a(90 + (70 * pulse if self._active else 25)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border, 1.05))
        painter.drawPath(path)

        # Inner hairline
        inner = rect.adjusted(1.5, 1.5, -1.5, -1.5)
        painter.setPen(QPen(QColor(61, 224, 255, 18), 0.8))
        painter.drawRoundedRect(inner, radius - 1.5, radius - 1.5)

        # Tiny gold pip on left when active
        if self._active and not self._danger:
            pip = QColor(C_GOLD)
            pip.setAlpha(_a(140 + 80 * pulse))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pip)
            painter.drawEllipse(QPointF(rect.left() + 9.0, cy), 2.0, 2.0)

        # Label
        tc = QColor(base)
        if self._danger:
            tc = QColor(255, 140, 140)
        elif self._active:
            tc = QColor(180, 240, 255)
        else:
            tc = QColor(90, 180, 200)
        tc.setAlpha(230 if self._active or self._danger else 175)
        painter.setPen(tc)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._text)
        painter.end()


class CaptionStack(QWidget):
    """Fading reply caption under the orb — not a scrolling chat box."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(52)
        self.setMaximumHeight(110)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 2, 28, 0)
        lay.setSpacing(4)
        self._caption = QLabel("")
        self._caption.setObjectName("replyCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._caption.setWordWrap(True)
        self._caption.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self._caption)
        self._opacity = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._lines: list[str] = []
        self._is_user = False

    def show_reply(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._lines.append(text)
        if len(self._lines) > 6:
            self._lines = self._lines[-6:]
        display = text if len(text) <= 220 else text[:217].rstrip() + "…"
        self._caption.setText(display)
        self._is_user = False
        self._opacity = 1.0
        self._apply_opacity()
        self._fade_timer.stop()
        QTimer.singleShot(7000, self._start_fade)

    def show_user(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        display = text if len(text) <= 160 else text[:157].rstrip() + "…"
        self._caption.setText(f"›  {display}")
        self._is_user = True
        self._opacity = 1.0
        self._apply_opacity()
        self._fade_timer.stop()

    def _start_fade(self) -> None:
        if not self._fade_timer.isActive():
            self._fade_timer.start(70)

    def _fade_tick(self) -> None:
        self._opacity = max(0.14, self._opacity - 0.022)
        self._apply_opacity()
        if self._opacity <= 0.14:
            self._fade_timer.stop()

    def _apply_opacity(self) -> None:
        a = int(210 * self._opacity)
        if self._is_user:
            color = f"rgba(61, 224, 255, {a})"
        else:
            color = f"rgba(220, 232, 242, {a})"
        self._caption.setStyleSheet(
            f"QLabel#replyCaption {{ color: {color}; "
            f"font-family: {UI_SANS}; font-size: 13px; letter-spacing: 0.4px; "
            f"font-weight: 400; background: transparent; padding: 8px 28px; }}"
        )


class OrbVisualizer(QWidget):
    """Iron-Man holographic orb: glass core, arc rings, restrained particle field.

    Hold-click (or Space from parent) drives listening. States:
    idle / listening / thinking / speaking.
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"

    hold_started = pyqtSignal()
    hold_ended = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Hold to speak · release to send")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._state = self.IDLE
        self._phase = 0.0
        self._wave = 0.0
        self._rot = 0.0
        self._sweep = 0.0
        self._holding = False
        self._rng = random.Random(42)

        # Ambient starfield — fewer, softer (elegant, not noisy)
        self._stars = [
            (
                self._rng.random(),
                self._rng.random(),
                0.35 + self._rng.random() * 1.4,
                self._rng.random() * math.pi * 2,
            )
            for _ in range(56)
        ]
        # Soft bokeh dots
        self._bokeh = [
            (
                self._rng.random(),
                self._rng.random(),
                4.0 + self._rng.random() * 9.0,
                self._rng.random() * math.pi * 2,
            )
            for _ in range(10)
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _tick(self) -> None:
        speed = {
            self.IDLE: 0.018,
            self.LISTENING: 0.075,
            self.THINKING: 0.14,
            self.SPEAKING: 0.095,
        }.get(self._state, 0.018)
        wave_speed = {
            self.IDLE: 0.028,
            self.LISTENING: 0.08,
            self.THINKING: 0.12,
            self.SPEAKING: 0.09,
        }.get(self._state, 0.028)
        rot_speed = {
            self.IDLE: 0.18,
            self.LISTENING: 0.7,
            self.THINKING: 1.55,
            self.SPEAKING: 0.95,
        }.get(self._state, 0.18)
        sweep_speed = {
            self.IDLE: 0.6,
            self.LISTENING: 2.2,
            self.THINKING: 4.0,
            self.SPEAKING: 2.8,
        }.get(self._state, 0.6)
        self._phase = (self._phase + speed) % (math.pi * 2)
        self._wave = (self._wave + wave_speed) % (math.pi * 2)
        self._rot = (self._rot + rot_speed) % 360.0
        self._sweep = (self._sweep + sweep_speed) % 360.0
        self.update()

    def _palette(self) -> tuple[QColor, QColor, QColor, float]:
        """primary, accent, gold, intensity."""
        if self._state == self.LISTENING:
            return (
                QColor(90, 235, 255),
                QColor(255, 196, 90),
                QColor(212, 168, 75),
                1.18,
            )
        if self._state == self.THINKING:
            return (
                QColor(110, 242, 255),
                QColor(140, 245, 255),
                QColor(200, 180, 100),
                1.28,
            )
        if self._state == self.SPEAKING:
            return (
                QColor(200, 236, 248),
                QColor(122, 240, 255),
                QColor(180, 200, 160),
                1.12,
            )
        return (
            QColor(50, 195, 225),
            QColor(0, 155, 195),
            QColor(180, 140, 60),
            0.70,
        )

    # —— Interaction ——
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._holding = True
            self.hold_started.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._holding:
            self._holding = False
            self.hold_ended.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        try:
            self._paint_orb(event)
        except Exception as exc:  # noqa: BLE001
            try:
                import traceback
                from pathlib import Path
                from datetime import datetime

                log = Path(__file__).resolve().parent / "jarvis-debug.log"
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] OrbVisualizer.paintEvent error: {exc!r}\n")
                    f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                    f.flush()
            except Exception:  # noqa: BLE001
                pass

    def _paint_orb(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) * 0.33

        primary, accent, gold, intensity = self._palette()
        pulse = 0.62 + 0.38 * (0.5 + 0.5 * math.sin(self._phase))
        if self._state == self.THINKING:
            pulse = 0.78 + 0.22 * abs(math.sin(self._phase * 1.7))
        elif self._state == self.SPEAKING:
            pulse = 0.68 + 0.32 * abs(math.sin(self._phase * 2.4))
        elif self._state == self.LISTENING:
            pulse = 0.82 + 0.18 * abs(math.sin(self._phase * 1.2))
        alpha_scale = min(1.0, float(intensity) * float(pulse))

        # —— Starfield (restrained) ——
        painter.setPen(Qt.PenStyle.NoPen)
        for sx, sy, sz, sph in self._stars:
            tw = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._phase * 1.1 + sph))
            a = _a(18 + 70 * tw * (0.5 + 0.5 * intensity))
            c = QColor(primary)
            c.setAlpha(max(6, min(140, a)))
            painter.setBrush(c)
            painter.drawEllipse(QPointF(sx * w, sy * h), sz * tw, sz * tw)

        for bx, by, br, bph in self._bokeh:
            tw = 0.5 + 0.5 * (0.5 + 0.5 * math.sin(self._wave + bph))
            a = _a(8 + 16 * tw * intensity)
            c = QColor(primary)
            c.setAlpha(a)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(bx * w, by * h), br * tw, br * tw)

        # —— Multi-layer outer bloom ——
        for bloom_r, bloom_a in (
            (radius * 2.15, 28),
            (radius * 1.75, 42),
            (radius * 1.45, 55),
        ):
            glow = QRadialGradient(QPointF(cx, cy), bloom_r)
            c0 = QColor(primary)
            c0.setAlpha(_a(bloom_a * alpha_scale))
            c1 = QColor(primary)
            c1.setAlpha(_a(bloom_a * 0.25 * alpha_scale))
            glow.setColorAt(0.0, c0)
            glow.setColorAt(0.5, c1)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(cx, cy), bloom_r, bloom_r)

        # —— Thin chrome orbital rings (dashed / arc segments) ——
        self._draw_chrome_rings(painter, cx, cy, radius, primary, gold, alpha_scale)

        # —— Sweep / scan arc (elegant, not noisy) ——
        self._draw_sweep(painter, cx, cy, radius, primary, gold, alpha_scale)

        # —— Restrained wavy particle rings ——
        ring_specs = (
            # (base_r_frac, dots, amp_frac, freq, phase_off, size, alpha_base, spin)
            (1.22, 120, 0.040, 4.5, 0.0, 1.45, 145, 0.30),
            (1.05, 96, 0.032, 3.8, 1.3, 1.25, 125, -0.50),
            (0.88, 78, 0.026, 3.2, 2.0, 1.1, 105, 0.75),
            (0.72, 60, 0.020, 2.6, 0.8, 0.95, 90, -0.95),
        )
        energy = {
            self.LISTENING: 1.30,
            self.THINKING: 1.48,
            self.SPEAKING: 1.22,
        }.get(self._state, 1.0)

        for i, (r_frac, dots, amp, freq, ph_off, sz, base_a, spin) in enumerate(ring_specs):
            base_r = radius * r_frac * (0.98 + 0.02 * math.sin(self._phase + i))
            rot = math.radians(self._rot * spin)
            for d in range(dots):
                t = (d / dots) * math.pi * 2.0 + rot
                wave = (
                    math.sin(t * freq + self._wave + ph_off)
                    + 0.4 * math.sin(t * (freq + 1.4) - self._wave * 1.2 + i)
                    + 0.15 * math.sin(t * 2.0 + self._phase)
                )
                rr = base_r * (1.0 + amp * energy * wave)
                px = cx + math.cos(t) * rr
                py = cy + math.sin(t) * rr
                bright = 0.5 + 0.5 * (0.5 + 0.5 * math.sin(t * 3 + self._phase + i))
                a = _a(base_a * alpha_scale * bright * (0.78 + 0.22 * pulse))
                # Alternate cyan / gold on outer ring when listening
                if i == 0 and self._state == self.LISTENING and d % 7 == 0:
                    col = QColor(gold)
                else:
                    col = QColor(primary if i % 2 == 0 else accent)
                col.setAlpha(max(8, min(255, a)))
                painter.setBrush(col)
                painter.setPen(Qt.PenStyle.NoPen)
                ds = sz * (0.85 + 0.28 * bright) * (0.92 + 0.12 * energy)
                painter.drawEllipse(QPointF(px, py), ds, ds)

        # —— Glass core (Arc Reactor feel) ——
        core_r = radius * 0.36 * (0.97 + 0.03 * pulse)

        # Soft glass disc
        glass = QRadialGradient(QPointF(cx - core_r * 0.15, cy - core_r * 0.2), core_r * 1.2)
        glass.setColorAt(0.0, QColor(40, 90, 120, _a(90 * intensity)))
        glass.setColorAt(0.35, QColor(8, 22, 36, _a(200)))
        glass.setColorAt(0.75, QColor(4, 12, 22, _a(230)))
        glass.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), _a(55 * alpha_scale)))
        painter.setBrush(glass)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Specular highlight crescent
        spec = QRadialGradient(
            QPointF(cx - core_r * 0.28, cy - core_r * 0.32),
            core_r * 0.55,
        )
        spec.setColorAt(0.0, QColor(200, 240, 255, _a(55 * alpha_scale)))
        spec.setColorAt(0.55, QColor(120, 200, 230, _a(12)))
        spec.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(spec)
        painter.drawEllipse(QPointF(cx, cy), core_r * 0.92, core_r * 0.92)

        # Hex mesh (lighter, finer)
        ha = QColor(primary)
        ha.setAlpha(_a(95 * alpha_scale))
        painter.setPen(QPen(ha, 0.9))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ring_i in range(1, 4):
            hr = core_r * (ring_i / 3.6)
            pts = []
            for s in range(6):
                ang = math.radians(60 * s - 90 + self._rot * 0.06)
                rr = hr * (1.0 + 0.012 * math.sin(self._phase + s))
                pts.append(QPointF(cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
            for s in range(6):
                painter.drawLine(pts[s], pts[(s + 1) % 6])
            if ring_i >= 2:
                for s in range(6):
                    ang = math.radians(60 * s - 90 + self._rot * 0.06)
                    painter.drawLine(
                        QPointF(cx, cy),
                        QPointF(cx + math.cos(ang) * hr, cy + math.sin(ang) * hr),
                    )

        # Fine hex cells
        cell = core_r * 0.24
        fine = QColor(primary)
        fine.setAlpha(_a(40 * alpha_scale))
        painter.setPen(QPen(fine, 0.65))
        for row in range(-2, 3):
            for col in range(-2, 3):
                ox = col * cell * 1.5
                oy = row * cell * math.sqrt(3)
                if col % 2:
                    oy += cell * math.sqrt(3) / 2
                if ox * ox + oy * oy > (core_r * 0.78) ** 2:
                    continue
                self._draw_hex(painter, cx + ox, cy + oy, cell * 0.38)

        # Core rim — dual stroke (cyan + soft gold tick)
        rim = QColor(primary)
        rim.setAlpha(_a(210 * alpha_scale))
        painter.setPen(QPen(rim, 1.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)
        # Outer hairline
        rim2 = QColor(primary)
        rim2.setAlpha(_a(60 * alpha_scale))
        painter.setPen(QPen(rim2, 0.8))
        painter.drawEllipse(QPointF(cx, cy), core_r + 3.5, core_r + 3.5)

        # Gold accent ticks on core (listening / always subtle)
        tick_a = _a((140 if self._state == self.LISTENING else 45) * alpha_scale)
        painter.setPen(QPen(_q(C_GOLD, tick_a), 1.4))
        for s in range(6):
            ang = math.radians(60 * s - 90 + self._rot * 0.06)
            r0 = core_r + 1.0
            r1 = core_r + (7.0 if self._state == self.LISTENING else 4.5)
            painter.drawLine(
                QPointF(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0),
                QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
            )

        # Inner bright pip (reactor core)
        pip_r = 2.6 + 1.6 * pulse
        pip_glow = QRadialGradient(QPointF(cx, cy), pip_r * 3.2)
        pg = QColor(C_CYAN_GLOW)
        pg.setAlpha(_a(180 * alpha_scale))
        pip_glow.setColorAt(0.0, pg)
        pip_glow.setColorAt(0.4, QColor(61, 224, 255, _a(80 * alpha_scale)))
        pip_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip_glow)
        painter.drawEllipse(QPointF(cx, cy), pip_r * 3.0, pip_r * 3.0)
        painter.setBrush(_q(C_CYAN_GLOW, 220 * alpha_scale))
        painter.drawEllipse(QPointF(cx, cy), pip_r, pip_r)

        painter.end()

    def _draw_chrome_rings(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius: float,
        primary: QColor,
        gold: QColor,
        alpha_scale: float,
    ) -> None:
        """Dashed / gapped orbital rings — Arc Reactor chrome."""
        rings = (
            # (r_frac, width, alpha, dash_on, dash_off, rot_sign, use_gold)
            (1.42, 1.15, 70, 14.0, 8.0, 0.15, False),
            (1.32, 0.85, 45, 6.0, 10.0, -0.22, True),
            (0.55, 1.05, 90, 18.0, 6.0, 0.4, False),
            (0.48, 0.75, 50, 4.0, 8.0, -0.55, False),
        )
        for r_frac, width, base_a, dash_on, dash_off, rot_sign, use_gold in rings:
            r = radius * r_frac
            col = QColor(gold if use_gold else primary)
            col.setAlpha(_a(base_a * alpha_scale))
            pen = QPen(col, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            # Draw as arc segments instead of Qt dash (smoother on retina)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rot = math.radians(self._rot * rot_sign)
            # Approximate circumference for dash count
            circ = 2 * math.pi * r
            seg = dash_on
            gap = dash_off
            unit = seg + gap
            n = max(8, int(circ / unit))
            for i in range(n):
                a0 = rot + (i * unit) / r
                a1 = a0 + seg / r
                # Convert to Qt arc degrees (Qt: 16ths of degree, 0=3 o'clock, CCW)
                start_deg = -math.degrees(a0)
                span_deg = -math.degrees(a1 - a0)
                rect = QRectF(cx - r, cy - r, r * 2, r * 2)
                painter.drawArc(rect, int(start_deg * 16), int(span_deg * 16))

    def _draw_sweep(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius: float,
        primary: QColor,
        gold: QColor,
        alpha_scale: float,
    ) -> None:
        """Single soft rotating sweep wedge — restrained radar feel."""
        if self._state == self.IDLE:
            span = 28.0
            r = radius * 1.28
            a_mul = 0.35
            col = primary
        elif self._state == self.LISTENING:
            span = 42.0
            r = radius * 1.34
            a_mul = 0.7
            col = gold
        elif self._state == self.THINKING:
            span = 55.0
            r = radius * 1.36
            a_mul = 0.85
            col = primary
        else:  # speaking
            span = 36.0
            r = radius * 1.30
            a_mul = 0.6
            col = primary

        ang = self._sweep
        # Soft wedge via several arcs fading out
        for i in range(6):
            t = i / 5.0
            a = _a((55 * (1.0 - t) * a_mul) * alpha_scale)
            c = QColor(col)
            c.setAlpha(a)
            painter.setPen(QPen(c, 1.6 - t * 0.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start = -(ang - span * 0.15 + span * t)
            span_i = span * (1.0 - t) * 0.35
            rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawArc(rect, int(start * 16), int(-span_i * 16))

        # Leading tip pip
        tip_ang = math.radians(ang)
        tip = QPointF(cx + math.cos(tip_ang) * r, cy - math.sin(tip_ang) * r)
        tip_c = QColor(col)
        tip_c.setAlpha(_a(160 * a_mul * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tip_c)
        painter.drawEllipse(tip, 2.2, 2.2)

    @staticmethod
    def _draw_hex(painter: QPainter, cx: float, cy: float, r: float) -> None:
        pts = []
        for s in range(6):
            ang = math.radians(60 * s - 30)
            pts.append(QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r))
        for s in range(6):
            painter.drawLine(pts[s], pts[(s + 1) % 6])


# Back-compat alias so older imports keep working during transition
PulseRing = OrbVisualizer


# Kept for import compatibility; unused in orb-first UI
class HoloPanel(QWidget):
    def __init__(self, parent: QWidget | None = None, *, scanlines: bool = False) -> None:
        super().__init__(parent)
        self._scanlines = scanlines

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C_BG))
        painter.end()


class ChatStack(QWidget):
    def __init__(self, chat_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(chat_widget)
        self._empty = True

    def set_empty(self, empty: bool) -> None:
        self._empty = empty
