"""TTS (ElevenLabs primary, macOS `say` fallback) + local Faster-Whisper STT."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

# Lazy singleton
_whisper_model = None
_whisper_lock = threading.Lock()

# ElevenLabs defaults — Daniel (authoritative British male). Override via env.
# Flash model for lower latency; override with ELEVENLABS_MODEL_ID if needed.
DEFAULT_ELEVENLABS_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_flash_v2_5"
DEFAULT_ELEVENLABS_MAX_CHARS = 400
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def text_for_speech(text: str) -> str:
    """Strip markdown-ish noise so TTS sounds natural."""
    t = text.strip()
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"#+\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip() or " "


def _max_tts_chars() -> int:
    raw = os.environ.get("ELEVENLABS_MAX_CHARS", "").strip()
    if raw.isdigit():
        return max(40, int(raw))
    return DEFAULT_ELEVENLABS_MAX_CHARS


def _truncate_for_tts(safe: str) -> str:
    """Keep spoken audio short so TTS starts sooner; full text stays in chat."""
    limit = _max_tts_chars()
    if len(safe) <= limit:
        return safe
    cut = safe[:limit].rsplit(" ", 1)[0] or safe[:limit]
    return cut.rstrip(",.;:") + "…"


def _load_env_files() -> None:
    """Load KEY=VALUE from ~/.jarvis/.env and project .env without overriding existing env."""
    candidates = [
        Path.home() / ".jarvis" / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            continue


_load_env_files()


def _elevenlabs_api_key() -> str | None:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    return key or None


def _speak_via_say(safe: str) -> None:
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["/usr/bin/say", safe],
            check=False,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _play_audio_file(path: Path) -> None:
    """Play a local audio file; prefer afplay on macOS."""
    if sys.platform == "darwin" and Path("/usr/bin/afplay").exists():
        subprocess.run(
            ["/usr/bin/afplay", str(path)],
            check=False,
            capture_output=True,
            timeout=600,
        )
        return
    # Best-effort fallback: try ffplay / aplay if present
    for cmd in (
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["aplay", str(path)],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=600)
            return
        except (OSError, subprocess.TimeoutExpired):
            continue


def _speak_via_elevenlabs(safe: str, api_key: str) -> bool:
    """POST to ElevenLabs TTS and play the result. Returns True on success."""
    import httpx

    voice_id = (
        os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
        or DEFAULT_ELEVENLABS_VOICE_ID
    )
    model_id = (
        os.environ.get("ELEVENLABS_MODEL_ID", "").strip()
        or DEFAULT_ELEVENLABS_MODEL_ID
    )
    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": safe,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
        },
    }
    tmp_path: Path | None = None
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio = resp.content
        if not audio:
            return False
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(audio)
        _play_audio_file(tmp_path)
        return True
    except Exception:  # noqa: BLE001 — any EL failure → caller falls back to say
        return False
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def speak_async(text: str, on_done: Callable[[], None] | None = None) -> None:
    """Speak in a background thread (non-blocking UI).

    Uses ElevenLabs when ELEVENLABS_API_KEY is set; otherwise (or on any
    ElevenLabs failure) falls back to macOS `/usr/bin/say`.
    Spoken text is truncated (~ELEVENLABS_MAX_CHARS) so synthesis starts sooner;
    the full reply remains in the chat UI.

    Exceptions in the TTS thread are swallowed so they cannot kill the process.
    """

    def run() -> None:
        try:
            safe = _truncate_for_tts(text_for_speech(text))
            if len(safe) > 32000:
                safe = safe[:32000] + "…"
            api_key = _elevenlabs_api_key()
            used_el = False
            if api_key:
                used_el = _speak_via_elevenlabs(safe, api_key)
            if not used_el:
                _speak_via_say(safe)
        except Exception:  # noqa: BLE001 — never let TTS kill the GUI process
            pass
        finally:
            if on_done:
                try:
                    on_done()
                except Exception:  # noqa: BLE001
                    pass

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
