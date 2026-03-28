"""macOS TTS (say) + local Faster-Whisper STT."""

from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

# Lazy singleton
_whisper_model = None
_whisper_lock = threading.Lock()


def text_for_speech(text: str) -> str:
    """Strip markdown-ish noise so `say` sounds natural."""
    t = text.strip()
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"#+\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip() or " "


def speak_async(text: str, on_done: Callable[[], None] | None = None) -> None:
    """Speak in a background thread (non-blocking UI)."""

    def run() -> None:
        safe = text_for_speech(text)
        if len(safe) > 32000:
            safe = safe[:32000] + "…"
        try:
            subprocess.run(
                ["/usr/bin/say", safe],
                check=False,
                capture_output=True,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if on_done:
            on_done()

    threading.Thread(target=run, daemon=True).start()


def _get_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            from faster_whisper import WhisperModel

            # int8 + CPU is reliable on Apple Silicon; first run downloads weights
            _whisper_model = WhisperModel(
                "base",
                device="cpu",
                compute_type="int8",
            )
        return _whisper_model


def _write_wav_mono(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    s = np.clip(samples.astype(np.float64).flatten(), -1.0, 1.0)
    s16 = (s * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(s16.tobytes())


def transcribe_audio(
    samples: np.ndarray,
    sample_rate: int,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Float32 mono samples, typically 16 kHz."""
    if samples.size < sample_rate * 0.25:
        return ""

    if on_progress:
        on_progress("Transcribing…")

    model = _get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        _write_wav_mono(path, samples, sample_rate)
        segments, _info = model.transcribe(
            str(path),
            language=None,
            vad_filter=True,
            beam_size=5,
        )
        parts = [s.text for s in segments]
        return " ".join(p.strip() for p in parts if p.strip()).strip()
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
