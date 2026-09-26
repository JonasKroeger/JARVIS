#!/usr/bin/env python3
"""
JARVIS desktop app — cinematic Stark HUD (PyQt6), speech out (ElevenLabs /
macOS `say`), speech in (Faster-Whisper).

Run from the JARVIS folder: python app.py
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime

import httpx
import numpy as np
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
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
from hud_widgets import (
    C_ASSIST,
    C_CYAN,
    C_CYAN_DIM,
    C_MUTED,
    C_USER,
    ChatStack,
    HUD_STYLESHEET,
    HoloPanel,
    HudRoot,
    PulseRing,
    StatusStrip,
    TitleBar,
)

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


class JarvisWindow(QMainWindow):
    # Thread-safe bridge: TTS background thread → GUI slot (never create QTimers off-thread)
    speak_finished = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)

        # Frameless cinematic chrome (no translucent bg — stable on macOS)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._client = httpx.Client()
        self._model = os.environ.get("OLLAMA_MODEL", brain.DEFAULT_OLLAMA_MODEL)
        self._messages: list[dict] = [
            {"role": "system", "content": brain.SYSTEM_PROMPT + "\n\n" + VOICE_HINT}
        ]
        self._busy = False
        self._mic_recording = False
        self._rec_stop: threading.Event | None = None
        self._rec_thread: threading.Thread | None = None
        self._rec_chunks: list[np.ndarray] = []
        self._ready_status = "SYS // OLLAMA READY"
        self._ring_state = PulseRing.IDLE
        self._el_req_count = 0
        self._speak_gen = 0  # invalidate stale speak_finished when a new turn starts

        self.speak_finished.connect(self._on_speak_finished)

        root = HudRoot()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(16, 14, 16, 14)

        # —— Custom title bar ——
        self._title_bar = TitleBar()
        self._title_bar.close_requested.connect(self.close)
        self._title_bar.minimize_requested.connect(self.showMinimized)
        outer.addWidget(self._title_bar)

        content = QVBoxLayout()
        content.setSpacing(10)
        content.setContentsMargins(8, 10, 8, 4)
        outer.addLayout(content, stretch=1)

        # —— Body: left radar | right HUD stack ——
        body = QHBoxLayout()
        body.setSpacing(16)

        # Left: cinematic pulse / radar
        left = QVBoxLayout()
        left.setSpacing(8)
        left.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._ring = PulseRing()
        left.addWidget(self._ring, stretch=1)

        self._ring_caption = QLabel("ONLINE")
        self._ring_caption.setObjectName("ringCaption")
        self._ring_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(self._ring_caption)

        left_wrap = QWidget()
        left_wrap.setMinimumWidth(300)
        left_wrap.setMaximumWidth(380)
        left_wrap.setLayout(left)
        body.addWidget(left_wrap)

        # Right: status + transcript + transmit
        right = QVBoxLayout()
        right.setSpacing(8)

        # Status strip + telemetry
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self._status = StatusStrip()
        self._status.setText("SYS // CHECKING OLLAMA…")
        status_row.addWidget(self._status, stretch=1)

        self._el_label = QLabel("EL REQ // 0")
        self._el_label.setObjectName("telemetryBit")
        self._el_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        status_row.addWidget(self._el_label)
        right.addLayout(status_row)

        # Transcript holo panel
        chat_panel = HoloPanel(scanlines=True)
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(2, 2, 2, 2)
        chat_layout.setSpacing(0)

        chat_hdr = QLabel("  TRANSCRIPT  //  SESSION")
        chat_hdr.setObjectName("fieldLabel")
        chat_hdr.setFixedHeight(22)
        chat_layout.addWidget(chat_hdr)

        self._chat = QTextEdit()
        self._chat.setObjectName("chatLog")
        self._chat.setReadOnly(True)
        self._chat.setFont(QFont("Menlo", 12))
        self._chat.setFrameStyle(0)
        self._chat_stack = ChatStack(self._chat)
        chat_layout.addWidget(self._chat_stack, stretch=1)
        right.addWidget(chat_panel, stretch=1)

        # Compact telemetry: model + speak
        telem = QHBoxLayout()
        telem.setSpacing(10)
        model_lbl = QLabel("MODEL")
        model_lbl.setObjectName("fieldLabel")
        telem.addWidget(model_lbl)
        self._model_entry = QLineEdit(self._model)
        self._model_entry.setObjectName("modelInput")
        self._model_entry.setPlaceholderText("e.g. llama3.2")
        self._model_entry.setMinimumWidth(120)
        self._model_entry.setMaximumWidth(180)
        telem.addWidget(self._model_entry)

        self._auto_speak = QCheckBox("SPEAK")
        self._auto_speak.setObjectName("speakBox")
        self._auto_speak.setChecked(True)
        if speak_async is None:
            self._auto_speak.setChecked(False)
            self._auto_speak.setEnabled(False)
        telem.addWidget(self._auto_speak)
        telem.addStretch(1)
        right.addLayout(telem)

        # Transmit bar
        tx_panel = HoloPanel(scanlines=False)
        tx_layout = QHBoxLayout(tx_panel)
        tx_layout.setContentsMargins(4, 6, 6, 6)
        tx_layout.setSpacing(8)

        chevron = QLabel("›")
        chevron.setObjectName("chevron")
        tx_layout.addWidget(chevron)

        self._entry = QLineEdit()
        self._entry.setObjectName("msgInput")
        self._entry.setPlaceholderText("Transmit a message…")
        self._entry.returnPressed.connect(self._send_text)
        tx_layout.addWidget(self._entry, stretch=1)

        self._mic_btn = QPushButton("●")
        self._mic_btn.setObjectName("micBtn")
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.setToolTip("Hold to speak")
        self._mic_btn.pressed.connect(self._mic_press)
        self._mic_btn.released.connect(self._mic_release)
        if sd is None or transcribe_audio is None:
            self._mic_btn.setEnabled(False)
            self._mic_btn.setToolTip("Mic unavailable — install sounddevice + faster-whisper")
            self._mic_btn.setText("×")
        tx_layout.addWidget(self._mic_btn)

        self._send_btn = QPushButton("TRANSMIT")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._send_text)
        tx_layout.addWidget(self._send_btn)

        right.addWidget(tx_panel)
        body.addLayout(right, stretch=1)
        content.addLayout(body, stretch=1)

        foot = QLabel(
            f"NOTES  {brain.NOTES_DIR}  ·  CLI  python jarvis.py  ·  HUD v3"
        )
        foot.setObjectName("footLabel")
        content.addWidget(foot)

        self.setStyleSheet(HUD_STYLESHEET)

        QTimer.singleShot(100, self._check_ollama)

    # —— Status / ring ——
    def _set_status(self, text: str) -> None:
        # Normalize plain phrases into SYS // HUD format when callers pass legacy text
        display = text
        lower = text.lower()
        if not text.upper().startswith("SYS"):
            if "listening" in lower:
                display = "SYS // LISTENING"
            elif "synthesiz" in lower:
                display = "SYS // SYNTHESIZING"
            elif "thinking" in lower:
                display = "SYS // THINKING"
            elif "transcrib" in lower:
                display = "SYS // TRANSCRIBING"
            elif "processing" in lower:
                display = "SYS // PROCESSING"
            elif "speaking" in lower:
                display = "SYS // SPEAKING"
            elif "ollama ready" in lower:
                display = "SYS // OLLAMA READY"
            elif "checking" in lower:
                display = "SYS // CHECKING OLLAMA…"
            elif "error" in lower:
                display = f"SYS // ERROR — {text}"
            elif "cannot" in lower or "missing" in lower:
                display = f"SYS // {text.upper()}"
            else:
                display = f"SYS // {text.upper()}" if text else "SYS // STANDBY"
        self._status.setText(display)
        self._sync_ring_from_status(display)

    def _sync_ring_from_status(self, text: str) -> None:
        lower = text.lower()
        if "listening" in lower:
            state, caption = PulseRing.LISTENING, "LISTENING"
        elif (
            "thinking" in lower
            or "synthesiz" in lower
            or "transcrib" in lower
            or "processing" in lower
        ):
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

    def _on_speak_finished(self, gen: int) -> None:
        """GUI-thread slot: reset status + ring after TTS (ignore stale gens)."""
        if gen != self._speak_gen:
            return
        self._set_status(self._ready_status)
        self._ring.set_state(PulseRing.IDLE)
        self._ring_caption.setText("ONLINE")
        self._ring_state = PulseRing.IDLE

    def _bump_el_req(self) -> None:
        self._el_req_count += 1
        self._el_label.setText(f"EL REQ // {self._el_req_count}")

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

        self._ready_status = "SYS // OLLAMA READY"
        self._set_status(self._ready_status)

    def _append_chat(self, who: str, text: str) -> None:
        self._chat_stack.set_empty(False)
        ts = datetime.now().strftime("%H:%M")
        ts_html = (
            f'<span style="color:{C_MUTED};font-size:10px;'
            f'letter-spacing:1px;">{ts}</span>'
        )
        if who == "You":
            html = (
                f'<p style="margin:10px 0 2px 0;line-height:1.45;">'
                f"{ts_html}"
                f'<span style="color:{C_MUTED};">  </span>'
                f'<span style="color:{C_USER};font-size:10px;font-weight:600;'
                f'letter-spacing:2px;">YOU</span>'
                f'<br><span style="color:{C_CYAN};">{_esc(text)}</span></p>'
            )
        elif who == "JARVIS":
            html = (
                f'<p style="margin:4px 0 12px 0;line-height:1.45;">'
                f"{ts_html}"
                f'<span style="color:{C_MUTED};">  </span>'
                f'<span style="color:{C_CYAN_DIM};font-size:10px;font-weight:600;'
                f'letter-spacing:2px;">JARVIS</span>'
                f'<br><span style="color:{C_ASSIST};">{_esc(text)}</span></p>'
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
        # Invalidate any in-flight speak_finished from a previous turn
        self._speak_gen += 1
        self._model = self._model_entry.text().strip() or self._model
        self._append_chat("You", text)
        self._busy = True
        self._send_btn.setEnabled(False)
        self._entry.setEnabled(False)
        self._set_status("SYS // SYNTHESIZING")

        self._worker = OllamaWorker(self._client, self._model, self._messages, text, self)
        self._worker.finished_ok.connect(self._on_ollama_ok)
        self._worker.finished_err.connect(self._on_ollama_err)
        self._worker.start()

    def _on_ollama_ok(self, msgs: list, reply: str) -> None:
        self._messages = msgs
        self._busy = False
        self._send_btn.setEnabled(True)
        self._entry.setEnabled(True)
        # Show text immediately — never block UI on TTS
        self._append_chat("JARVIS", reply)
        if self._auto_speak.isChecked() and speak_async:
            self._speak_gen += 1
            gen = self._speak_gen
            self._set_status("SYS // SPEAKING")
            self._bump_el_req()

            def _done() -> None:
                # Background thread: only emit (thread-safe). Never create QTimers here.
                self.speak_finished.emit(gen)

            speak_async(reply, on_done=_done)
        else:
            self._set_status(self._ready_status)
            self._ring.set_state(PulseRing.IDLE)

    def _on_ollama_err(self, err: str) -> None:
        self._busy = False
        self._send_btn.setEnabled(True)
        self._entry.setEnabled(True)
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
        self._mic_btn.setText("◉")
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
        self._mic_btn.setText("●")
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
            self._set_status("Ollama ready — press TRANSMIT or Enter")
        else:
            self._set_status("Didn't catch that — try again")

    def _on_transcribe_err(self, err: str) -> None:
        self._set_status(self._ready_status)
        QMessageBox.critical(self, "JARVIS", err)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._speak_gen += 1  # ignore late TTS callbacks
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
    # High-DPI awareness for crisp HUD painting
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setStyle("Fusion")  # avoid native grey chrome leaking through
    win = JarvisWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
