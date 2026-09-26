# JARVIS

Local personal AI assistant: Ollama chat, session memory, safe tools, optional PyQt6 UI + voice.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# macOS: brew install ollama && ollama pull llama3.1:8b
```

## Run

```bash
# CLI
python jarvis.py

# GUI (PyQt6)
python app.py

# Or double-click run.command on macOS
```

Env vars: `OLLAMA_HOST` (default `http://127.0.0.1:11434`), `OLLAMA_MODEL` (default `llama3.1:8b`).

Notes are stored under `~/.jarvis/notes/`.

## Tools

See [TOOLS.md](TOOLS.md) for the full tool list (time, notes, browser, apps, clipboard, weather, GitHub).
