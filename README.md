# JARVIS

Local personal AI assistant: Ollama chat, session memory, safe tools, and a PyQt6 **Stark HUD** desktop window (optional voice).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# macOS: brew install ollama && brew services start ollama
ollama pull llama3.1:8b
# Faster alternative (recommended for snappier replies):
# ollama pull llama3.2
```

## Run (desktop first)

```bash
# Primary: desktop window (Iron Man / Stark-style HUD)
python app.py

# Or double-click run.command on macOS (activates .venv if present, then app.py)
```

The window is a frameless **cinematic HUD** (default ~1180×740). Status strip uses `SYS // OLLAMA READY`, `SYS // SYNTHESIZING` (waiting on Ollama), `SYS // SPEAKING` (TTS playing), `SYS // LISTENING`. Left side is a multi-layer pulse/radar; right side stacks transcript + transmit bar. Telemetry shows `EL REQ // N` whenever TTS/`speak_async` is invoked. Startup fails fast if the model is missing (suggests `ollama pull …`).

Short greetings/chitchat (≤40 chars) and short personal-fact questions (name, home, preferences, “what do you know about me”) skip the tools schema for a faster single Ollama round-trip (memory is still injected); real asks still get tools. Lean calls use `keep_alive=30m` and a lower `num_predict`.

### CLI (secondary)

```bash
python jarvis.py
```

The CLI also prints `JARVIS › Thinking…` before each reply, and exits if the configured model is not installed.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API base |
| `OLLAMA_MODEL` | `llama3.1:8b` | Chat model (`llama3.2` is faster if you prefer) |
| `ELEVENLABS_API_KEY` | *(unset)* | Enables ElevenLabs TTS; without it, macOS `say` is used |
| `ELEVENLABS_VOICE_ID` | `onwK4e9ZLuTAKqWW03F9` (Daniel — British male) | Override voice |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | ElevenLabs TTS model (flash = lower latency; override if needed) |
| `ELEVENLABS_MAX_CHARS` | `400` | Max chars sent to TTS (full reply still shown in chat) |

### ElevenLabs voice (optional)

```bash
export ELEVENLABS_API_KEY="your_key_here"
# optional:
export ELEVENLABS_VOICE_ID="onwK4e9ZLuTAKqWW03F9"   # Daniel
export ELEVENLABS_MODEL_ID="eleven_flash_v2_5"       # or eleven_turbo_v2_5
export ELEVENLABS_MAX_CHARS=400
python app.py
```

Do **not** commit API keys. If ElevenLabs fails for any reason, JARVIS falls back to `/usr/bin/say` on macOS and keeps the UI running.

Notes are stored under `~/.jarvis/notes/`.

Long-term memory (preferences, people, projects, routines) lives in `~/.jarvis/memory.json` and is injected into each turn so JARVIS can greet you by name and recall facts across sessions. Say *Remember that I work in Helsinki*, *What do you know about me?*, or *Forget that*.

## Tools

See [TOOLS.md](TOOLS.md) for the full tool list (time, notes, browser, apps, clipboard, weather, GitHub, system status, notify, reminders, music, screenshot, running apps, read_file, web search, plus premium: calendar, volume, timers, fetch_url, stocks, dark mode, **daily_briefing**, and durable **memory** tools).

Say *good morning*, *brief me*, or *status report* to get the Iron Man-style `daily_briefing` composite.

JARVIS also auto-loads `ELEVENLABS_*` from `~/JARVIS/.env` or `~/.jarvis/.env` if those files exist.
