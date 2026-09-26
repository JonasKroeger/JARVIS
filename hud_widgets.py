"""JARVIS HUD chrome — holographic orb visualizer, frameless title, captions."""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
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

# —— Palette (Stark cyan glow on near-black) ——
C_BG = "#020408"
C_PANEL = "#05080e"
C_BORDER = "#1a3048"
C_BORDER_BRIGHT = "#2e5578"
C_CYAN = "#3de0ff"
C_CYAN_DIM = "#00d4ff"
C_CYAN_SOFT = "#1a8aaa"
C_CYAN_GLOW = "#7af0ff"
C_GOLD = "#d4a84b"
C_AMBER = "#ffb84d"
C_TEXT = "#d8e6f0"
C_MUTED = "#6a8498"
C_USER = "#3de0ff"
C_ASSIST = "#e8f0f8"
C_DANGER = "#ff5a5a"
C_SPEAK = "#c8e8f4"

MONO = '"Menlo", "SF Mono", "Consolas", "Courier New", monospace'


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


HUD_STYLESHEET = f"""
QWidget#hudRoot {{
    background: transparent;
}}
QWidget#titleBar {{
    background: transparent;
    border: none;
}}
QLabel#wordmark {{
    color: rgba(61, 224, 255, 90);
    font-family: {MONO};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 6px;
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
    background: rgba(255, 95, 87, 160);
}}
QPushButton#winClose:hover {{
    background: #ff7a73;
}}
QPushButton#winMin {{
    background: rgba(254, 188, 46, 140);
}}
QPushButton#winMin:hover {{
    background: #ffd060;
}}
QLabel#ringCaption {{
    color: {C_CYAN_SOFT};
    font-family: {MONO};
    font-size: 11px;
    letter-spacing: 5px;
    font-weight: 600;
    background: transparent;
}}
QLabel#replyCaption {{
    color: rgba(232, 240, 248, 200);
    font-family: {MONO};
    font-size: 12px;
    letter-spacing: 0.5px;
    background: transparent;
    padding: 6px 18px;
}}
QLabel#hintLabel {{
    color: rgba(106, 132, 152, 140);
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 2px;
    background: transparent;
}}
QLineEdit#ghostInput {{
    background: rgba(5, 10, 18, 200);
    color: {C_TEXT};
    border: 1px solid rgba(61, 224, 255, 90);
    border-radius: 14px;
    padding: 10px 16px;
    selection-background-color: #1a3a50;
    font-family: {MONO};
    font-size: 13px;
}}
QLineEdit#ghostInput:focus {{
    border: 1px solid {C_CYAN_DIM};
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
    """Near-black canvas with soft rounded frame — orb lives on top."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG))
        # Soft vignette
        vig = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.72)
        vig.setColorAt(0.0, QColor(4, 12, 22, 40))
        vig.setColorAt(0.55, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 180))
        painter.fillRect(0, 0, w, h, vig)
        # Soft rounded outer frame
        painter.setPen(QPen(QColor(46, 85, 120, 80), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(3.5, 3.5, w - 7.0, h - 7.0), 18.0, 18.0)
        painter.setPen(QPen(QColor(61, 224, 255, 18), 1.0))
        painter.drawRoundedRect(QRectF(6.5, 6.5, w - 13.0, h - 13.0), 15.0, 15.0)
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


class CaptionStack(QWidget):
    """Fading reply caption under the orb — not a scrolling chat box."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setMaximumHeight(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 0)
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

    def show_reply(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Keep a tiny recent stack in memory; show last line only.
        self._lines.append(text)
        if len(self._lines) > 6:
            self._lines = self._lines[-6:]
        # Truncate display for caption aesthetics
        display = text if len(text) <= 220 else text[:217].rstrip() + "…"
        self._caption.setText(display)
        self._opacity = 1.0
        self._apply_opacity()
        self._fade_timer.stop()
        # Start slow fade after a few seconds
        QTimer.singleShot(6500, self._start_fade)

    def show_user(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        display = text if len(text) <= 160 else text[:157].rstrip() + "…"
        self._caption.setText(f"› {display}")
        self._opacity = 1.0
        self._apply_opacity()
        self._fade_timer.stop()

    def _start_fade(self) -> None:
        if not self._fade_timer.isActive():
            self._fade_timer.start(80)

    def _fade_tick(self) -> None:
        self._opacity = max(0.18, self._opacity - 0.03)
        self._apply_opacity()
        if self._opacity <= 0.18:
            self._fade_timer.stop()

    def _apply_opacity(self) -> None:
        a = int(200 * self._opacity)
        self._caption.setStyleSheet(
            f"QLabel#replyCaption {{ color: rgba(232, 240, 248, {a}); "
            f"font-family: {MONO}; font-size: 12px; background: transparent; "
            f"padding: 6px 18px; }}"
        )


class OrbVisualizer(QWidget):
    """Iron-Man holographic orb: honeycomb core, wavy particle rings, starfield.

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
        self._holding = False
        self._rng = random.Random(42)

        # Ambient starfield (fixed positions, twinkle via phase)
        self._stars = [
            (
                self._rng.random(),
                self._rng.random(),
                0.4 + self._rng.random() * 1.8,
                self._rng.random() * math.pi * 2,
            )
            for _ in range(90)
        ]
        # Soft bokeh dots
        self._bokeh = [
            (
                self._rng.random(),
                self._rng.random(),
                3.0 + self._rng.random() * 7.0,
                self._rng.random() * math.pi * 2,
            )
            for _ in range(14)
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _tick(self) -> None:
        speed = {
            self.IDLE: 0.022,
            self.LISTENING: 0.09,
            self.THINKING: 0.16,
            self.SPEAKING: 0.11,
        }.get(self._state, 0.022)
        wave_speed = {
            self.IDLE: 0.035,
            self.LISTENING: 0.09,
            self.THINKING: 0.14,
            self.SPEAKING: 0.10,
        }.get(self._state, 0.035)
        rot_speed = {
            self.IDLE: 0.25,
            self.LISTENING: 0.9,
            self.THINKING: 1.8,
            self.SPEAKING: 1.1,
        }.get(self._state, 0.25)
        self._phase = (self._phase + speed) % (math.pi * 2)
        self._wave = (self._wave + wave_speed) % (math.pi * 2)
        self._rot = (self._rot + rot_speed) % 360.0
        self.update()

    def _palette(self) -> tuple[QColor, QColor, float]:
        if self._state == self.LISTENING:
            return QColor(90, 235, 255), QColor(255, 184, 77), 1.15
        if self._state == self.THINKING:
            return QColor(100, 240, 255), QColor(122, 240, 255), 1.25
        if self._state == self.SPEAKING:
            return QColor(200, 236, 248), QColor(122, 240, 255), 1.1
        return QColor(45, 190, 220), QColor(0, 160, 200), 0.72

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
            # Never let a paint glitch kill the Qt process.
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
        radius = min(w, h) * 0.34

        primary, accent, intensity = self._palette()
        pulse = 0.62 + 0.38 * (0.5 + 0.5 * math.sin(self._phase))
        if self._state == self.THINKING:
            pulse = 0.75 + 0.25 * abs(math.sin(self._phase * 1.7))
        elif self._state == self.SPEAKING:
            pulse = 0.65 + 0.35 * abs(math.sin(self._phase * 2.4))
        elif self._state == self.LISTENING:
            pulse = 0.8 + 0.2 * abs(math.sin(self._phase * 1.2))
        # intensity can be >1; never let scale push alphas past 255
        alpha_scale = min(1.0, float(intensity) * float(pulse))

        # —— Starfield ——
        painter.setPen(Qt.PenStyle.NoPen)
        for sx, sy, sz, sph in self._stars:
            tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(self._phase * 1.3 + sph))
            a = _a(28 + 90 * tw * (0.55 + 0.45 * intensity))
            c = QColor(primary)
            c.setAlpha(max(8, min(180, a)))
            painter.setBrush(c)
            px = sx * w
            py = sy * h
            painter.drawEllipse(QPointF(px, py), sz * tw, sz * tw)

        # Soft bokeh
        for bx, by, br, bph in self._bokeh:
            tw = 0.5 + 0.5 * (0.5 + 0.5 * math.sin(self._wave + bph))
            a = _a(10 + 22 * tw * intensity)
            c = QColor(primary)
            c.setAlpha(a)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(bx * w, by * h), br * tw, br * tw)

        # —— Soft outer aura ——
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.85)
        c0 = QColor(primary)
        c0.setAlpha(_a(55 * alpha_scale))
        c1 = QColor(primary)
        c1.setAlpha(_a(18 * alpha_scale))
        glow.setColorAt(0.0, c0)
        glow.setColorAt(0.45, c1)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.75, radius * 1.75)

        # —— Wavy particle rings (concentric) ——
        ring_specs = (
            # (base_r_frac, dots, amp_frac, freq, phase_off, size, alpha_base, spin)
            (1.28, 220, 0.055, 5.0, 0.0, 1.55, 160, 0.35),
            (1.10, 180, 0.042, 4.0, 1.2, 1.35, 140, -0.55),
            (0.94, 150, 0.035, 3.5, 2.1, 1.2, 120, 0.8),
            (0.78, 120, 0.028, 3.0, 0.7, 1.05, 100, -1.0),
            (0.64, 90, 0.022, 2.5, 1.8, 0.95, 85, 1.2),
        )
        energy = 1.0
        if self._state == self.LISTENING:
            energy = 1.35
        elif self._state == self.THINKING:
            energy = 1.55
        elif self._state == self.SPEAKING:
            energy = 1.25

        for i, (r_frac, dots, amp, freq, ph_off, sz, base_a, spin) in enumerate(ring_specs):
            base_r = radius * r_frac * (0.97 + 0.03 * math.sin(self._phase + i))
            rot = math.radians(self._rot * spin)
            for d in range(dots):
                t = (d / dots) * math.pi * 2.0 + rot
                # Multi-harmonic wavy radius
                wave = (
                    math.sin(t * freq + self._wave + ph_off)
                    + 0.45 * math.sin(t * (freq + 1.5) - self._wave * 1.3 + i)
                    + 0.2 * math.sin(t * 2.0 + self._phase)
                )
                rr = base_r * (1.0 + amp * energy * wave)
                px = cx + math.cos(t) * rr
                py = cy + math.sin(t) * rr
                # Brightness varies along ring
                bright = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 3 + self._phase + i))
                a = _a(base_a * alpha_scale * bright * (0.75 + 0.25 * pulse))
                col = QColor(primary if i % 2 == 0 else accent)
                col.setAlpha(max(10, min(255, a)))
                painter.setBrush(col)
                painter.setPen(Qt.PenStyle.NoPen)
                ds = sz * (0.85 + 0.3 * bright) * (0.9 + 0.15 * energy)
                painter.drawEllipse(QPointF(px, py), ds, ds)

        # —— Honeycomb / hexagonal core ——
        core_r = radius * 0.38 * (0.96 + 0.04 * pulse)
        # Core glow fill
        core_grad = QRadialGradient(QPointF(cx, cy), core_r * 1.15)
        cg0 = QColor(primary)
        cg0.setAlpha(_a(70 * alpha_scale))
        cg1 = QColor(8, 20, 32, _a(180 * intensity))
        core_grad.setColorAt(0.0, cg1)
        core_grad.setColorAt(0.55, QColor(4, 12, 20, 220))
        core_grad.setColorAt(1.0, cg0)
        painter.setBrush(core_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Hex mesh
        hex_pen = QPen(primary)
        ha = QColor(primary)
        ha.setAlpha(_a(110 * alpha_scale))
        hex_pen.setColor(ha)
        hex_pen.setWidthF(1.0)
        painter.setPen(hex_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Concentric hex rings + radial spokes feel
        for ring_i in range(1, 5):
            hr = core_r * (ring_i / 4.5)
            pts = []
            sides = 6
            for s in range(sides):
                ang = math.radians(60 * s - 90 + self._rot * 0.08)
                # slight breathing
                rr = hr * (1.0 + 0.015 * math.sin(self._phase + s))
                pts.append(QPointF(cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
            for s in range(sides):
                painter.drawLine(pts[s], pts[(s + 1) % sides])
            # subdividing spokes on outer rings
            if ring_i >= 2:
                for s in range(sides):
                    ang = math.radians(60 * s - 90 + self._rot * 0.08)
                    painter.drawLine(
                        QPointF(cx, cy),
                        QPointF(cx + math.cos(ang) * hr, cy + math.sin(ang) * hr),
                    )

        # Finer hex grid overlay (small cells)
        cell = core_r * 0.22
        fine = QColor(primary)
        fine.setAlpha(_a(55 * alpha_scale))
        painter.setPen(QPen(fine, 0.7))
        for row in range(-3, 4):
            for col in range(-3, 4):
                ox = col * cell * 1.5
                oy = row * cell * math.sqrt(3)
                if col % 2:
                    oy += cell * math.sqrt(3) / 2
                if ox * ox + oy * oy > (core_r * 0.82) ** 2:
                    continue
                self._draw_hex(painter, cx + ox, cy + oy, cell * 0.42)

        # Bright rim on core
        rim = QColor(primary)
        rim.setAlpha(_a(200 * alpha_scale))
        painter.setPen(QPen(rim, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Inner bright pip
        pip = QColor(C_CYAN_GLOW)
        pip.setAlpha(_a(210 * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip)
        painter.drawEllipse(QPointF(cx, cy), 2.8 + 1.4 * pulse, 2.8 + 1.4 * pulse)

        painter.end()

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
