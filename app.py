#!/usr/bin/env python3
"""
JARVIS desktop app — voice-first soft-glow orb HUD (PyQt6).

Hold the orb (or Space) to talk; release to send. Press / for a ghost text
field. Replies prefer TTS with a fading caption — quiet circle of light.

Run from the JARVIS folder: python app.py
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import signal
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

import jarvis as brain
from jarvis import ensure_model, run_turn, warmup_model
from bridge_server import start_bridge_in_thread
from hud_widgets import (
    CaptionStack,
    HUD_STYLESHEET,
    HudRoot,
    OrbVisualizer,
    StatusChip,
    TitleBar,
)

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore[assignment]

# Always bound so _submit_user_message / closeEvent never NameError.
cancel_speak = None  # type: ignore[assignment]
speak_async = None  # type: ignore[assignment]
transcribe_audio = None  # type: ignore[assignment]
try:
    from voice import cancel_speak, speak_async, transcribe_audio
except ImportError:
    pass

SAMPLE_RATE = 16000

VOICE_HINT = (
    "Spoken path: calm, precise, dry wit; never chatty or sycophantic. Prefer one or "
    "two short sentences. No emoji, markdown, bullets, or code fences unless Jonas "
    "asks for code. Address Jonas by name when useful; occasional 'sir' is fine, not "
    "every line. Finish every sentence. Do not talk about suits, armor, Mark suits, "
    "or Stark-tech fanfic — holographic assistant, not cosplay. "
    "Never open with canned lines like 'Hello, how can I assist you?' — not at "
    "session start and never before a tool call. A bare greeting → one clipped beat "
    "('Evening.' / 'Yes?' / 'Ready.'). Mentions of Coder → ask_coder with no preamble. "
    "Screen / looking-at / help-with-this asks → see_screen first."
)

_DEBUG_LOG = Path(__file__).resolve().parent / "jarvis-debug.log"


def _debug_log(msg: str, exc: BaseException | None = None) -> None:
    """Append a line (and optional traceback) to jarvis-debug.log. Never raises."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{ts}] {msg}"]
        if exc is not None:
            lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
    except Exception:  # noqa: BLE001
        pass



def _install_crash_hooks() -> None:
    """Log uncaught exceptions and process exit; flush always."""
    try:
        # Dump native/Python fatal traces into the same debug log.
        _fh = open(_DEBUG_LOG, "a", encoding="utf-8")
        faulthandler.enable(file=_fh, all_threads=True)
    except Exception:  # noqa: BLE001
        try:
            faulthandler.enable(all_threads=True)
        except Exception:  # noqa: BLE001
            pass

    def _signal_log(signum, frame) -> None:  # noqa: ARG001
        name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        _debug_log(f"JARVIS got signal {name} ({signum})")
        if signum in (signal.SIGINT, signal.SIGTERM):
            raise SystemExit(128 + int(signum))

    for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None), getattr(signal, "SIGABRT", None)):
        if sig is None:
            continue
        try:
            # SIGABRT handler may not run if abort() is hard; still try.
            signal.signal(sig, _signal_log)
        except Exception:  # noqa: BLE001
            pass

    def _excepthook(exc_type, exc, tb) -> None:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] JARVIS uncaught exception: {exc_type.__name__}: {exc}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
                f.flush()
        except Exception:  # noqa: BLE001
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    try:
        def _thread_hook(args) -> None:  # threading.ExceptHookArgs
            try:
                _debug_log(
                    f"JARVIS thread exception in {getattr(args.thread, 'name', '?')!r}: "
                    f"{args.exc_type.__name__}: {args.exc_value}",
                    args.exc_value if isinstance(args.exc_value, BaseException) else None,
                )
            except Exception:  # noqa: BLE001
                pass

        threading.excepthook = _thread_hook  # type: ignore[attr-defined, assignment]
    except Exception:  # noqa: BLE001
        pass

    def _on_exit() -> None:
        _debug_log(f"JARVIS process exit (atexit) pid={os.getpid()}")

    atexit.register(_on_exit)


class JarvisWindow(QMainWindow):
    speak_finished = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(720, 780)
        self.setMinimumSize(520, 560)

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
        self._ready_status = "ONLINE"
        self._ring_state = OrbVisualizer.IDLE
        self._el_req_count = 0
        self._speak_gen = 0
        self._auto_speak = True  # voice-first default
        self._space_held = False

        self.speak_finished.connect(self._on_speak_finished)

        root = HudRoot()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(10, 8, 10, 12)

        self._title_bar = TitleBar()
        self._title_bar.close_requested.connect(self.close)
        self._title_bar.minimize_requested.connect(self.showMinimized)
        outer.addWidget(self._title_bar)

        # —— Orb fills the window ——
        self._orb = OrbVisualizer()
        self._orb.hold_started.connect(self._mic_press)
        self._orb.hold_ended.connect(self._mic_release)
        outer.addWidget(self._orb, stretch=1)

        # Status is silent — orb brightness/pulse only (compat shim kept off-layout)
        self._ring_caption = StatusChip()
        self._ring_caption.hide()

        self._captions = CaptionStack()
        outer.addWidget(self._captions)

        # Ghost text entry — hidden until /
        self._entry = QLineEdit()
        self._entry.setObjectName("ghostInput")
        self._entry.setPlaceholderText("")
        self._entry.returnPressed.connect(self._send_text)
        self._entry.hide()
        outer.addWidget(self._entry)

        self.setStyleSheet(HUD_STYLESHEET)

        # Keyboard: Space = hold-to-talk; / = ghost input
        self._sc_slash = QShortcut(QKeySequence("/"), self)
        self._sc_slash.activated.connect(self._show_ghost_input)
        self._sc_esc = QShortcut(QKeySequence("Escape"), self)
        self._sc_esc.activated.connect(self._hide_ghost_input)

        QTimer.singleShot(100, self._check_ollama)

    # —— Status / orb ——
    def _set_status(self, text: str) -> None:
        display = text
        lower = text.lower()
        if "listening" in lower:
            display = "LISTENING"
        elif "observ" in lower or "scanning" in lower:
            display = "OBSERVING"
        elif "synthesiz" in lower or "formulat" in lower:
            display = "FORMULATING"
        elif "contacting" in lower or "relaying" in lower:
            display = "RELAY"
        elif "thinking" in lower or "comput" in lower:
            display = "COMPUTING"
        elif "transcrib" in lower:
            display = "PROCESSING"
        elif "processing" in lower:
            display = "PROCESSING"
        elif "speaking" in lower:
            display = "SPEAKING"
        elif "ollama ready" in lower or "online" in lower:
            display = "ONLINE"
        elif "checking" in lower or "boot" in lower or "initializ" in lower:
            display = "INITIALIZING"
        elif "audio unclear" in lower or "didn't catch" in lower or "didnt catch" in lower:
            display = "AUDIO UNCLEAR"
        elif "error" in lower:
            display = "FAULT"
        elif "cannot" in lower or "missing" in lower or "unavailable" in lower:
            display = "STANDBY"
        elif text.upper().startswith("SYS"):
            display = text.split("//", 1)[-1].strip() or "STANDBY"
        self._ring_caption.setText(display)
        self._sync_orb_from_status(display)

    def _sync_orb_from_status(self, text: str) -> None:
        lower = text.lower()
        if "listening" in lower:
            state = OrbVisualizer.LISTENING
        elif any(
            k in lower
            for k in (
                "thinking",
                "comput",
                "formulat",
                "synthesiz",
                "transcrib",
                "processing",
                "boot",
                "initializ",
                "contacting",
                "relay",
            )
        ):
            state = OrbVisualizer.THINKING
        elif "speaking" in lower:
            state = OrbVisualizer.SPEAKING
        else:
            state = OrbVisualizer.IDLE
        self._ring_state = state
        self._orb.set_state(state)

    def _on_speak_finished(self, gen: int) -> None:
        if gen != self._speak_gen:
            return
        self._set_status(self._ready_status)
        self._orb.set_state(OrbVisualizer.IDLE)
        self._ring_state = OrbVisualizer.IDLE

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
                    "Or set another model via OLLAMA_MODEL."
                ),
            )
            return

        self._ready_status = "ONLINE"
        self._set_status(self._ready_status)
        model = self._model

        def _warm() -> None:
            client = None
            try:
                client = httpx.Client(timeout=120.0)
                warmup_model(client, model)
                _debug_log(f"warmup ok model={model!r}")
            except Exception as e:  # noqa: BLE001
                _debug_log(f"warmup failed model={model!r}", e)
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=_warm, daemon=True).start()

    def _show_ghost_input(self) -> None:
        self._entry.show()
        self._entry.setFocus()
        self._entry.selectAll()

    def _hide_ghost_input(self) -> None:
        self._entry.clear()
        self._entry.hide()
        self._orb.setFocus()

    def _send_text(self) -> None:
        if self._busy:
            return
        text = self._entry.text().strip()
        if not text:
            return
        self._entry.clear()
        self._entry.hide()
        self._submit_user_message(text)

    def _submit_user_message(self, text: str) -> None:
        self._speak_gen += 1
        if cancel_speak is not None:
            cancel_speak()
        self._captions.show_user(text)
        self._busy = True
        self._stream_active = False
        self._stream_buf = ""
        self._set_status("COMPUTING")

        self._worker = OllamaWorker(self._model, list(self._messages), text, self)
        self._worker.token.connect(self._on_ollama_token)
        self._worker.finished_ok.connect(self._on_ollama_ok)
        self._worker.finished_err.connect(self._on_ollama_err)
        self._worker.start()

    def _on_ollama_token(self, delta: str) -> None:
        if not delta:
            return
        if not self._stream_active:
            self._stream_active = True
            self._stream_buf = ""
            low = delta.lower()
            if "contacting coder" in low:
                self._set_status("RELAY")
            elif "observ" in low or "scanning" in low:
                self._set_status("OBSERVING")
            else:
                self._set_status("FORMULATING")
        self._stream_buf += delta

    def _on_ollama_ok(self, msgs: list, reply: str) -> None:
        self._messages = msgs
        self._busy = False
        self._stream_active = False
        self._stream_buf = ""
        self._captions.show_reply(reply or "")
        if self._auto_speak and speak_async:
            self._speak_gen += 1
            gen = self._speak_gen
            self._set_status("SPEAKING")
            self._el_req_count += 1

            def _done() -> None:
                self.speak_finished.emit(gen)

            speak_async(reply, on_done=_done)
        else:
            self._set_status(self._ready_status)
            self._orb.set_state(OrbVisualizer.IDLE)

    def _on_ollama_err(self, err: str) -> None:
        self._busy = False
        self._stream_active = False
        self._stream_buf = ""
        self._captions.show_reply(f"Fault: {err}")
        self._set_status("FAULT")

    # —— Mic / hold-to-talk ——
    def _mic_press(self) -> None:
        if self._busy or sd is None:
            return
        if self._mic_recording:
            return
        if transcribe_audio is None:
            self._set_status("Mic unavailable")
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
        self._set_status("LISTENING")

    def _mic_release(self) -> None:
        if not self._mic_recording or self._rec_stop is None:
            return
        self._mic_recording = False
        self._rec_stop.set()
        if self._rec_thread:
            self._rec_thread.join(timeout=2.0)
        self._set_status("PROCESSING")

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
            self._submit_user_message(text)
        else:
            self._set_status("AUDIO UNCLEAR")
            QTimer.singleShot(1800, lambda: self._set_status(self._ready_status))

    def _on_transcribe_err(self, err: str) -> None:
        self._set_status(self._ready_status)
        QMessageBox.critical(self, "JARVIS", err)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if (
            event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and not self._entry.isVisible()
        ):
            self._space_held = True
            self._mic_press()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and self._space_held:
            self._space_held = False
            self._mic_release()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        _debug_log("JARVIS closeEvent (window closing)")
        self._speak_gen += 1
        if cancel_speak is not None:
            cancel_speak()
        try:
            self._client.close()
        except Exception as e:  # noqa: BLE001
            _debug_log("JARVIS client.close failed", e)
        super().closeEvent(event)


class OllamaWorker(QThread):
    finished_ok = pyqtSignal(list, str)
    finished_err = pyqtSignal(str)
    token = pyqtSignal(str)

    def __init__(
        self,
        model: str,
        messages: list[dict],
        user_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._messages = list(messages)
        self._user_text = user_text

    def run(self) -> None:
        client: httpx.Client | None = None
        try:
            client = httpx.Client(timeout=180.0)
            messages = list(self._messages)
            messages.append({"role": "user", "content": self._user_text})

            def _on_token(delta: str) -> None:
                if delta:
                    self.token.emit(delta)

            msgs, reply = run_turn(
                client, self._model, messages, on_token=_on_token
            )
            self.finished_ok.emit(msgs, reply or "")
        except Exception as e:  # noqa: BLE001
            _debug_log("OllamaWorker.run failed", e)
            self.finished_err.emit(f"{type(e).__name__}: {e}")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass


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
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    _install_crash_hooks()
    _debug_log(
        f"JARVIS starting pid={os.getpid()} platform={sys.platform} "
        f"python={sys.version.split()[0]} log={_DEBUG_LOG}"
    )
    # Localhost HTTP bridge for Coder / CLI clients (JARVIS_BRIDGE=0 to disable).
    start_bridge_in_thread(
        model=os.environ.get("OLLAMA_MODEL"),
        log=lambda msg, exc=None: _debug_log(msg, exc),
    )
    if sys.platform != "darwin" and not os.environ.get("ELEVENLABS_API_KEY"):
        print("Note: TTS uses ElevenLabs (set ELEVENLABS_API_KEY) or macOS `say`.")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    code = 1
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("JARVIS")
        app.setStyle("Fusion")
        # Avoid accidental Esc quitting the app on some platforms; our shortcut
        # only hides the ghost input. Do not bind Esc to QApplication.quit.
        win = JarvisWindow()
        win.show()
        _debug_log("JARVIS window shown; entering event loop")
        code = app.exec()
        _debug_log(f"JARVIS event loop exited code={code}")
    except Exception as e:  # noqa: BLE001
        _debug_log("JARVIS main() crashed", e)
        raise
    finally:
        _debug_log(f"JARVIS main() leaving with code={code}")
    sys.exit(code)


if __name__ == "__main__":
    main()
