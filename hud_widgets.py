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
    layer: int = 1  # 0=deep core, 1=mid, 2=cortex (parallax / brightness)


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
    width: float = 1.0


@dataclass
class _BrainGraph:
    nodes: list[_Node] = field(default_factory=list)
    edges: list[_Edge] = field(default_factory=list)


def _in_brain(x: float, y: float, z: float) -> bool:
    """Stylized two-hemisphere brain volume (unit-ish coords)."""
    ax = abs(x)
    # Main ellipsoid per hemisphere, shifted outward from midline
    hx = ax - 0.20
    cortex = (hx * hx) / (0.74 * 0.74) + (y * y) / (0.56 * 0.56) + (z * z) / (0.50 * 0.50)
    if cortex > 1.0:
        # Soft lower brainstem / cerebellum bump
        stem = (x * x) / (0.30 * 0.30) + ((y + 0.40) ** 2) / (0.34 * 0.34) + (z * z) / (0.30 * 0.30)
        if stem > 1.0:
            return False
    if y < -0.58:
        return False
    # Medial cleft except near bottom (corpus-ish bridge)
    if ax < 0.055 and y > -0.12:
        return False
    return True


def _build_brain(seed: int = 42) -> _BrainGraph:
    """Denser neural graph — finished look, still procedural."""
    rng = random.Random(seed)
    nodes: list[_Node] = []

    def _add(x: float, y: float, z: float, r: float, layer: int, min_d2: float = 0.028) -> bool:
        for n in nodes:
            dx, dy, dz = n.x - x, n.y - y, n.z - z
            if dx * dx + dy * dy + dz * dz < min_d2:
                return False
        nodes.append(_Node(x=x, y=y, z=z, r=r, layer=layer))
        return True

    # —— Dense cortex shell (surface preference) ——
    attempts = 0
    while len(nodes) < 64 and attempts < 4500:
        attempts += 1
        x = rng.uniform(-1.08, 1.08)
        y = rng.uniform(-0.72, 0.75)
        z = rng.uniform(-0.72, 0.72)
        if not _in_brain(x, y, z):
            continue
        # Push toward cortex surface for silhouette read
        nrm = math.sqrt(x * x + y * y + z * z) or 1.0
        if rng.random() < 0.72:
            push = 0.10 + rng.random() * 0.16
            x *= 1.0 + push / nrm
            y *= 1.0 + push / nrm * 0.82
            z *= 1.0 + push / nrm
        layer = 2
        r = 0.022 + rng.random() * 0.020
        _add(x, y, z, r, layer, min_d2=0.036)

    # —— Mid-depth fill (volume, not just shell) ——
    attempts = 0
    target_mid = len(nodes) + 22
    while len(nodes) < target_mid and attempts < 3500:
        attempts += 1
        x = rng.uniform(-0.85, 0.85)
        y = rng.uniform(-0.55, 0.55)
        z = rng.uniform(-0.55, 0.55)
        if not _in_brain(x * 0.95, y * 0.95, z * 0.95):
            continue
        # Keep away from surface a bit
        nrm = math.sqrt(x * x + y * y + z * z)
        if nrm > 0.78:
            continue
        _add(x, y, z, 0.016 + rng.random() * 0.014, layer=1, min_d2=0.038)

    # —— Deep core nuclei (small, dimmer later) ——
    attempts = 0
    target_core = len(nodes) + 10
    while len(nodes) < target_core and attempts < 2000:
        attempts += 1
        x = rng.uniform(-0.45, 0.45)
        y = rng.uniform(-0.35, 0.35)
        z = rng.uniform(-0.35, 0.35)
        if abs(x) < 0.08 and y > -0.05:
            continue
        if not _in_brain(x, y, z):
            continue
        _add(x, y, z, 0.012 + rng.random() * 0.010, layer=0, min_d2=0.045)

    # Guaranteed silhouette / lobe / stem anchors
    anchors = [
        (-0.58, 0.18, 0.12, 0.038, 2),
        (0.58, 0.18, 0.12, 0.038, 2),
        (-0.74, -0.02, 0.02, 0.036, 2),
        (0.74, -0.02, 0.02, 0.036, 2),
        (-0.48, 0.42, 0.18, 0.034, 2),
        (0.48, 0.42, 0.18, 0.034, 2),
        (-0.42, 0.38, -0.22, 0.030, 2),
        (0.42, 0.38, -0.22, 0.030, 2),
        (-0.28, -0.38, 0.08, 0.032, 1),
        (0.28, -0.38, 0.08, 0.032, 1),
        (0.0, -0.52, 0.0, 0.040, 1),
        (-0.18, 0.08, 0.40, 0.030, 2),
        (0.18, 0.08, 0.40, 0.030, 2),
        (-0.18, 0.08, -0.40, 0.030, 2),
        (0.18, 0.08, -0.40, 0.030, 2),
        (-0.62, 0.22, -0.18, 0.028, 2),
        (0.62, 0.22, -0.18, 0.028, 2),
        (-0.35, -0.15, 0.28, 0.026, 1),
        (0.35, -0.15, 0.28, 0.026, 1),
        (-0.12, 0.28, 0.05, 0.024, 1),
        (0.12, 0.28, 0.05, 0.024, 1),
    ]
    for ax, ay, az, ar, al in anchors:
        _add(ax, ay, az, ar, al, min_d2=0.018)

    # Micro-nodes — density glitter (tiny, mostly visual)
    attempts = 0
    micro_target = len(nodes) + 36
    while len(nodes) < micro_target and attempts < 4000:
        attempts += 1
        x = rng.uniform(-1.0, 1.0)
        y = rng.uniform(-0.68, 0.70)
        z = rng.uniform(-0.68, 0.68)
        if not _in_brain(x, y, z):
            continue
        _add(x, y, z, 0.008 + rng.random() * 0.008, layer=2 if rng.random() < 0.6 else 1, min_d2=0.014)

    # k-NN edges + commissural bridges
    edges: list[_Edge] = []
    seen: set[tuple[int, int]] = set()
    k = 3
    for i, ni in enumerate(nodes):
        # Skip pure micro glitter as edge sources (keeps FPS)
        if ni.r < 0.014:
            continue
        dists: list[tuple[float, int]] = []
        for j, nj in enumerate(nodes):
            if i == j:
                continue
            # Prefer linking to real nodes; allow some micro tips
            if nj.r < 0.014 and rng.random() > 0.25:
                continue
            dx, dy, dz = ni.x - nj.x, ni.y - nj.y, ni.z - nj.z
            dists.append((dx * dx + dy * dy + dz * dz, j))
        dists.sort()
        # Cortex gets one extra local link for density
        take = k + (1 if ni.layer >= 2 else 0)
        for _, j in dists[:take]:
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in seen:
                continue
            # Prefer same-hemisphere; allow some cross
            if nodes[a].x * nodes[b].x < 0 and abs(nodes[a].x) > 0.14 and abs(nodes[b].x) > 0.14:
                if rng.random() > 0.18:
                    continue
            # Skip very long edges (cheap look)
            if dists[0][0] > 0 and _ > 0:
                pass
            dx = nodes[a].x - nodes[b].x
            dy = nodes[a].y - nodes[b].y
            dz = nodes[a].z - nodes[b].z
            if dx * dx + dy * dy + dz * dz > 0.85:
                continue
            seen.add((a, b))
            edges.append(_Edge(a=a, b=b, curl=rng.uniform(-0.42, 0.42)))

    # Explicit corpus callosum bridges
    left = [i for i, n in enumerate(nodes) if n.x < -0.10]
    right = [i for i, n in enumerate(nodes) if n.x > 0.10]
    bridges = 0
    tries = 0
    while bridges < 10 and tries < 80 and left and right:
        tries += 1
        a = rng.choice(left)
        b = rng.choice(right)
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        if abs(nodes[a].y - nodes[b].y) > 0.32:
            continue
        if abs(nodes[a].z - nodes[b].z) > 0.40:
            continue
        seen.add(key)
        edges.append(_Edge(a=a, b=b, curl=rng.uniform(-0.18, 0.18)))
        bridges += 1

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
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._state = self.IDLE
        self._phase = 0.0
        self._yaw = 0.35  # start slightly turned so cleft reads
        self._pitch_base = 0.34
        self._pitch_sway = 0.0
        self._bob = 0.0
        self._holding = False
        self._graph = _build_brain(42)
        self._pulses: list[_Pulse] = []
        self._spawn_acc = 0.0
        self._rng = random.Random(7)
        self._lit_edges: dict[int, float] = {}  # edge → remaining axon glow

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)  # ~20 fps idle; rises when active

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _activity(self) -> tuple[float, float, float, int]:
        """Return (spawn_rate, pulse_speed, node_glow, pulse_cap) by state."""
        if self._state == self.SPEAKING:
            return 9.5, 1.65, 1.15, 48
        if self._state == self.LISTENING:
            return 3.8, 1.15, 0.88, 28
        if self._state == self.THINKING:
            return 5.5, 1.35, 0.98, 36
        return 0.65, 0.55, 0.48, 12

    def _tick(self) -> None:
        # Adaptive cadence: quieter idle, snappier when talking
        interval = 50 if self._state == self.IDLE else 33
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        dt = interval / 1000.0

        spin = {
            self.IDLE: 0.22,
            self.LISTENING: 0.32,
            self.THINKING: 0.48,
            self.SPEAKING: 0.62,
        }.get(self._state, 0.22)
        self._yaw = (self._yaw + spin * dt) % (math.pi * 2)
        self._phase = (self._phase + dt) % (math.pi * 200)
        # Stronger, smoother float — dual-frequency bob + slow pitch sway
        self._bob = (
            math.sin(self._phase * 0.65) * 0.048
            + math.sin(self._phase * 1.15 + 0.7) * 0.018
        )
        self._pitch_sway = math.sin(self._phase * 0.28) * 0.07

        spawn_rate, pulse_speed, _, pulse_cap = self._activity()
        self._spawn_acc += spawn_rate * dt
        # Speaking: occasionally burst 2–3 pulses in one tick
        burst = 1
        if self._state == self.SPEAKING and self._rng.random() < 0.35:
            burst = 2 + int(self._rng.random() > 0.55)
        while self._spawn_acc >= 1.0 and self._graph.edges:
            self._spawn_acc -= 1.0
            for _ in range(burst):
                ei = self._rng.randrange(len(self._graph.edges))
                bright = 0.78 + self._rng.random() * 0.22
                if self._state == self.SPEAKING:
                    bright = 0.92 + self._rng.random() * 0.08
                self._pulses.append(
                    _Pulse(
                        edge=ei,
                        t=0.0,
                        speed=pulse_speed * (0.80 + self._rng.random() * 0.55),
                        bright=bright,
                        width=1.0 + (0.35 if self._state == self.SPEAKING else 0.0),
                    )
                )
                e = self._graph.edges[ei]
                flash_a = 0.85 if self._state == self.SPEAKING else 0.70
                self._graph.nodes[e.a].flash = max(self._graph.nodes[e.a].flash, flash_a)
                self._graph.nodes[e.b].flash = max(self._graph.nodes[e.b].flash, flash_a * 0.75)
                self._lit_edges[ei] = max(self._lit_edges.get(ei, 0.0), 1.0)
            burst = 1  # only first spawn in the accumulator burst

        if len(self._pulses) > pulse_cap:
            self._pulses = self._pulses[-pulse_cap:]

        alive: list[_Pulse] = []
        cascades: list[_Pulse] = []
        for p in self._pulses:
            p.t += p.speed * dt * 0.92
            # Keep axon lit under traveling pulse
            self._lit_edges[p.edge] = max(self._lit_edges.get(p.edge, 0.0), 0.55 + 0.45 * (1.0 - p.t))
            if p.t < 1.0:
                alive.append(p)
                # Mid-travel node shimmer near pulse
                if 0.35 < p.t < 0.65 and self._state == self.SPEAKING:
                    e = self._graph.edges[p.edge]
                    self._graph.nodes[e.a].flash = max(self._graph.nodes[e.a].flash, 0.35)
                    self._graph.nodes[e.b].flash = max(self._graph.nodes[e.b].flash, 0.45)
            else:
                e = self._graph.edges[p.edge]
                hit = p.bright * (1.15 if self._state == self.SPEAKING else 1.0)
                self._graph.nodes[e.b].flash = max(self._graph.nodes[e.b].flash, hit)
                # Cascade spark queued separately (cap runaway)
                if self._state == self.SPEAKING and self._rng.random() < 0.32:
                    for j, ej in enumerate(self._graph.edges):
                        if j == p.edge:
                            continue
                        if ej.a == e.b or ej.b == e.b:
                            cascades.append(
                                _Pulse(
                                    edge=j,
                                    t=0.0,
                                    speed=p.speed * 0.9,
                                    bright=p.bright * 0.82,
                                    width=p.width * 0.9,
                                )
                            )
                            self._lit_edges[j] = max(self._lit_edges.get(j, 0.0), 0.8)
                            break
        # Merge cascades without exceeding cap
        for c in cascades:
            if len(alive) >= pulse_cap:
                break
            alive.append(c)
        self._pulses = alive

        # Decay node flashes + axon glow
        decay = (2.1 if self._state == self.SPEAKING else 2.8) * dt
        for n in self._graph.nodes:
            n.flash = max(0.0, n.flash - decay)
        dead = [k for k, v in self._lit_edges.items() if v <= 0.02]
        for k in list(self._lit_edges.keys()):
            self._lit_edges[k] = max(0.0, self._lit_edges[k] - 1.6 * dt)
        for k in dead:
            self._lit_edges.pop(k, None)

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

    def _project(
        self,
        x: float,
        y: float,
        z: float,
        cx: float,
        cy: float,
        scale: float,
        *,
        parallax: float = 0.0,
    ) -> tuple[float, float, float]:
        """Yaw + pitch sway → screen xy + depth weight (0 back .. 1 front)."""
        cyaw, syaw = math.cos(self._yaw), math.sin(self._yaw)
        xr = x * cyaw - z * syaw
        zr = x * syaw + z * cyaw
        yr = y + self._bob * (1.0 + parallax * 0.35)
        pitch = self._pitch_base + self._pitch_sway
        cp, sp = math.cos(pitch), math.sin(pitch)
        y2 = yr * cp - zr * sp
        z2 = yr * sp + zr * cp
        # Slight layer parallax shift
        xr += parallax * 0.04 * math.sin(self._yaw + 0.5)
        persp = 1.0 / (1.0 + z2 * 0.36)
        sx = cx + xr * scale * persp
        sy = cy + y2 * scale * persp
        depth = 0.5 + 0.5 * max(-1.0, min(1.0, z2 * 1.05))
        return sx, sy, depth

    def _axon_points(
        self, ax: float, ay: float, az: float, bx: float, by: float, bz: float, curl: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        mx = (ax + bx) * 0.5
        my = (ay + by) * 0.5
        mz = (az + bz) * 0.5
        dx, dy = bx - ax, by - ay
        length = math.sqrt(dx * dx + dy * dy) or 1.0
        px, py = -dy / length, dx / length
        lift = 0.10 + abs(curl) * 0.14
        cx_ = mx + px * curl * 0.50
        cy_ = my + py * curl * 0.50 + lift
        cz_ = mz + curl * 0.18
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
        cx, cy = w / 2.0, h / 2.0 - h * 0.015 + self._bob * min(w, h) * 0.12
        scale = min(w, h) * 0.40

        spawn_rate, _, glow_mul, _ = self._activity()
        breathe = 0.90 + 0.10 * (0.5 + 0.5 * math.sin(self._phase * 1.05))
        intensity = glow_mul * breathe
        speaking = self._state == self.SPEAKING

        painter.setPen(Qt.PenStyle.NoPen)

        # —— Soft contact shadow (float cue) ——
        shadow_y = cy + scale * 0.78
        sh = QRadialGradient(QPointF(cx, shadow_y), scale * 0.72)
        sh.setColorAt(0.0, QColor(0, 8, 18, _a(55)))
        sh.setColorAt(0.45, QColor(0, 6, 14, _a(28)))
        sh.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(sh)
        painter.drawEllipse(QPointF(cx, shadow_y), scale * 0.85, scale * 0.22)

        # —— Far parallax bloom (deeper layer, offset) ——
        far_cx = cx - scale * 0.04 * math.sin(self._yaw)
        far_cy = cy + scale * 0.02
        for bloom_r, bloom_a in (
            (scale * 1.55, 14),
            (scale * 1.15, 24),
        ):
            glow = QRadialGradient(QPointF(far_cx, far_cy), bloom_r)
            c0 = QColor(70, 160, 200)
            c0.setAlpha(_a(bloom_a * intensity * 0.75))
            c1 = QColor(40, 100, 140)
            c1.setAlpha(_a(bloom_a * 0.2 * intensity))
            glow.setColorAt(0.0, c0)
            glow.setColorAt(0.5, c1)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(far_cx, far_cy), bloom_r * 1.18, bloom_r * 0.90)

        # —— Twin hemisphere glass volumes + medial cleft ——
        hemi_sep = scale * 0.16
        for sign, hx_off in ((-1, -hemi_sep), (1, hemi_sep)):
            hx = cx + hx_off * math.cos(self._yaw * 0.35)
            hy = cy - scale * 0.06
            glass = QRadialGradient(QPointF(hx - sign * scale * 0.10, hy - scale * 0.14), scale * 0.82)
            glass.setColorAt(0.0, QColor(120, 200, 225, _a(40 * intensity)))
            glass.setColorAt(0.28, QColor(40, 95, 130, _a(72)))
            glass.setColorAt(0.58, QColor(12, 36, 55, _a(95)))
            glass.setColorAt(0.82, QColor(8, 22, 36, _a(50)))
            glass.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glass)
            # Wider than tall lobe — brain mass, not a ball
            painter.drawEllipse(QPointF(hx, hy), scale * 0.70, scale * 0.64)

        # Medial cleft shadow (reads as longitudinal fissure)
        cleft = QRadialGradient(QPointF(cx, cy - scale * 0.02), scale * 0.55)
        cleft.setColorAt(0.0, QColor(4, 12, 22, _a(70)))
        cleft.setColorAt(0.25, QColor(6, 16, 28, _a(40)))
        cleft.setColorAt(0.55, QColor(0, 0, 0, 0))
        cleft.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(cleft)
        painter.drawEllipse(QPointF(cx, cy), scale * 0.22, scale * 0.72)

        # Soft brainstem / cerebellum lower mass
        stem = QRadialGradient(QPointF(cx, cy + scale * 0.42), scale * 0.38)
        stem.setColorAt(0.0, QColor(60, 140, 175, _a(48 * intensity)))
        stem.setColorAt(0.55, QColor(20, 50, 72, _a(50)))
        stem.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(stem)
        painter.drawEllipse(QPointF(cx, cy + scale * 0.40), scale * 0.42, scale * 0.28)

        # —— Rim lighting (lit edge silhouette) ——
        rim_ang = self._yaw + 0.6
        rim_x = cx + math.cos(rim_ang) * scale * 0.55
        rim_y = cy - scale * 0.20 + math.sin(rim_ang) * scale * 0.15
        rim = QRadialGradient(QPointF(rim_x, rim_y), scale * 0.95)
        rim.setColorAt(0.0, QColor(160, 230, 250, _a(42 * intensity)))
        rim.setColorAt(0.25, QColor(90, 185, 220, _a(22 * intensity)))
        rim.setColorAt(0.55, QColor(0, 0, 0, 0))
        rim.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(rim)
        painter.drawEllipse(QPointF(cx, cy), scale * 1.05, scale * 0.82)


        # —— Soft brain silhouette (two lobes + stem) for finished volume read ——
        sil = QPainterPath()
        # Left lobe
        sil.addEllipse(QPointF(cx - scale * 0.28, cy - scale * 0.04), scale * 0.58, scale * 0.62)
        # Right lobe
        sil.addEllipse(QPointF(cx + scale * 0.28, cy - scale * 0.04), scale * 0.58, scale * 0.62)
        # Stem
        sil.addEllipse(QPointF(cx, cy + scale * 0.42), scale * 0.28, scale * 0.22)
        pen_sil = QPen(_q(C_CYAN_SOFT, 55 * intensity), 1.8)
        pen_sil.setCosmetic(True)
        painter.setPen(pen_sil)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(sil)
        # Inner cleft line
        cleft_path = QPainterPath()
        cleft_path.moveTo(cx, cy - scale * 0.48)
        cleft_path.quadTo(cx + scale * 0.02, cy - scale * 0.05, cx, cy + scale * 0.28)
        painter.setPen(QPen(QColor(4, 12, 22, _a(130)), 3.0))
        painter.drawPath(cleft_path)

        # Front bloom for presence
        near = QRadialGradient(QPointF(cx - scale * 0.05, cy - scale * 0.12), scale * 0.95)
        near.setColorAt(0.0, QColor(100, 200, 230, _a(28 * intensity)))
        near.setColorAt(0.4, QColor(45, 115, 155, _a(16 * intensity)))
        near.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(near)
        painter.drawEllipse(QPointF(cx, cy), scale * 1.08, scale * 0.84)

        nodes = self._graph.nodes
        edges = self._graph.edges

        # Project with slight layer parallax
        proj: list[tuple[float, float, float]] = []
        for n in nodes:
            par = (n.layer - 1) * 0.55  # deep back, cortex forward shift
            proj.append(self._project(n.x, n.y, n.z, cx, cy, scale, parallax=par))

        # Which edges currently carry a pulse (for bright pathway)
        pulse_on: dict[int, _Pulse] = {}
        for p in self._pulses:
            prev = pulse_on.get(p.edge)
            if prev is None or p.bright > prev.bright:
                pulse_on[p.edge] = p

        # Draw axons back-to-front
        edge_order = list(range(len(edges)))
        edge_order.sort(key=lambda i: (proj[edges[i].a][2] + proj[edges[i].b][2]) * 0.5)

        for ei in edge_order:
            e = edges[ei]
            na, nb = nodes[e.a], nodes[e.b]
            mid_d = (proj[e.a][2] + proj[e.b][2]) * 0.5
            flash = max(na.flash, nb.flash)
            lit = self._lit_edges.get(ei, 0.0)
            on_pulse = ei in pulse_on
            base_a = 38 + 70 * mid_d
            base_a += flash * 120
            base_a += lit * 130
            if on_pulse:
                base_a += 110
            base_a *= 0.55 + 0.45 * intensity
            # Depth haze: push back axons into soft occlusion
            base_a *= 0.50 + 0.50 * mid_d
            width = 1.15 + flash * 1.05 + lit * 0.85
            if on_pulse:
                width += 1.45 * pulse_on[ei].width
            if speaking and (on_pulse or lit > 0.3):
                pen = QPen(_q(C_CYAN_GLOW if on_pulse else C_CYAN, base_a), width)
            else:
                pen = QPen(_q(C_CYAN_SOFT, base_a), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sa = proj[e.a]
            sb = proj[e.b]
            if flash > 0.12 or lit > 0.15 or on_pulse:
                p0, p1, p2 = self._axon_points(na.x, na.y, na.z, nb.x, nb.y, nb.z, e.curl)
                path = QPainterPath()
                s0 = self._project(*p0, cx, cy, scale)
                path.moveTo(s0[0], s0[1])
                steps = 6 if (on_pulse or speaking) else 4
                for s in range(1, steps + 1):
                    tt = s / steps
                    bx, by, bz = self._bezier(p0, p1, p2, tt)
                    sx, sy, _ = self._project(bx, by, bz, cx, cy, scale)
                    path.lineTo(sx, sy)
                painter.drawPath(path)
            else:
                painter.drawLine(QPointF(sa[0], sa[1]), QPointF(sb[0], sb[1]))

        # —— Traveling synapse pulses (vivid core + multi-segment trail) ——
        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._pulses:
            e = edges[p.edge]
            na, nb = nodes[e.a], nodes[e.b]
            p0, p1, p2 = self._axon_points(na.x, na.y, na.z, nb.x, nb.y, nb.z, e.curl)
            trail_n = 5 if speaking else 3
            for k in range(trail_n, -1, -1):
                tt = p.t - k * (0.045 if speaking else 0.055)
                if tt < 0.0:
                    continue
                bx, by, bz = self._bezier(p0, p1, p2, tt)
                sx, sy, depth = self._project(bx, by, bz, cx, cy, scale)
                fade = 1.0 - k / (trail_n + 1.2)
                pr = (4.6 + 3.2 * p.bright) * (0.65 + 0.35 * depth) * p.width * fade
                if k == 0:
                    pr *= 1.45
                g = QRadialGradient(QPointF(sx, sy), pr * (3.4 if k == 0 else 2.4))
                if k == 0:
                    core = QColor(230, 252, 255)
                    core.setAlpha(_a(255 * p.bright * min(1.2, intensity)))
                    mid = QColor(140, 235, 255)
                    mid.setAlpha(_a(160 * p.bright * intensity))
                else:
                    core = QColor(160, 235, 255)
                    core.setAlpha(_a(140 * p.bright * intensity * fade))
                    mid = QColor(90, 200, 230)
                    mid.setAlpha(_a(70 * p.bright * intensity * fade))
                g.setColorAt(0.0, core)
                g.setColorAt(0.35, mid)
                g.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setBrush(g)
                painter.drawEllipse(QPointF(sx, sy), pr * 2.8, pr * 2.8)
            # Hot white pip at pulse head
            bx, by, bz = self._bezier(p0, p1, p2, p.t)
            sx, sy, depth = self._project(bx, by, bz, cx, cy, scale)
            pip = (2.0 + 1.2 * p.bright) * (0.7 + 0.3 * depth) * p.width
            painter.setBrush(QColor(255, 255, 255, _a(240 * p.bright)))
            painter.drawEllipse(QPointF(sx, sy), pip, pip)

        # —— Nodes back-to-front ——
        order = sorted(range(len(nodes)), key=lambda i: proj[i][2])
        for i in order:
            n = nodes[i]
            sx, sy, depth = proj[i]
            flash = n.flash
            # Layer + depth sizing / brightness
            layer_mul = 0.70 + 0.16 * n.layer
            # Aggressive z-based size: back nodes shrink, front pop
            r = (n.r * scale * 0.62 + 1.35) * (0.55 + 0.55 * depth) * layer_mul
            r *= 1.0 + flash * (0.85 if speaking else 0.50)
            # Occlusion haze for deep nodes
            occl = 0.28 + 0.72 * depth

            hr = r * (3.2 + flash * 3.0)
            hg = QRadialGradient(QPointF(sx, sy), hr)
            ha = (36 + flash * 160) * intensity * occl
            if speaking and flash > 0.4:
                ha *= 1.25
            hg.setColorAt(0.0, QColor(190, 248, 255, _a(ha)))
            hg.setColorAt(0.40, QColor(100, 210, 235, _a(ha * 0.38)))
            hg.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hg)
            painter.drawEllipse(QPointF(sx, sy), hr, hr)

            core_a = (130 + flash * 140) * (0.55 + 0.45 * intensity) * occl
            if flash > 0.18:
                painter.setBrush(_q("#f2fdff", min(255, 220 * flash * intensity + 40)))
            else:
                # Deep nodes slightly cooler / dimmer
                if n.layer == 0:
                    painter.setBrush(QColor(70, 150, 185, _a(core_a * 0.75)))
                else:
                    painter.setBrush(QColor(105, 195, 225, _a(core_a)))
            painter.drawEllipse(QPointF(sx, sy), r, r)

            # Specular kiss on front cortex nodes
            if depth > 0.55 and n.layer >= 1 and flash < 0.3:
                painter.setBrush(QColor(220, 245, 255, _a(50 * depth * intensity)))
                painter.drawEllipse(QPointF(sx - r * 0.25, sy - r * 0.28), r * 0.35, r * 0.28)

            if flash > 0.30:
                painter.setBrush(_q(C_CYAN_GLOW, 250 * flash))
                painter.drawEllipse(QPointF(sx, sy), r * 0.48, r * 0.48)
            if speaking and flash > 0.55:
                painter.setBrush(QColor(255, 255, 255, _a(200 * flash)))
                painter.drawEllipse(QPointF(sx, sy), r * 0.22, r * 0.22)

        # Soft outer haze ring (keeps field from reading as hard cutout)
        outer = QRadialGradient(QPointF(cx, cy), scale * 1.35)
        outer.setColorAt(0.0, QColor(0, 0, 0, 0))
        outer.setColorAt(0.72, QColor(0, 0, 0, 0))
        outer.setColorAt(1.0, QColor(8, 18, 28, _a(30)))
        painter.setBrush(outer)
        painter.drawEllipse(QPointF(cx, cy), scale * 1.35, scale * 1.10)

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
