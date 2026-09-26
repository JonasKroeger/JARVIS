"""JARVIS HUD — reference-photo lateral brain. Cyan synapse flashes when speaking."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
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

# —— Luminous quiet palette (lifted charcoal, not near-black void) ——
C_BG = "#0c121c"
C_CYAN = "#7ae8ff"
C_CYAN_SOFT = "#4ec8e0"
C_CYAN_GLOW = "#c8f6ff"
C_TEXT = "#e4eef6"
C_MUTED = "#7a92a4"

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
    color: rgba(122, 232, 255, 70);
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
    background: rgba(255, 95, 87, 140);
}}
QPushButton#winClose:hover {{
    background: #ff7a73;
}}
QPushButton#winMin {{
    background: rgba(254, 188, 46, 120);
}}
QPushButton#winMin:hover {{
    background: #ffd060;
}}
QLabel#ringCaption {{
    color: rgba(110, 180, 200, 110);
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 4px;
    font-weight: 500;
    background: transparent;
}}
QLabel#replyCaption {{
    color: rgba(228, 238, 246, 230);
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
    background: rgba(14, 22, 34, 200);
    color: {C_TEXT};
    border: 1px solid rgba(122, 232, 255, 85);
    border-radius: 16px;
    padding: 10px 16px;
    selection-background-color: #1a3a50;
    font-family: {UI_SANS};
    font-size: 13px;
}}
QLineEdit#ghostInput:focus {{
    border: 1px solid rgba(122, 232, 255, 140);
    background: rgba(16, 26, 40, 220);
}}
QMessageBox {{
    background: {C_BG};
    color: {C_TEXT};
}}
QMessageBox QLabel {{
    color: {C_TEXT};
}}
QMessageBox QPushButton {{
    background: #121a28;
    color: {C_CYAN};
    border: 1px solid rgba(122, 232, 255, 90);
    border-radius: 10px;
    padding: 6px 16px;
    font-family: {MONO};
}}
"""


class HudRoot(QWidget):
    """Lifted charcoal field — soft ambient wash + gentle vignette. No chrome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hudRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG))

        haze = QRadialGradient(QPointF(w / 2.0, h * 0.40), max(w, h) * 0.58)
        haze.setColorAt(0.0, QColor(28, 70, 95, 72))
        haze.setColorAt(0.35, QColor(16, 42, 62, 38))
        haze.setColorAt(0.7, QColor(10, 22, 36, 14))
        haze.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, haze)

        lift = QRadialGradient(QPointF(w / 2.0, h * 0.55), max(w, h) * 0.95)
        lift.setColorAt(0.0, QColor(18, 36, 52, 28))
        lift.setColorAt(0.55, QColor(12, 22, 34, 12))
        lift.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, lift)

        vig = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.88)
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.72, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(2, 4, 8, 110))
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
    """Compat shim — unused in luminous HUD."""

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
    """Compat shim — status is silent (brain activity only).

    Always expects a parent. If constructed without one, stay hidden and
    attribute-less so we never spawn a rogue top-level focus window.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(0)
        self.setMaximumHeight(0)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
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
    """Fading reply caption under the brain — soft text only, no frame."""

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
        self._opacity = max(0.14, self._opacity - 0.022)
        self._apply_opacity()
        if self._opacity <= 0.14:
            self._fade_timer.stop()

    def _apply_opacity(self) -> None:
        a = int(230 * self._opacity)
        if self._is_user:
            color = f"rgba(122, 232, 255, {a})"
        else:
            color = f"rgba(228, 238, 246, {a})"
        self._caption.setStyleSheet(
            f"QLabel#replyCaption {{ color: {color}; "
            f"font-family: {UI_SANS}; font-size: 13px; letter-spacing: 0.3px; "
            f"font-weight: 400; background: transparent; padding: 6px 32px; }}"
        )


# ── Reference-sprite neural brain (identical to assets/brain-ref-side.png) ──


@dataclass
class _Flash:
    """Synapse flash / streak over the reference silhouette."""

    u: float  # 0..1 in sprite local X
    v: float  # 0..1 in sprite local Y
    age: float
    life: float
    bright: float
    radius: float
    vx: float = 0.0
    vy: float = 0.0


def _repo_assets() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _load_brain_sprite() -> tuple[QImage, QPixmap, list[tuple[float, float]]]:
    """Load lateral ref, punch near-black to alpha, cache sample points on mesh.

    Returns (ARGB image, pixmap, list of (u,v) sample points on bright filaments).
    """
    path = _repo_assets() / "brain-ref-side.png"
    src = QImage(str(path))
    if src.isNull():
        empty = QImage(8, 8, QImage.Format.Format_ARGB32)
        empty.fill(QColor(0, 0, 0, 0))
        return empty, QPixmap.fromImage(empty), []

    img = src.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    samples: list[tuple[float, float]] = []
    step = max(2, min(w, h) // 160)

    # Fast in-place ARGB32 punch via byte buffer (BGRA on little-endian Qt)
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())  # type: ignore[attr-defined]
    buf = memoryview(ptr).cast("B")
    bpl = img.bytesPerLine()
    for y in range(h):
        row = y * bpl
        for x in range(w):
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum < 10.0:
                buf[i + 3] = 0
            elif lum < 32.0:
                buf[i + 3] = int(255 * (lum - 10.0) / 22.0)
            else:
                if a < 250:
                    buf[i + 3] = 255
                if lum > 48.0 and (x % step == 0) and (y % step == 0):
                    samples.append((x / max(1, w - 1), y / max(1, h - 1)))

    pm = QPixmap.fromImage(img)
    return img, pm, samples


class OrbVisualizer(QWidget):
    """Floating reference-photo brain — identical lateral filament mesh.

    Primary look is ``assets/brain-ref-side.png`` (scaled, high quality).
    Idle: gentle bob + soft breathe. Speaking / listening / thinking: cyan
    synapse flashes travel over the silhouette (masked to bright filaments).
    Hold-click on the brain region drives listening.
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
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._state = self.IDLE
        self._phase = 0.0
        self._bob = 0.0
        self._scale_breathe = 1.0
        self._holding = False
        self._flashes: list[_Flash] = []
        self._spawn_acc = 0.0
        self._rng = random.Random(7)

        self._img, self._pixmap, self._samples = _load_brain_sprite()
        self._scaled: QPixmap | None = None
        self._scaled_size: tuple[int, int] = (0, 0)
        self._dest = (0.0, 0.0, 0.0, 0.0)  # x, y, w, h of drawn sprite
        self._bright_cache: dict[tuple[int, int], bool] = {}

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)  # ~20 fps idle; rises when active

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _activity(self) -> tuple[float, float, float, int]:
        """Return (spawn_rate, speed, glow_mul, flash_cap) by state."""
        if self._state == self.SPEAKING:
            return 14.0, 1.55, 1.22, 48
        if self._state == self.LISTENING:
            return 4.5, 1.05, 0.92, 22
        if self._state == self.THINKING:
            return 7.0, 1.25, 1.02, 32
        return 0.55, 0.45, 0.62, 8

    def _ensure_scaled(self, tw: int, th: int) -> QPixmap:
        if self._scaled is not None and self._scaled_size == (tw, th):
            return self._scaled
        if self._pixmap.isNull() or tw < 2 or th < 2:
            self._scaled = self._pixmap
            self._scaled_size = (tw, th)
            return self._scaled
        self._scaled = self._pixmap.scaled(
            tw,
            th,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._scaled_size = (tw, th)
        self._bright_cache.clear()
        return self._scaled

    def _sprite_layout(self) -> tuple[float, float, float, float, QPixmap]:
        """Compute destination rect for the brain sprite (with bob + breathe)."""
        w, h = self.width(), self.height()
        # Fit ref inside orb area with padding so reflection + silhouette breathe
        pad = 0.06
        target_w = max(2, int(w * (1.0 - 2 * pad)))
        target_h = max(2, int(h * (1.0 - 2 * pad)))
        pm = self._ensure_scaled(target_w, target_h)
        sw, sh = pm.width(), pm.height()
        # Gentle scale breathe (very subtle — identity first)
        s = self._scale_breathe
        dw, dh = sw * s, sh * s
        cx = w / 2.0
        cy = h / 2.0 + self._bob * min(w, h) * 0.10
        x = cx - dw / 2.0
        y = cy - dh / 2.0
        self._dest = (x, y, dw, dh)
        return x, y, dw, dh, pm

    def _sample_uv(self) -> tuple[float, float] | None:
        if not self._samples:
            return None
        return self._samples[self._rng.randrange(len(self._samples))]

    def _is_brain_uv(self, u: float, v: float) -> bool:
        """True if (u,v) lands on a bright filament in the reference."""
        if self._img.isNull():
            return False
        x = int(max(0, min(self._img.width() - 1, round(u * (self._img.width() - 1)))))
        y = int(max(0, min(self._img.height() - 1, round(v * (self._img.height() - 1)))))
        key = (x, y)
        cached = self._bright_cache.get(key)
        if cached is not None:
            return cached
        c = self._img.pixelColor(x, y)
        ok = c.alpha() > 40 and _luminance(c.red(), c.green(), c.blue()) > 36
        self._bright_cache[key] = ok
        return ok

    def _hit_brain(self, pos: QPointF) -> bool:
        x, y, dw, dh = self._dest
        if dw <= 1 or dh <= 1:
            return False
        if pos.x() < x or pos.x() > x + dw or pos.y() < y or pos.y() > y + dh:
            return False
        u = (pos.x() - x) / dw
        v = (pos.y() - y) / dh
        return self._is_brain_uv(u, v)

    def _tick(self) -> None:
        interval = 50 if self._state == self.IDLE else 33
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        dt = interval / 1000.0

        self._phase = (self._phase + dt) % (math.pi * 200)
        # Soft float — dual-frequency bob (photo stays readable)
        self._bob = (
            math.sin(self._phase * 0.70) * 0.028
            + math.sin(self._phase * 1.20 + 0.6) * 0.010
        )
        # Barely-there breathe so idle still feels alive without morphing shape
        self._scale_breathe = 1.0 + 0.012 * math.sin(self._phase * 0.55)

        spawn_rate, speed, _, flash_cap = self._activity()
        self._spawn_acc += spawn_rate * dt
        burst = 1
        if self._state == self.SPEAKING and self._rng.random() < 0.40:
            burst = 2 + int(self._rng.random() > 0.50)
        while self._spawn_acc >= 1.0:
            self._spawn_acc -= 1.0
            for _ in range(burst):
                uv = self._sample_uv()
                if uv is None:
                    break
                u, v = uv
                # Mild drift along local cortex (horizontal bias = lateral folds)
                ang = self._rng.uniform(-math.pi, math.pi)
                spd = 0.08 + self._rng.random() * 0.14
                if self._state == self.SPEAKING:
                    spd *= 1.35
                self._flashes.append(
                    _Flash(
                        u=u,
                        v=v,
                        age=0.0,
                        life=0.45 + self._rng.random() * 0.55,
                        bright=0.75 + self._rng.random() * 0.25,
                        radius=0.012 + self._rng.random() * 0.018,
                        vx=math.cos(ang) * spd,
                        vy=math.sin(ang) * spd * 0.55,
                    )
                )
            burst = 1

        if len(self._flashes) > flash_cap:
            self._flashes = self._flashes[-flash_cap:]

        alive: list[_Flash] = []
        for f in self._flashes:
            f.age += dt * speed
            f.u += f.vx * dt
            f.v += f.vy * dt
            if f.age < f.life and 0.02 < f.u < 0.98 and 0.02 < f.v < 0.98:
                # Drop flashes that drift off the mesh
                if self._is_brain_uv(f.u, f.v) or f.age < 0.08:
                    alive.append(f)
        self._flashes = alive
        self.update()

    # —— Interaction ——
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # Layout dest before hit-test (paint may not have run yet)
            self._sprite_layout()
            if self._hit_brain(event.position()):
                self._holding = True
                self.hold_started.emit()
                event.accept()
                return
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
            self._paint_brain(event)
        except Exception as exc:  # noqa: BLE001
            try:
                import traceback
                from datetime import datetime

                log = Path(__file__).resolve().parent / "jarvis-debug.log"
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] OrbVisualizer.paintEvent error: {exc!r}\n")
                    f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                    f.flush()
            except Exception:  # noqa: BLE001
                pass

    def _paint_brain(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        _, _, glow_mul, _ = self._activity()
        breathe = 0.92 + 0.08 * (0.5 + 0.5 * math.sin(self._phase * 1.05))
        intensity = glow_mul * breathe
        speaking = self._state == self.SPEAKING

        x, y, dw, dh, pm = self._sprite_layout()
        cx = x + dw / 2.0
        cy = y + dh / 2.0

        painter.setPen(Qt.PenStyle.NoPen)

        # Soft contact shadow under the floating photo
        shadow_y = y + dh * 0.92
        sh = QRadialGradient(QPointF(cx, shadow_y), dw * 0.42)
        sh.setColorAt(0.0, QColor(0, 8, 18, _a(55)))
        sh.setColorAt(0.50, QColor(0, 6, 14, _a(22)))
        sh.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(sh)
        painter.drawEllipse(QPointF(cx, shadow_y), dw * 0.48, dh * 0.07)

        # Very soft cyan core wash behind the sprite (does not reshape it)
        wash = QRadialGradient(QPointF(cx, cy + dh * 0.02), max(dw, dh) * 0.42)
        wash.setColorAt(0.0, QColor(40, 110, 140, _a(28 * intensity)))
        wash.setColorAt(0.55, QColor(20, 55, 75, _a(10 * intensity)))
        wash.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(wash)
        painter.drawEllipse(QPointF(cx, cy), dw * 0.46, dh * 0.40)

        # —— Primary look: the reference photo itself ——
        opacity = 0.88 + 0.12 * intensity
        if self._state == self.IDLE:
            opacity = 0.94 + 0.06 * breathe
        painter.setOpacity(opacity)
        painter.drawPixmap(
            QPointF(x, y),
            pm.scaled(
                max(1, int(round(dw))),
                max(1, int(round(dh))),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if abs(dw - pm.width()) > 0.6 or abs(dh - pm.height()) > 0.6
            else pm,
        )
        painter.setOpacity(1.0)

        # Speaking: gentle overall cyan lift (photo still dominates)
        if speaking or self._state == self.THINKING:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            lift = QRadialGradient(QPointF(cx, cy), max(dw, dh) * 0.48)
            lift_a = 22 if speaking else 12
            lift.setColorAt(0.0, QColor(60, 200, 230, _a(lift_a * intensity)))
            lift.setColorAt(0.55, QColor(30, 120, 160, _a(lift_a * 0.35)))
            lift.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(lift)
            painter.drawEllipse(QPointF(cx, cy), dw * 0.48, dh * 0.42)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # —— Synapse flashes locked to reference silhouette ——
        if self._flashes:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            painter.setPen(Qt.PenStyle.NoPen)
            for f in self._flashes:
                t = f.age / max(1e-6, f.life)
                fade = math.sin(math.pi * min(1.0, t))  # ease in-out
                sx = x + f.u * dw
                sy = y + f.v * dh
                pr = max(dw, dh) * f.radius * (0.85 + 0.55 * f.bright) * (0.7 + 0.3 * fade)
                if speaking:
                    pr *= 1.25
                g = QRadialGradient(QPointF(sx, sy), pr * 2.4)
                core = QColor(230, 250, 255)
                core.setAlpha(_a(200 * f.bright * intensity * fade))
                mid = QColor(64, 230, 235)
                mid.setAlpha(_a(110 * f.bright * intensity * fade))
                rim = QColor(30, 140, 170, _a(40 * f.bright * intensity * fade))
                g.setColorAt(0.0, core)
                g.setColorAt(0.30, mid)
                g.setColorAt(0.70, rim)
                g.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setBrush(g)
                painter.drawEllipse(QPointF(sx, sy), pr * 1.8, pr * 1.8)
                # Tiny hard spark
                painter.setBrush(QColor(240, 252, 255, _a(180 * f.bright * fade)))
                painter.drawEllipse(QPointF(sx, sy), max(0.8, pr * 0.22), max(0.8, pr * 0.22))

                # Short streak along drift direction (speaking / thinking)
                if self._state in (self.SPEAKING, self.THINKING) and (abs(f.vx) + abs(f.vy)) > 0.02:
                    streak = QPainterPath()
                    streak.moveTo(sx - f.vx * dw * 0.35, sy - f.vy * dh * 0.35)
                    streak.lineTo(sx + f.vx * dw * 0.55, sy + f.vy * dh * 0.55)
                    pen = QPen(QColor(120, 235, 250, _a(90 * f.bright * fade * intensity)))
                    pen.setWidthF(max(1.0, pr * 0.35))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(streak)
                    painter.setPen(Qt.PenStyle.NoPen)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.end()


# Back-compat aliases
PulseRing = OrbVisualizer
BrainWidget = OrbVisualizer


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
