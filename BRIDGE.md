# JARVIS ↔ Coder bridge

Minimal localhost HTTP API so Grok Bot **Coder** (or any local client) can send
prompts to Jonas's Mac JARVIS and get replies. Does **not** call xAI.

## What JARVIS exposes

| | |
|---|---|
| Host | `127.0.0.1` only (never LAN/public) |
| Port | `8765` (override with `JARVIS_BRIDGE_PORT`) |
| Enable | on by default; set `JARVIS_BRIDGE=0` to disable |
| Auth | if `JARVIS_API_KEY` is set → require `Authorization: Bearer <key>`; if unset → allow localhost unauthenticated |

### Endpoints

- `GET /health` → `{"ok": true}`
- `POST /chat` (also `POST /`)

Request:

```json
{
  "message": "what is 2+2",
  "context": {
    "source": "coder",
    "grok_draft": "optional upstream draft — treated as context"
  }
}
```

Response:

```json
{"reply": "Four."}
```

`context` and `grok_draft` are optional. When present, `grok_draft` is injected
as an extra system note so JARVIS can use it without treating it as its own
prior turn.

## Verify (on the Mac)

```bash
curl -s http://127.0.0.1:8765/health
# {"ok": true}

curl -s -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"what is 2+2","context":{"source":"curl"}}'

python coder_jarvis_bridge.py "what is 2+2"
```

Look for `bridge listening http://127.0.0.1:8765/chat` in `jarvis-debug.log`.

## How Coder uses it

Coder runs the client **on Jonas's Mac** via machine tools
(`machineId` `01c88f7a-b822-4887-82b2-33a6f8c6c00c`, cwd `~/JARVIS`):

```bash
cd ~/JARVIS && .venv/bin/python coder_jarvis_bridge.py "your prompt here"
```

Env (optional):

- `JARVIS_URL` — default `http://127.0.0.1:8765/chat`
- `JARVIS_API_KEY` — only if the running app has the same key set

Offline smoke (no server):

```bash
python coder_jarvis_bridge.py --demo "hello"
```

## Files

- `bridge_server.py` — stdlib `ThreadingHTTPServer`; each request owns an httpx client and calls `run_turn`
- `app.py` — starts the bridge in a daemon thread on launch
- `coder_jarvis_bridge.py` — CLI client for Coder / Shell
