#!/usr/bin/env python3
"""
JARVIS desktop app — Stark HUD PyQt6 UI, speech out (ElevenLabs / macOS `say`),
speech in (Faster-Whisper).
Run from the JARVIS folder: python app.py
"""

from __future__ import annotations

import math
import os
import sys
import threading

import httpx
import numpy as np
from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import jarvis as brain
from jarvis import ensure_model, run_turn

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore[assignment]

try:
    from voice import speak_async, transcribe_audio
except ImportError:
    speak_async = None  # type: ignore[assignment]
    transcribe_audio = None  # type: ignore[assignment]

SAMPLE_RATE = 16000

VOICE_HINT = (
    "The user may speak via microphone; reply in clear, conversational sentences. "
    "Avoid markdown, bullet lists, and code blocks unless they ask for code — "
    "your answer may be read aloud."
)

# Stark HUD palette
C_BG = "#05070c"
C_PANEL = "#0a0e18"
C_BORDER = "#1a3048"
C_CYAN = "#3de0ff"
C_CYAN_DIM = "#00d4ff"
C_TEXT = "#d8e6f0"
C_MUTED = "#6a8498"
C_USER = "#3de0ff"
C_ASSIST = "#e8f0f8"

HUD_STYLESHEET = f"""
QMainWindow {{
    background: {C_BG};
}}
QWidget#centralRoot {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
}}
QLabel#wordmark {{
    color: {C_CYAN};
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 6px;
}}
QLabel#statusLabel {{
    color: {C_MUTED};
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 11px;
    letter-spacing: 1px;
}}
QLabel#footLabel {{
    color: {C_MUTED};
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 10px;
}}
QLabel#fieldLabel {{
    color: {C_MUTED};
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 10px;
    letter-spacing: 1px;
}}
QTextEdit#chatLog {{
    background: #070b12;
    color: {C_ASSIST};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 12px;
    selection-background-color: #1a3a50;
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 12px;
}}
QLineEdit#msgInput, QLineEdit#modelInput {{
    background: #070b12;
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 18px;
    padding: 10px 16px;
    selection-background-color: #1a3a50;
    font-family: "Helvetica Neue", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QLineEdit#msgInput:focus, QLineEdit#modelInput:focus {{
    border: 1px solid {C_CYAN_DIM};
}}
QLineEdit#modelInput {{
    border-radius: 6px;
    padding: 6px 10px;
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 11px;
}}
QPushButton#sendBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00b8d4, stop:1 #3de0ff);
    color: #041018;
    font-weight: 700;
    font-family: "Helvetica Neue", "Segoe UI", sans-serif;
    font-size: 13px;
    padding: 10px 22px;
    border: 1px solid {C_CYAN};
    border-radius: 18px;
}}
QPushButton#sendBtn:hover {{
    background: #5aebff;
}}
QPushButton#sendBtn:disabled {{
    background: #1a2430;
    color: #556677;
    border-color: #2a3545;
}}
QPushButton#micBtn {{
    background: #0c1522;
    color: {C_CYAN};
    font-weight: 600;
    font-family: "Helvetica Neue", "Segoe UI", sans-serif;
    font-size: 12px;
    padding: 10px 18px;
    border: 1px solid {C_CYAN_DIM};
    border-radius: 18px;
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
    font-family: "Menlo", "SF Mono", "Consolas", monospace;
    font-size: 11px;
    spacing: 8px;
}}
QCheckBox#speakBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    background: #070b12;
}}
QCheckBox#speakBox::indicator:checked {{
    background: {C_CYAN_DIM};
    border-color: {C_CYAN};
}}
QFrame#headerBar {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {C_BORDER};
}}
QFrame#sidePanel {{
    background: #070b12;
    border: 1px solid {C_BORDER};
    border-radius: 4px;
}}
"""


class PulseRing(QWidget):
    """Concentric arcs that pulse according to JARVIS state."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 160)
        self.setMaximumSize(220, 220)
        self._state = self.IDLE
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    def set_state(self, state: str) -> None:
        self._state = state or self.IDLE
        self.update()

    def _tick(self) -> None:
        speed = {
            self.IDLE: 0.035,
            self.LISTENING: 0.12,
            self.THINKING: 0.18,
            self.SPEAKING: 0.14,
        }.get(self._state, 0.035)
        self._phase = (self._phase + speed) % (math.pi * 2)
        self.update()

    def _palette(self) -> tuple[QColor, QColor, float]:
        if self._state == self.LISTENING:
            return QColor(61, 224, 255), QColor(0, 212, 255, 180), 0.95
        if self._state == self.THINKING:
            return QColor(120, 180, 255), QColor(61, 224, 255, 200), 1.0
        if self._state == self.SPEAKING:
            return QColor(80, 255, 210), QColor(61, 224, 255, 220), 1.0
        # idle — dim slow pulse
        return QColor(40, 90, 120), QColor(0, 160, 200, 90), 0.45

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) * 0.42

        primary, secondary, intensity = self._palette()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        alpha_scale = intensity * pulse

        # Soft radial core glow
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.15)
        core = QColor(primary)
        core.setAlpha(int(40 * alpha_scale))
        glow.setColorAt(0.0, core)
        glow.setColorAt(0.55, QColor(0, 0, 0, 0))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.1, radius * 1.1)

        # Concentric arcs
        for i, (r_frac, width, spin) in enumerate(
            (
                (1.00, 2.2, 1.0),
                (0.78, 1.6, -1.4),
                (0.55, 1.4, 1.8),
            )
        ):
            pen = QPen(primary if i == 0 else secondary)
            a = int(220 * alpha_scale) if i == 0 else int(140 * alpha_scale)
            c = QColor(pen.color())
            c.setAlpha(max(30, min(255, a)))
            pen.setColor(c)
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            r = radius * r_frac
            span = 70 + 40 * math.sin(self._phase * (1.0 + i * 0.3) + i)
            start = math.degrees(self._phase * spin) + i * 40
            # Qt uses 1/16th of a degree for arc angles
            painter.drawArc(
                int(cx - r),
                int(cy - r),
                int(r * 2),
                int(r * 2),
                int(start * 16),
                int(span * 16),
            )
            # Opposite arc for HUD symmetry
            painter.drawArc(
                int(cx - r),
                int(cy - r),
                int(r * 2),
                int(r * 2),
                int((start + 180) * 16),
                int(span * 16),
            )

        # Center pip
        pip = QColor(primary)
        pip.setAlpha(int(200 * alpha_scale))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pip)
        pip_r = 3.5 + 1.5 * pulse
        painter.drawEllipse(QPointF(cx, cy), pip_r, pip_r)

        painter.end()


class JarvisWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(1000, 720)
        self.setMinimumSize(720, 520)

        self._client = httpx.Client()
        self._model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        self._messages: list[dict] = [
            {"role": "system", "content": brain.SYSTEM_PROMPT + "\n\n" + VOICE_HINT}
        ]
        self._busy = False
        self._mic_recording = False
        self._rec_stop: threading.Event | None = None
        self._rec_thread: threading.Thread | None = None
        self._rec_chunks: list[np.ndarray] = []
        self._ready_status = "Ollama ready"
        self._ring_state = PulseRing.IDLE

        root = QWidget()
        root.setObjectName("centralRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 14, 18, 14)

        # —— Header ——
        header_frame = QFrame()
        header_frame.setObjectName("headerBar")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 10)
        header.setSpacing(16)

        title = QLabel("JARVIS")
        title.setObjectName("wordmark")
        header.addWidget(title)

        self._status = QLabel("Checking Ollama…")
        self._status.setObjectName("statusLabel")
        header.addWidget(self._status, stretch=1)

        model_lbl = QLabel("MODEL")
        model_lbl.setObjectName("fieldLabel")
        header.addWidget(model_lbl)
        self._model_entry = QLineEdit(self._model)
        self._model_entry.setObjectName("modelInput")
        self._model_entry.setMinimumWidth(160)
        self._model_entry.setMaximumWidth(240)
        header.addWidget(self._model_entry)

        self._auto_speak = QCheckBox("Speak replies")
        self._auto_speak.setObjectName("speakBox")
        self._auto_speak.setChecked(True)
        if speak_async is None:
            self._auto_speak.setChecked(False)
            self._auto_speak.setEnabled(False)
        header.addWidget(self._auto_speak)
        layout.addWidget(header_frame)

        # —— Body: ring + chat ——
        body = QHBoxLayout()
        body.setSpacing(14)

        side = QFrame()
        side.setObjectName("sidePanel")
        side.setFixedWidth(200)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(12, 20, 12, 20)
        side_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._ring = PulseRing()
        side_layout.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._ring_caption = QLabel("ONLINE")
        self._ring_caption.setObjectName("fieldLabel")
        self._ring_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        side_layout.addWidget(self._ring_caption)
        side_layout.addStretch()
        body.addWidget(side)

        self._chat = QTextEdit()
        self._chat.setObjectName("chatLog")
        self._chat.setReadOnly(True)
        self._chat.setFont(QFont("Menlo", 12))
        body.addWidget(self._chat, stretch=1)
        layout.addLayout(body, stretch=1)

        # —— Input row ——
        row = QHBoxLayout()
        row.setSpacing(10)
        self._entry = QLineEdit()
        self._entry.setObjectName("msgInput")
        self._entry.setPlaceholderText("Transmit a message, or hold to speak…")
        self._entry.returnPressed.connect(self._send_text)
        row.addWidget(self._entry, stretch=1)

        self._mic_btn = QPushButton("Hold to speak")
        self._mic_btn.setObjectName("micBtn")
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.pressed.connect(self._mic_press)
        self._mic_btn.released.connect(self._mic_release)
        if sd is None or transcribe_audio is None:
            self._mic_btn.setEnabled(False)
            self._mic_btn.setText("Mic (install sounddevice + faster-whisper)")
        row.addWidget(self._mic_btn)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._send_text)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        foot = QLabel(
            f"NOTES  {brain.NOTES_DIR}  ·  CLI  python jarvis.py  ·  HUD v1"
        )
        foot.setObjectName("footLabel")
        layout.addWidget(foot)

        self.setStyleSheet(HUD_STYLESHEET)

        QTimer.singleShot(100, self._check_ollama)

    # —— Status / ring ——
    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._sync_ring_from_status(text)

    def _sync_ring_from_status(self, text: str) -> None:
        lower = text.lower()
        if "listening" in lower:
            state, caption = PulseRing.LISTENING, "LISTENING"
        elif "thinking" in lower or "transcrib" in lower or "processing" in lower:
            state, caption = PulseRing.THINKING, "THINKING"
        elif "speaking" in lower:
            state, caption = PulseRing.SPEAKING, "SPEAKING"
        elif "error" in lower or "cannot" in lower or "missing" in lower:
            state, caption = PulseRing.IDLE, "STANDBY"
        else:
            state, caption = PulseRing.IDLE, "ONLINE"
        self._ring_state = state
        self._ring.set_state(state)
        self._ring_caption.setText(caption)

    def _check_ollama(self) -> None:
        try:
            r = self._client.get(f"{brain.OLLAMA_HOST}/api/tags", timeout=5.0)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Cannot reach Ollama ({brain.OLLAMA_HOST}) — {e}")
            QMessageBox.warning(
                self,
                "JARVIS",
                "Start Ollama first:\n  brew services start ollama",
            )
            return

        try:
            ensure_model(self._client, self._model)
        except SystemExit:
            pull = f"ollama pull {self._model}"
            self._set_status(f"Model missing · {self._model}")
            QMessageBox.critical(
                self,
                "JARVIS — model not found",
                (
                    f"Model {self._model!r} is not installed in Ollama.\n\n"
                    f"Pull it with:\n  {pull}\n\n"
                    "Or set another model via OLLAMA_MODEL / the Model field."
                ),
            )
            return

        self._ready_status = "Ollama ready"
        self._set_status(self._ready_status)

    def _append_chat(self, who: str, text: str) -> None:
        if who == "You":
            html = (
                f'<p style="margin:8px 0 2px 0;">'
                f'<span style="color:{C_USER};font-weight:700;">YOU</span>'
                f'<span style="color:{C_MUTED};"> › </span>'
                f'<span style="color:{C_TEXT};">{_esc(text)}</span></p>'
            )
        elif who == "JARVIS":
            html = (
                f'<p style="margin:2px 0 10px 0;">'
                f'<span style="color:{C_CYAN_DIM};font-weight:700;">JARVIS</span>'
                f'<span style="color:{C_MUTED};"> › </span>'
                f'<span style="color:{C_ASSIST};">{_esc(text)}</span></p>'
            )
        else:
            html = f"<p>{_esc(who)}: {_esc(text)}</p>"
        self._chat.append(html)

    def _send_text(self) -> None:
        if self._busy:
            return
        text = self._entry.text().strip()
        if not text:
            return
        self._entry.clear()
        self._submit_user_message(text)

    def _submit_user_message(self, text: str) -> None:
        self._model = self._model_entry.text().strip() or self._model
        self._append_chat("You", text)
        self._busy = True
        self._send_btn.setEnabled(False)
        self._set_status("Thinking…")

        self._worker = OllamaWorker(self._client, self._model, self._messages, text, self)
        self._worker.finished_ok.connect(self._on_ollama_ok)
        self._worker.finished_err.connect(self._on_ollama_err)
        self._worker.start()

    def _on_ollama_ok(self, msgs: list, reply: str) -> None:
        self._messages = msgs
        self._busy = False
        self._send_btn.setEnabled(True)
        self._append_chat("JARVIS", reply)
        if self._auto_speak.isChecked() and speak_async:
            self._set_status("Speaking…")

            def _done() -> None:
                # Speak runs off-thread; bounce status back on the UI thread.
                QTimer.singleShot(0, lambda: self._set_status(self._ready_status))

            speak_async(reply, on_done=_done)
        else:
            self._set_status(self._ready_status)

    def _on_ollama_err(self, err: str) -> None:
        self._busy = False
        self._send_btn.setEnabled(True)
        self._append_chat("JARVIS", f"(Error: {err})")
        self._set_status("Error — see chat")

    def _mic_press(self) -> None:
        if self._busy or sd is None:
            return
        if self._mic_recording:
            return
        self._mic_recording = True
        self._rec_chunks = []
        self._rec_stop = threading.Event()

        def loop() -> None:
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype=np.float32,
                    blocksize=512,
                ) as stream:
                    while self._rec_stop and not self._rec_stop.is_set():
                        data, _overflowed = stream.read(512)
                        self._rec_chunks.append(data.copy())
            except OSError as e:
                self._set_status(f"Mic error: {e}")

        self._rec_thread = threading.Thread(target=loop, daemon=True)
        self._rec_thread.start()
        self._set_status("Listening… (release to send)")
        self._mic_btn.setText("Release to send")
        self._mic_btn.setProperty("recording", True)
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)

    def _mic_release(self) -> None:
        if not self._mic_recording or self._rec_stop is None:
            return
        self._mic_recording = False
        self._rec_stop.set()
        if self._rec_thread:
            self._rec_thread.join(timeout=2.0)
        self._mic_btn.setText("Hold to speak")
        self._mic_btn.setProperty("recording", False)
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)
        self._set_status("Processing speech…")

        if not self._rec_chunks:
            self._set_status(self._ready_status)
            return

        audio = np.concatenate(self._rec_chunks, axis=0).flatten()

        self._tw = TranscribeWorker(audio, self)
        self._tw.finished_ok.connect(self._on_transcribe_ok)
        self._tw.finished_err.connect(self._on_transcribe_err)
        self._tw.progress.connect(self._set_status)
        self._tw.start()

    def _on_transcribe_ok(self, text: str) -> None:
        if text:
            self._entry.setText(text)
            self._set_status("Ollama ready — press Send or Enter")
        else:
            self._set_status("Didn't catch that — try again")

    def _on_transcribe_err(self, err: str) -> None:
        self._set_status(self._ready_status)
        QMessageBox.critical(self, "JARVIS", err)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._client.close()
        super().closeEvent(event)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


class OllamaWorker(QThread):
    finished_ok = pyqtSignal(list, str)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        client: httpx.Client,
        model: str,
        messages: list[dict],
        user_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._model = model
        self._messages = messages
        self._user_text = user_text

    def run(self) -> None:
        try:
            self._messages.append({"role": "user", "content": self._user_text})
            msgs, reply = run_turn(self._client, self._model, self._messages)
            self.finished_ok.emit(msgs, reply)
        except Exception as e:  # noqa: BLE001
            self.finished_err.emit(str(e))


class TranscribeWorker(QThread):
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, audio: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._audio = audio

    def run(self) -> None:
        try:
            if transcribe_audio is None:
                self.finished_err.emit("Speech recognition unavailable.")
                return

            def prog(msg: str) -> None:
                self.progress.emit(msg)

            text = transcribe_audio(self._audio, SAMPLE_RATE, on_progress=prog)
            self.finished_ok.emit(text)
        except Exception as e:  # noqa: BLE001
            self.finished_err.emit(str(e))


def main() -> None:
    if sys.platform != "darwin" and not os.environ.get("ELEVENLABS_API_KEY"):
        print("Note: TTS uses ElevenLabs (set ELEVENLABS_API_KEY) or macOS `say`.")
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    win = JarvisWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
