# JARVIS

Local personal AI assistant: Ollama chat, session memory, safe tools, and a PyQt6 **Stark HUD** desktop window (optional voice).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# macOS: brew install ollama && brew services start ollama
ollama pull llama3.1:8b
```

## Run (desktop first)

```bash
# Primary: desktop window (Iron Man / Stark-style HUD)
python app.py

# Or double-click run.command on macOS (activates .venv if present, then app.py)
```

The window title is **JARVIS**. The header status shows **Ollama ready** when the model is available, **Thinking…** while a reply is generating, **Listening…** while you hold the mic, and **Speaking…** during TTS. A circular pulse ring on the side animates with those states. Startup fails fast if the model is missing (suggests `ollama pull …`).

### CLI (secondary)

```bash
python jarvis.py
```

The CLI also prints `JARVIS › Thinking…` before each reply, and exits if the configured model is not installed.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API base |
| `OLLAMA_MODEL` | `llama3.1:8b` | Chat model |
| `ELEVENLABS_API_KEY` | *(unset)* | Enables ElevenLabs TTS; without it, macOS `say` is used |
| `ELEVENLABS_VOICE_ID` | `onwK4e9ZLuTAKqWW03F9` (Daniel — British male) | Override voice |
| `ELEVENLABS_MODEL_ID` | `eleven_turbo_v2_5` | ElevenLabs TTS model |

### ElevenLabs voice (optional)

```bash
export ELEVENLABS_API_KEY="your_key_here"
# optional:
export ELEVENLABS_VOICE_ID="onwK4e9ZLuTAKqWW03F9"   # Daniel
export ELEVENLABS_MODEL_ID="eleven_turbo_v2_5"
python app.py
```

Do **not** commit API keys. If ElevenLabs fails for any reason, JARVIS falls back to `/usr/bin/say` on macOS and keeps the UI running.

Notes are stored under `~/.jarvis/notes/`.

## Tools

See [TOOLS.md](TOOLS.md) for the full tool list (time, notes, browser, apps, clipboard, weather, GitHub).
