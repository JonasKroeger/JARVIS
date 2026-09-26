# JARVIS

Local personal AI assistant: Ollama chat, session memory, safe tools, and a PyQt6 desktop window (optional voice).

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
# Primary: desktop window
python app.py

# Or double-click run.command on macOS (activates .venv if present, then app.py)
```

The window title is **JARVIS**; the status line shows `Desktop · local Ollama` when ready, and **Thinking…** while a reply is generating. Startup fails fast if the model is missing (suggests `ollama pull …`).

### CLI (secondary)

```bash
python jarvis.py
```

The CLI also prints `JARVIS › Thinking…` before each reply, and exits if the configured model is not installed.

Env vars: `OLLAMA_HOST` (default `http://127.0.0.1:11434`), `OLLAMA_MODEL` (default `llama3.1:8b`).

Notes are stored under `~/.jarvis/notes/`.

## Tools

See [TOOLS.md](TOOLS.md) for the full tool list (time, notes, browser, apps, clipboard, weather, GitHub).
