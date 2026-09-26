"""JARVIS HUD — quiet soft-glow orb. Minimal chrome."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSignal
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

# —— Quiet palette ——
C_BG = "#030508"
C_CYAN = "#7ae8ff"
C_CYAN_SOFT = "#4ec8e0"
C_CYAN_GLOW = "#c8f6ff"
C_TEXT = "#d8e6f0"
C_MUTED = "#5a7080"

MONO = '"Menlo", "SF Mono", "Consolas", "Courier New", monospace'
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
    color: rgba(122, 232, 255, 45);
    font-family: {MONO};
    font-size: 8px;
    font-weight: 500;
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
    background: rgba(255, 95, 87, 120);
}}
QPushButton#winClose:hover {{
    background: #ff7a73;
}}
QPushButton#winMin {{
    background: rgba(254, 188, 46, 100);
}}
QPushButton#winMin:hover {{
    background: #ffd060;
}}
QLabel#ringCaption {{
    color: rgba(90, 160, 180, 90);
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 4px;
    font-weight: 500;
    background: transparent;
}}
QLabel#replyCaption {{
    color: rgba(220, 232, 242, 200);
    font-family: {UI_SANS};
    font-size: 13px;
    letter-spacing: 0.3px;
    font-weight: 400;
    background: transparent;
    padding: 6px 32px;
}}
QLabel#hintLabel {{
    color: rgba(90, 112, 128, 0);
    font-family: {MONO};
    font-size: 1px;
    background: transparent;
}}
QLineEdit#ghostInput {{
    background: rgba(8, 14, 22, 140);
    color: {C_TEXT};
    border: 1px solid rgba(122, 232, 255, 35);
    border-radius: 16px;
    padding: 10px 16px;
    selection-background-color: #1a3a50;
    font-family: {UI_SANS};
    font-size: 13px;
}}
QLineEdit#ghostInput:focus {{
    border: 1px solid rgba(122, 232, 255, 90);
    background: rgba(10, 18, 28, 170);
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
    border: 1px solid rgba(122, 232, 255, 80);
    border-radius: 10px;
    padding: 6px 16px;
    font-family: {MONO};
}}
"""


class HudRoot(QWidget):
    """Near-black canvas — soft vignette only, no chrome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG))

        # Very soft center haze so the orb feels seated in light
        haze = QRadialGradient(QPointF(w / 2.0, h * 0.42), max(w, h) * 0.5)
        haze.setColorAt(0.0, QColor(10, 30, 42, 28))
        haze.setColorAt(0.5, QColor(4, 12, 20, 8))
        haze.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, haze)

        # Soft edge vignette
        vig = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.82)
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.7, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 160))
        painter.fillRect(0, 0, w, h, vig)
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
    """Compat shim — unused in minimal HUD."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(0)
        self.hide()
        self._label = QLabel("")

    def setText(self, text: str) -> None:  # noqa: N802, ARG002
        pass

    def text(self) -> str:
        return ""


class StatusChip(QWidget):
    """Compat shim — status is silent (orb brightness only)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(0)
        self.setMaximumHeight(0)
        self.hide()
        self._text = ""

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = (text or "").strip()

    def text(self) -> str:
        return self._text

    def sizeHint(self):  # noqa: N802
        from PyQt6.QtCore import QSize

        return QSize(0, 0)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        pass


class CaptionStack(QWidget):
    """Fading reply caption under the orb — soft text only, no frame."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setMaximumHeight(100)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 2, 36, 0)
        lay.setSpacing(0)
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
        self._caption.setText(display)
        self._is_user = True
        self._opacity = 1.0
        self._apply_opacity()
        self._fade_timer.stop()

    def _start_fade(self) -> None:
        if not self._fade_timer.isActive():
            self._fade_timer.start(70)

    def _fade_tick(self) -> None:
        self._opacity = max(0.12, self._opacity - 0.022)
        self._apply_opacity()
        if self._opacity <= 0.12:
            self._fade_timer.stop()

    def _apply_opacity(self) -> None:
        a = int(200 * self._opacity)
        if self._is_user:
            color = f"rgba(122, 232, 255, {a})"
        else:
            color = f"rgba(220, 232, 242, {a})"
        self._caption.setStyleSheet(
            f"QLabel#replyCaption {{ color: {color}; "
            f"font-family: {UI_SANS}; font-size: 13px; letter-spacing: 0.3px; "
            f"font-weight: 400; background: transparent; padding: 6px 32px; }}"
        )


class OrbVisualizer(QWidget):
    """Quiet circle of light — soft cyan/white glow. State = brightness/pulse only.

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
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Hold to speak")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._state = self.IDLE
        self._phase = 0.0
        self._holding = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)  # ~25 fps — enough for soft pulse

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _tick(self) -> None:
        speed = {
            self.IDLE: 0.022,
            self.LISTENING: 0.055,
            self.THINKING: 0.09,
            self.SPEAKING: 0.07,
        }.get(self._state, 0.022)
        self._phase = (self._phase + speed) % (math.pi * 2)
        self.update()

    def _intensity(self) -> float:
        """Base brightness multiplier by state."""
        if self._state == self.LISTENING:
            return 1.25
        if self._state == self.THINKING:
            return 1.15
        if self._state == self.SPEAKING:
            return 1.2
        return 0.78

    def _pulse(self) -> float:
        if self._state == self.THINKING:
            return 0.82 + 0.18 * abs(math.sin(self._phase * 1.6))
        if self._state == self.SPEAKING:
            return 0.75 + 0.25 * abs(math.sin(self._phase * 2.2))
        if self._state == self.LISTENING:
            return 0.88 + 0.12 * abs(math.sin(self._phase * 1.1))
        return 0.7 + 0.3 * (0.5 + 0.5 * math.sin(self._phase))

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
        radius = min(w, h) * 0.28

        intensity = self._intensity()
        pulse = self._pulse()
        scale = min(1.35, intensity * pulse)

        # Soft outer blooms — quiet circle of light
        painter.setPen(Qt.PenStyle.NoPen)
        for bloom_r, bloom_a in (
            (radius * 2.4, 18),
            (radius * 1.9, 32),
            (radius * 1.45, 55),
            (radius * 1.1, 90),
        ):
            glow = QRadialGradient(QPointF(cx, cy), bloom_r)
            c0 = QColor(122, 232, 255)
            c0.setAlpha(_a(bloom_a * scale))
            c1 = QColor(122, 232, 255)
            c1.setAlpha(_a(bloom_a * 0.2 * scale))
            glow.setColorAt(0.0, c0)
            glow.setColorAt(0.55, c1)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(cx, cy), bloom_r, bloom_r)

        # Soft glass body
        body_r = radius * 0.72
        glass = QRadialGradient(QPointF(cx - body_r * 0.12, cy - body_r * 0.18), body_r * 1.15)
        glass.setColorAt(0.0, QColor(180, 240, 255, _a(55 * scale)))
        glass.setColorAt(0.25, QColor(40, 100, 130, _a(70 * scale)))
        glass.setColorAt(0.55, QColor(8, 24, 36, _a(160)))
        glass.setColorAt(0.85, QColor(4, 12, 20, _a(200)))
        glass.setColorAt(1.0, QColor(122, 232, 255, _a(40 * scale)))
        painter.setBrush(glass)
        painter.drawEllipse(QPointF(cx, cy), body_r, body_r)

        # Specular highlight — one soft crescent
        spec = QRadialGradient(
            QPointF(cx - body_r * 0.25, cy - body_r * 0.3),
            body_r * 0.5,
        )
        spec.setColorAt(0.0, QColor(220, 248, 255, _a(50 * scale)))
        spec.setColorAt(0.5, QColor(140, 210, 235, _a(12)))
        spec.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(spec)
        painter.drawEllipse(QPointF(cx, cy), body_r * 0.9, body_r * 0.9)

        # Very faint rim hairline (almost invisible idle)
        rim_a = _a((35 if self._state == self.IDLE else 70) * scale)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_q(C_CYAN, rim_a), 1.0))
        painter.drawEllipse(QPointF(cx, cy), body_r, body_r)

        # Hot soft core pip
        pip_r = 4.5 + 2.0 * pulse
        pip_glow = QRadialGradient(QPointF(cx, cy), pip_r * 4.5)
        pg = QColor(C_CYAN_GLOW)
        pg.setAlpha(_a(200 * scale))
        pip_glow.setColorAt(0.0, pg)
        pip_glow.setColorAt(0.3, QColor(200, 246, 255, _a(120 * scale)))
        pip_glow.setColorAt(0.65, QColor(122, 232, 255, _a(40 * scale)))
        pip_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip_glow)
        painter.drawEllipse(QPointF(cx, cy), pip_r * 4.0, pip_r * 4.0)

        painter.setBrush(_q("#f0fcff", 240 * scale))
        painter.drawEllipse(QPointF(cx, cy), pip_r * 0.45, pip_r * 0.45)
        painter.setBrush(_q(C_CYAN_GLOW, 220 * scale))
        painter.drawEllipse(QPointF(cx, cy), pip_r * 0.9, pip_r * 0.9)

        painter.end()


# Back-compat alias
PulseRing = OrbVisualizer


class HoloPanel(QWidget):
    """Compat shim."""

    def __init__(self, parent: QWidget | None = None, *, scanlines: bool = False) -> None:
        super().__init__(parent)
        self._scanlines = scanlines

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C_BG))
        painter.end()


class ChatStack(QWidget):
    """Compat shim."""

    def __init__(self, chat_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(chat_widget)
        self._empty = True

    def set_empty(self, empty: bool) -> None:
        self._empty = empty
