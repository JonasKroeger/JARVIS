"""JARVIS HUD — floating neural brain. Synapses light when speaking."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
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


# ── Procedural neural brain ──────────────────────────────────────────────


@dataclass
class _Node:
    x: float
    y: float
    z: float
    r: float
    flash: float = 0.0


@dataclass
class _Edge:
    a: int
    b: int
    curl: float  # control-point offset for curved axon


@dataclass
class _Pulse:
    edge: int
    t: float  # 0..1 along axon
    speed: float
    bright: float


@dataclass
class _BrainGraph:
    nodes: list[_Node] = field(default_factory=list)
    edges: list[_Edge] = field(default_factory=list)


def _in_brain(x: float, y: float, z: float) -> bool:
    """Stylized two-hemisphere brain volume (unit-ish coords)."""
    # Longitudinal fissure — slight gap on midline
    ax = abs(x)
    # Main ellipsoid per hemisphere, shifted outward
    hx = ax - 0.22
    # Upper cortex bulge
    cortex = (hx * hx) / (0.72 * 0.72) + (y * y) / (0.55 * 0.55) + (z * z) / (0.48 * 0.48)
    if cortex > 1.0:
        # Allow a softer lower brainstem / cerebellum bump
        stem = (x * x) / (0.28 * 0.28) + ((y + 0.42) ** 2) / (0.32 * 0.32) + (z * z) / (0.28 * 0.28)
        if stem > 1.0:
            return False
    # Flatten underside a touch (not a perfect ball)
    if y < -0.55:
        return False
    # Keep midline cleft except near bottom (corpus-ish bridge)
    if ax < 0.06 and y > -0.15:
        return False
    return True


def _build_brain(seed: int = 42) -> _BrainGraph:
    rng = random.Random(seed)
    nodes: list[_Node] = []

    # Rejection-sample nodes inside brain volume
    attempts = 0
    while len(nodes) < 78 and attempts < 4000:
        attempts += 1
        x = rng.uniform(-1.05, 1.05)
        y = rng.uniform(-0.72, 0.72)
        z = rng.uniform(-0.7, 0.7)
        if not _in_brain(x, y, z):
            continue
        # Prefer cortex surface — push outward a bit
        if rng.random() < 0.55:
            nrm = math.sqrt(x * x + y * y + z * z) or 1.0
            push = 0.08 + rng.random() * 0.12
            x *= 1.0 + push / nrm
            y *= 1.0 + push / nrm * 0.85
            z *= 1.0 + push / nrm
            if not _in_brain(x * 0.92, y * 0.92, z * 0.92):
                # still accept slightly outside for silhouette
                pass
        # Spacing: skip if too close to existing
        too_close = False
        for n in nodes:
            dx, dy, dz = n.x - x, n.y - y, n.z - z
            if dx * dx + dy * dy + dz * dz < 0.045:
                too_close = True
                break
        if too_close:
            continue
        nodes.append(_Node(x=x, y=y, z=z, r=0.028 + rng.random() * 0.022))

    # Guaranteed silhouette anchors (left / right lobes + stem)
    anchors = [
        (-0.55, 0.15, 0.1),
        (0.55, 0.15, 0.1),
        (-0.7, -0.05, 0.0),
        (0.7, -0.05, 0.0),
        (-0.4, 0.4, 0.15),
        (0.4, 0.4, 0.15),
        (-0.25, -0.35, 0.05),
        (0.25, -0.35, 0.05),
        (0.0, -0.5, 0.0),
        (-0.15, 0.05, 0.35),
        (0.15, 0.05, 0.35),
        (-0.15, 0.05, -0.35),
        (0.15, 0.05, -0.35),
    ]
    for ax, ay, az in anchors:
        nodes.append(_Node(x=ax, y=ay, z=az, r=0.04))

    # k-NN edges + a few long-range commissural links
    edges: list[_Edge] = []
    seen: set[tuple[int, int]] = set()
    k = 4
    for i, ni in enumerate(nodes):
        dists: list[tuple[float, int]] = []
        for j, nj in enumerate(nodes):
            if i == j:
                continue
            dx, dy, dz = ni.x - nj.x, ni.y - nj.y, ni.z - nj.z
            dists.append((dx * dx + dy * dy + dz * dz, j))
        dists.sort()
        for _, j in dists[:k]:
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in seen:
                continue
            # Prefer same-hemisphere local wiring; allow some cross
            if nodes[a].x * nodes[b].x < 0 and abs(nodes[a].x) > 0.15 and abs(nodes[b].x) > 0.15:
                if rng.random() > 0.22:
                    continue
            seen.add((a, b))
            edges.append(_Edge(a=a, b=b, curl=rng.uniform(-0.35, 0.35)))

    # Explicit corpus callosum bridges
    left = [i for i, n in enumerate(nodes) if n.x < -0.12]
    right = [i for i, n in enumerate(nodes) if n.x > 0.12]
    for _ in range(10):
        if not left or not right:
            break
        a = rng.choice(left)
        b = rng.choice(right)
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        # Prefer similar y
        if abs(nodes[a].y - nodes[b].y) > 0.35:
            continue
        seen.add(key)
        edges.append(_Edge(a=a, b=b, curl=rng.uniform(-0.2, 0.2)))

    return _BrainGraph(nodes=nodes, edges=edges)


class OrbVisualizer(QWidget):
    """Floating procedural neural brain — synapses light on talk.

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
        self._yaw = 0.0
        self._bob = 0.0
        self._holding = False
        self._graph = _build_brain(42)
        self._pulses: list[_Pulse] = []
        self._spawn_acc = 0.0
        self._rng = random.Random(7)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60 fps

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _activity(self) -> tuple[float, float, float]:
        """Return (spawn_rate, pulse_speed, node_glow) by state."""
        if self._state == self.SPEAKING:
            return 4.2, 1.35, 1.0
        if self._state == self.LISTENING:
            return 2.6, 1.05, 0.85
        if self._state == self.THINKING:
            return 3.4, 1.2, 0.92
        return 0.55, 0.55, 0.45

    def _tick(self) -> None:
        dt = 0.016
        # Gentle idle spin + bob
        spin = {
            self.IDLE: 0.18,
            self.LISTENING: 0.28,
            self.THINKING: 0.42,
            self.SPEAKING: 0.55,
        }.get(self._state, 0.18)
        self._yaw = (self._yaw + spin * dt) % (math.pi * 2)
        self._phase = (self._phase + dt) % (math.pi * 2)
        self._bob = math.sin(self._phase * 0.7) * 0.035

        spawn_rate, pulse_speed, _ = self._activity()
        self._spawn_acc += spawn_rate * dt
        while self._spawn_acc >= 1.0 and self._graph.edges:
            self._spawn_acc -= 1.0
            ei = self._rng.randrange(len(self._graph.edges))
            self._pulses.append(
                _Pulse(
                    edge=ei,
                    t=0.0,
                    speed=pulse_speed * (0.75 + self._rng.random() * 0.55),
                    bright=0.7 + self._rng.random() * 0.3,
                )
            )
            # Flash endpoints lightly
            e = self._graph.edges[ei]
            self._graph.nodes[e.a].flash = max(self._graph.nodes[e.a].flash, 0.7)
            self._graph.nodes[e.b].flash = max(self._graph.nodes[e.b].flash, 0.55)

        # Cap pulse count for perf
        if len(self._pulses) > 48:
            self._pulses = self._pulses[-48:]

        alive: list[_Pulse] = []
        for p in self._pulses:
            p.t += p.speed * dt * 0.85
            if p.t < 1.0:
                alive.append(p)
            else:
                e = self._graph.edges[p.edge]
                self._graph.nodes[e.b].flash = max(self._graph.nodes[e.b].flash, p.bright)
        self._pulses = alive

        # Decay node flashes
        decay = 2.8 * dt
        for n in self._graph.nodes:
            n.flash = max(0.0, n.flash - decay)

        self.update()

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
            self._paint_brain(event)
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

    def _project(self, x: float, y: float, z: float, cx: float, cy: float, scale: float) -> tuple[float, float, float]:
        """Yaw rotation + slight tilt → screen xy + depth weight."""
        cyaw, syaw = math.cos(self._yaw), math.sin(self._yaw)
        # yaw around Y
        xr = x * cyaw - z * syaw
        zr = x * syaw + z * cyaw
        yr = y + self._bob
        # slight pitch (~18°) for 3D read
        pitch = 0.32
        cp, sp = math.cos(pitch), math.sin(pitch)
        y2 = yr * cp - zr * sp
        z2 = yr * sp + zr * cp
        # perspective foreshortening
        persp = 1.0 / (1.0 + z2 * 0.22)
        sx = cx + xr * scale * persp
        sy = cy + y2 * scale * persp
        depth = 0.5 + 0.5 * z2  # ~0..1 frontness
        return sx, sy, depth

    def _axon_points(
        self, ax: float, ay: float, az: float, bx: float, by: float, bz: float, curl: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        """Start, control, end in local brain space for a curved axon."""
        mx = (ax + bx) * 0.5
        my = (ay + by) * 0.5
        mz = (az + bz) * 0.5
        # Perp offset in XY for curl
        dx, dy = bx - ax, by - ay
        length = math.sqrt(dx * dx + dy * dy) or 1.0
        px, py = -dy / length, dx / length
        # Lift control toward outer cortex
        lift = 0.08 + abs(curl) * 0.12
        cx_ = mx + px * curl * 0.45
        cy_ = my + py * curl * 0.45 + lift
        cz_ = mz + curl * 0.15
        return (ax, ay, az), (cx_, cy_, cz_), (bx, by, bz)

    def _bezier(self, p0, p1, p2, t: float) -> tuple[float, float, float]:
        u = 1.0 - t
        return (
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            u * u * p0[2] + 2 * u * t * p1[2] + t * t * p2[2],
        )

    def _paint_brain(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0 - h * 0.02
        scale = min(w, h) * 0.38

        _, _, glow_mul = self._activity()
        breathe = 0.88 + 0.12 * (0.5 + 0.5 * math.sin(self._phase * 1.1))
        intensity = glow_mul * breathe

        # Soft volumetric aura — brain-shaped glow (not a hard circle blob)
        painter.setPen(Qt.PenStyle.NoPen)
        for bloom_r, bloom_a in (
            (scale * 1.55, 22),
            (scale * 1.15, 40),
            (scale * 0.85, 58),
        ):
            glow = QRadialGradient(QPointF(cx, cy), bloom_r)
            c0 = QColor(90, 200, 230)
            c0.setAlpha(_a(bloom_a * intensity))
            c1 = QColor(60, 140, 180)
            c1.setAlpha(_a(bloom_a * 0.25 * intensity))
            glow.setColorAt(0.0, c0)
            glow.setColorAt(0.45, c1)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            # Slightly wider than tall — brain mass
            painter.drawEllipse(QPointF(cx, cy), bloom_r * 1.15, bloom_r * 0.92)

        # Soft glass volume fill (read as translucent brain mass)
        glass = QRadialGradient(QPointF(cx - scale * 0.1, cy - scale * 0.15), scale * 0.95)
        glass.setColorAt(0.0, QColor(140, 220, 240, _a(28 * intensity)))
        glass.setColorAt(0.35, QColor(40, 90, 120, _a(55)))
        glass.setColorAt(0.7, QColor(12, 30, 48, _a(70)))
        glass.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(glass)
        painter.drawEllipse(QPointF(cx, cy), scale * 1.05, scale * 0.82)

        nodes = self._graph.nodes
        edges = self._graph.edges

        # Project all nodes once
        proj: list[tuple[float, float, float]] = []
        for n in nodes:
            proj.append(self._project(n.x, n.y, n.z, cx, cy, scale))

        # Draw axons back-to-front roughly by mid depth
        edge_order = list(range(len(edges)))
        edge_order.sort(
            key=lambda i: (proj[edges[i].a][2] + proj[edges[i].b][2]) * 0.5
        )

        for ei in edge_order:
            e = edges[ei]
            na, nb = nodes[e.a], nodes[e.b]
            p0, p1, p2 = self._axon_points(na.x, na.y, na.z, nb.x, nb.y, nb.z, e.curl)
            # Sample quadratic for path
            path = QPainterPath()
            s0 = self._project(*p0, cx, cy, scale)
            path.moveTo(s0[0], s0[1])
            samples = 8
            for s in range(1, samples + 1):
                t = s / samples
                bx, by, bz = self._bezier(p0, p1, p2, t)
                sx, sy, _ = self._project(bx, by, bz, cx, cy, scale)
                path.lineTo(sx, sy)
            mid_d = (proj[e.a][2] + proj[e.b][2]) * 0.5
            base_a = 28 + 50 * mid_d
            # Active flash if either node lit
            flash = max(na.flash, nb.flash)
            base_a += flash * 90
            base_a *= 0.55 + 0.45 * intensity
            pen = QPen(_q(C_CYAN_SOFT, base_a), 1.15 + flash * 0.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        # Traveling synapse pulses
        for p in self._pulses:
            e = edges[p.edge]
            na, nb = nodes[e.a], nodes[e.b]
            p0, p1, p2 = self._axon_points(na.x, na.y, na.z, nb.x, nb.y, nb.z, e.curl)
            bx, by, bz = self._bezier(p0, p1, p2, p.t)
            sx, sy, depth = self._project(bx, by, bz, cx, cy, scale)
            # Soft trail behind pulse
            for trail in (0.08, 0.04, 0.0):
                tt = max(0.0, p.t - trail)
                tx, ty, tz = self._bezier(p0, p1, p2, tt)
                tsx, tsy, _ = self._project(tx, ty, tz, cx, cy, scale)
                fade = 1.0 - trail * 8
                pr = (3.2 + 2.2 * p.bright) * (0.7 + 0.3 * depth) * fade
                g = QRadialGradient(QPointF(tsx, tsy), pr * 3.2)
                core = QColor(200, 250, 255)
                core.setAlpha(_a(220 * p.bright * intensity * fade))
                mid = QColor(122, 232, 255)
                mid.setAlpha(_a(110 * p.bright * intensity * fade))
                g.setColorAt(0.0, core)
                g.setColorAt(0.4, mid)
                g.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(g)
                painter.drawEllipse(QPointF(tsx, tsy), pr * 2.8, pr * 2.8)

        # Nodes back-to-front
        order = sorted(range(len(nodes)), key=lambda i: proj[i][2])
        for i in order:
            n = nodes[i]
            sx, sy, depth = proj[i]
            flash = n.flash
            r = (n.r * scale * 0.55 + 1.6) * (0.85 + 0.25 * depth)
            r *= 1.0 + flash * 0.55
            # Halo
            hr = r * (3.5 + flash * 2.5)
            hg = QRadialGradient(QPointF(sx, sy), hr)
            ha = (40 + flash * 140) * intensity * (0.6 + 0.4 * depth)
            hg.setColorAt(0.0, QColor(180, 245, 255, _a(ha)))
            hg.setColorAt(0.45, QColor(100, 210, 235, _a(ha * 0.35)))
            hg.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hg)
            painter.drawEllipse(QPointF(sx, sy), hr, hr)
            # Core
            core_a = (120 + flash * 120) * (0.55 + 0.45 * intensity)
            if flash > 0.2:
                painter.setBrush(_q("#f0fcff", 230 * flash * intensity))
            else:
                painter.setBrush(QColor(100, 190, 220, _a(core_a)))
            painter.drawEllipse(QPointF(sx, sy), r, r)
            # Tiny hot pip when flashing
            if flash > 0.35:
                painter.setBrush(_q(C_CYAN_GLOW, 240 * flash))
                painter.drawEllipse(QPointF(sx, sy), r * 0.45, r * 0.45)

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
