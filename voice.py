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
# Per-request chunk size (not a hard reply cap). Full replies are spoken via
# sequential sentence-boundary chunks so the first audio starts quickly.
DEFAULT_ELEVENLABS_MAX_CHARS = 1600
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Cancel mid-utterance / mid-chunk-queue when a newer speak starts or cancel_speak().
_speak_lock = threading.Lock()
_speak_generation = 0
_active_proc: subprocess.Popen | None = None
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


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


def cancel_speak() -> None:
    """Invalidate in-flight TTS (new user turn). Safe to call from the GUI thread."""
    global _speak_generation, _active_proc
    with _speak_lock:
        _speak_generation += 1
        proc = _active_proc
        _active_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def _current_speak_gen() -> int:
    with _speak_lock:
        return _speak_generation


def _bump_speak_gen() -> int:
    global _speak_generation
    with _speak_lock:
        _speak_generation += 1
        return _speak_generation


def _truncate_at_boundary(safe: str, limit: int) -> str:
    """Hard-cap at a sentence (or word) boundary — never mid-word."""
    if len(safe) <= limit:
        return safe
    window = safe[:limit]
    # Prefer last sentence end inside the window
    best = -1
    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        idx = window.rfind(sep)
        if idx > best:
            best = idx
    if best >= max(8, limit // 6):
        return window[: best + 1].rstrip()
    # Fall back to last whitespace
    cut = window.rsplit(" ", 1)[0] or window
    return cut.rstrip(",;:")


def _truncate_for_tts(safe: str) -> str:
    """Legacy single-shot cap (sentence-boundary). Prefer _chunk_for_tts."""
    return _truncate_at_boundary(safe, _max_tts_chars())


def _chunk_for_tts(safe: str) -> list[str]:
    """Split into speakable chunks at sentence boundaries under the char budget.

    Speaks the full reply across sequential chunks (first chunk ASAP). Only
    truncates a single oversize sentence at a word/sentence boundary.
    """
    limit = _max_tts_chars()
    if not safe.strip():
        return [" "]
    if len(safe) <= limit:
        return [safe]

    sentences = _SENTENCE_SPLIT.split(safe)
    chunks: list[str] = []
    buf = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            # Oversized sentence: pack word-boundary slices
            rest = sent
            while rest:
                piece = _truncate_at_boundary(rest, limit)
                if not piece:
                    piece = rest[:limit]
                chunks.append(piece)
                rest = rest[len(piece) :].lstrip()
            continue
        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= limit:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = sent
    if buf:
        chunks.append(buf)
    return chunks or [safe[:limit]]


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


def _run_cancellable(cmd: list[str], gen: int) -> None:
    """Run a player/say subprocess that cancel_speak() / newer gen can kill."""
    global _active_proc
    if gen != _current_speak_gen():
        return
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    with _speak_lock:
        if gen != _speak_generation:
            try:
                proc.terminate()
            except OSError:
                pass
            return
        _active_proc = proc
    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
    finally:
        with _speak_lock:
            if _active_proc is proc:
                _active_proc = None


def _speak_via_say(safe: str, gen: int) -> None:
    if sys.platform != "darwin":
        return
    _run_cancellable(["/usr/bin/say", safe], gen)


def _play_audio_file(path: Path, gen: int) -> None:
    """Play a local audio file; prefer afplay on macOS. Respects speak gen cancel."""
    if sys.platform == "darwin" and Path("/usr/bin/afplay").exists():
        _run_cancellable(["/usr/bin/afplay", str(path)], gen)
        return
    for cmd in (
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["aplay", str(path)],
    ):
        try:
            _run_cancellable(cmd, gen)
            return
        except OSError:
            continue


def _speak_via_elevenlabs(safe: str, api_key: str, gen: int) -> bool:
    """POST to ElevenLabs TTS and play the result. Returns True on success."""
    import httpx

    if gen != _current_speak_gen():
        return True  # cancelled — treat as handled (no say fallback)
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
        if gen != _current_speak_gen():
            return True
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(audio)
        _play_audio_file(tmp_path, gen)
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

    Full replies are spoken via sequential sentence-boundary chunks (first chunk
    ASAP). A newer speak_async or cancel_speak() invalidates the generation so
    remaining chunks (and the active player) stop — used on a new user turn.
    Same-turn chunk continuations share one generation and are not cancelled.

    Exceptions in the TTS thread are swallowed so they cannot kill the process.
    """
    # Bump gen once for this utterance (cancels any previous speak_async).
    gen = _bump_speak_gen()

    def run() -> None:
        try:
            safe = text_for_speech(text)
            if len(safe) > 32000:
                safe = _truncate_at_boundary(safe, 32000)
            chunks = _chunk_for_tts(safe)
            api_key = _elevenlabs_api_key()
            for chunk in chunks:
                if gen != _current_speak_gen():
                    break
                used_el = False
                if api_key:
                    used_el = _speak_via_elevenlabs(chunk, api_key, gen)
                if gen != _current_speak_gen():
                    break
                if not used_el:
                    _speak_via_say(chunk, gen)
        except Exception:  # noqa: BLE001 — never let TTS kill the GUI process
            pass
        finally:
            if on_done and gen == _current_speak_gen():
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
