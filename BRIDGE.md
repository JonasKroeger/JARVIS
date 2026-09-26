# JARVIS ↔ Coder bridge

Minimal localhost HTTP APIs so Grok Bot **Coder** and Jonas's Mac **JARVIS** can
talk both ways. Does **not** call xAI.

Two directions:

| Direction | Listener (Mac) | Port | Client |
|-----------|----------------|------|--------|
| **Forward** Coder → JARVIS | `bridge_server.py` (inside Qt app or standalone) | `8765` | `coder_jarvis_bridge.py` |
| **Reverse** JARVIS → Coder | `coder_bridge_server.py` (mailbox daemon) | `8766` | `jarvis_ask_coder.py` / `ask_coder` tool |

Both bind **`127.0.0.1` only** (never LAN/public).

---

## Forward: Coder → JARVIS (port 8765)

| | |
|---|---|
| Host | `127.0.0.1` only |
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

### Verify (on the Mac)

```bash
curl -s http://127.0.0.1:8765/health
# {"ok": true}

curl -s -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"what is 2+2","context":{"source":"curl"}}'

python coder_jarvis_bridge.py "what is 2+2"
```

Look for `bridge listening http://127.0.0.1:8765/chat` in `jarvis-debug.log`.

### How Coder uses it

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

### Forward files

- `bridge_server.py` — stdlib `ThreadingHTTPServer`; each request owns an httpx client and calls `run_turn`
- `app.py` — starts the bridge in a daemon thread on launch
- `coder_jarvis_bridge.py` — CLI client for Coder / Shell

---

## Reverse: JARVIS → Coder (port 8766)

Coder does **not** run an HTTP server on the Mac by default (compute is a remote
box). The reverse path is a **mailbox**:

1. `coder_bridge_server.py` listens on `127.0.0.1:8766` **on the Mac**.
2. Each `POST /chat` writes `coder_bridge/inbox/<id>.json` and blocks until
   `coder_bridge/outbox/<id>.json` appears (or timeout / optional auto-echo).
3. Coder fulfills requests by running `coder_bridge_worker.py` on the Mac
   (Shell / machine tools), which writes the outbox reply.

| | |
|---|---|
| Host | `127.0.0.1` only |
| Port | `8766` (`CODER_BRIDGE_PORT`) |
| Timeout | `120` s default (`CODER_BRIDGE_TIMEOUT`) |
| Auth | if `CODER_BRIDGE_API_KEY` set → Bearer / `X-Api-Key` |
| Auto | `CODER_BRIDGE_AUTO=echo` answers in-process (smoke only) |

### Endpoints

- `GET /health` → `{"ok": true, "role": "coder-mailbox"}`
- `POST /chat` (also `POST /`) — same body shape as forward bridge

Response:

```json
{"reply": "...", "id": "<request-id>"}
```

### Start the mailbox (Mac)

```bash
cd ~/JARVIS
./start_coder_bridge.sh
# → daemon; log ~/JARVIS/coder-bridge.log ; pid ~/JARVIS/coder_bridge.pid

curl -s http://127.0.0.1:8766/health
# {"ok": true, "role": "coder-mailbox"}
```

Does **not** require the Qt JARVIS app.

### JARVIS asks Coder

```bash
cd ~/JARVIS
.venv/bin/python jarvis_ask_coder.py "What is Coder's role in one sentence?"
```

Or from the orb / chat: tool `ask_coder` with `message` (POSTs to `CODER_URL`).

Env:

- `CODER_URL` — default `http://127.0.0.1:8766/chat`
- `CODER_BRIDGE_API_KEY` — only if the mailbox has the same key set
- `CODER_BRIDGE_TIMEOUT` — client HTTP timeout (default 180)

Offline smoke:

```bash
python jarvis_ask_coder.py --demo "hello"
```

### Coder answers (worker)

Coder keeps a small worker alive **on the Mac**, or answers one-shot for e2e:

```bash
# One-shot substantive reply (e2e / Coder turn)
.venv/bin/python coder_bridge_worker.py --once --wait 30 \
  --reply "I am Jonas's coding assistant, paired with JARVIS over the reverse localhost bridge."

# Smoke echo
.venv/bin/python coder_bridge_worker.py --once --echo --wait 30

# Continuous: print each request as JSON line; read reply from stdin
.venv/bin/python coder_bridge_worker.py
```

Mailbox paths (gitignored contents):

- `coder_bridge/inbox/<id>.json`
- `coder_bridge/outbox/<id>.json`

### Reverse files

- `coder_bridge_server.py` — mailbox `ThreadingHTTPServer` on `:8766`
- `coder_bridge_worker.py` — Coder fulfills inbox → outbox
- `jarvis_ask_coder.py` — CLI client (mirror of `coder_jarvis_bridge.py`)
- `start_coder_bridge.sh` — background daemon + log
- `jarvis.py` — optional tool `ask_coder`
