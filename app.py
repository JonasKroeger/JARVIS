#!/usr/bin/env python3
"""
JARVIS desktop app — PyQt6 UI, speech out (macOS `say`), speech in (Faster-Whisper).
Run from the `jarvis/` folder: python app.py
"""

from __future__ import annotations

import os
import sys
import threading

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
from jarvis import run_turn

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


class JarvisWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(920, 680)
        self.setMinimumSize(640, 480)

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

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QHBoxLayout()
        title = QLabel("JARVIS")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        header.addWidget(title)

        header.addSpacing(24)
        header.addWidget(QLabel("Model"))
        self._model_entry = QLineEdit(self._model)
        self._model_entry.setMinimumWidth(200)
        self._model_entry.setFont(QFont("Menlo", 11))
        header.addWidget(self._model_entry)

        header.addStretch()
        self._auto_speak = QCheckBox("Speak replies")
        self._auto_speak.setChecked(True)
        if speak_async is None:
            self._auto_speak.setChecked(False)
            self._auto_speak.setEnabled(False)
        header.addWidget(self._auto_speak)
        layout.addLayout(header)

        self._status = QLabel("Checking Ollama…")
        self._status.setStyleSheet("color: #8b92a8;")
        layout.addWidget(self._status)

        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setFont(QFont("Helvetica Neue", 13))
        self._chat.setStyleSheet(
            """
            QTextEdit {
                background: #12151c;
                color: #e6e9ef;
                border: 1px solid #2a3142;
                border-radius: 6px;
                padding: 10px;
            }
            """
        )
        layout.addWidget(self._chat, stretch=1)

        row = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Type a message, or hold “Hold to speak”…")
        self._entry.setFont(QFont("Helvetica Neue", 13))
        self._entry.returnPressed.connect(self._send_text)
        self._entry.setStyleSheet(
            """
            QLineEdit {
                background: #161922;
                color: #e6e9ef;
                border: 1px solid #2a3142;
                border-radius: 6px;
                padding: 10px;
            }
            """
        )
        row.addWidget(self._entry, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._send_text)
        self._send_btn.setStyleSheet(
            """
            QPushButton {
                background: #3d8bfd;
                color: white;
                font-weight: bold;
                padding: 10px 18px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #2563eb; }
            QPushButton:disabled { background: #444; color: #888; }
            """
        )
        row.addWidget(self._send_btn)

        self._mic_btn = QPushButton("Hold to speak")
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.pressed.connect(self._mic_press)
        self._mic_btn.released.connect(self._mic_release)
        self._mic_btn.setStyleSheet(
            """
            QPushButton {
                background: #1e2430;
                color: #e6e9ef;
                padding: 10px 14px;
                border: 1px solid #2a3142;
                border-radius: 6px;
            }
            QPushButton:hover { background: #2a3142; }
            QPushButton:disabled { background: #111; color: #555; }
            """
        )
        if sd is None or transcribe_audio is None:
            self._mic_btn.setEnabled(False)
            self._mic_btn.setText("Mic (install sounddevice + faster-whisper)")
        row.addWidget(self._mic_btn)
        layout.addLayout(row)

        foot = QLabel(f"Notes: {brain.NOTES_DIR}")
        foot.setFont(QFont("Menlo", 10))
        foot.setStyleSheet("color: #8b92a8;")
        layout.addWidget(foot)

        self.setStyleSheet("QMainWindow { background: #0c0e14; } QWidget { background: #0c0e14; color: #e6e9ef; }")

        QTimer.singleShot(100, self._check_ollama)

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _check_ollama(self) -> None:
        try:
            r = self._client.get(f"{brain.OLLAMA_HOST}/api/tags", timeout=5.0)
            r.raise_for_status()
            self._set_status(f"Ollama ready · {brain.OLLAMA_HOST}")
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Cannot reach Ollama ({brain.OLLAMA_HOST}) — {e}")
            QMessageBox.warning(
                self,
                "JARVIS",
                "Start Ollama first:\n  brew services start ollama",
            )

    def _append_chat(self, who: str, text: str) -> None:
        self._chat.append(f"{who}: {text}")

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
        self._set_status(f"Ready · {self._model}")
        if self._auto_speak.isChecked() and speak_async:
            speak_async(reply)

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
        self._mic_btn.setStyleSheet(
            self._mic_btn.styleSheet()
            + "QPushButton { background: #2d4a2d; border-color: #3d6a3d; }"
        )

    def _mic_release(self) -> None:
        if not self._mic_recording or self._rec_stop is None:
            return
        self._mic_recording = False
        self._rec_stop.set()
        if self._rec_thread:
            self._rec_thread.join(timeout=2.0)
        self._mic_btn.setText("Hold to speak")
        self._mic_btn.setStyleSheet(
            """
            QPushButton {
                background: #1e2430;
                color: #e6e9ef;
                padding: 10px 14px;
                border: 1px solid #2a3142;
                border-radius: 6px;
            }
            QPushButton:hover { background: #2a3142; }
            """
        )
        self._set_status("Processing speech…")

        if not self._rec_chunks:
            self._set_status("Ready")
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
            self._set_status("Ready — press Send or Enter")
        else:
            self._set_status("Didn't catch that — try again")

    def _on_transcribe_err(self, err: str) -> None:
        self._set_status("Ready")
        QMessageBox.critical(self, "JARVIS", err)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._client.close()
        super().closeEvent(event)


def main() -> None:
    if sys.platform != "darwin":
        print("Note: TTS uses macOS `say`.")
    app = QApplication(sys.argv)
    win = JarvisWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
