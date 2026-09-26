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

### Verify (on the Mac)

```bash
curl -s http://127.0.0.1:8765/health
python coder_jarvis_bridge.py "what is 2+2"
```

### How Coder uses it

Coder runs the client **on Jonas's Mac** via machine tools
(`machineId` `01c88f7a-b822-4887-82b2-33a6f8c6c00c`, cwd `~/JARVIS`):

```bash
cd ~/JARVIS && .venv/bin/python coder_jarvis_bridge.py "your prompt here"
```

### Forward files

- `bridge_server.py` — stdlib `ThreadingHTTPServer`
- `app.py` — starts the bridge in a daemon thread on launch
- `coder_jarvis_bridge.py` — CLI client for Coder / Shell

---

## Reverse: JARVIS → Coder (port 8766) — LIVE MODE

Coder does **not** expose a public HTTP server on the Mac. The reverse path is a
**mailbox** plus a **live notifier** that wakes Coder (no echo ack).

```
User → JARVIS ask_coder → POST :8766/chat
                         → inbox/<id>.json
                         → PENDING.json + optional webhook POST
Coder (Grok Bot) ← webhook routine / poll PENDING
Coder → fulfill_coder_reply.py --reply "…" → outbox/<id>.json
JARVIS ← {"reply":"…"} → TTS speaks clean text
```

| | |
|---|---|
| Host | `127.0.0.1` only |
| Port | `8766` (`CODER_BRIDGE_PORT`) |
| Mode | `CODER_BRIDGE_MODE=live` (**default**) — **no echo** |
| Timeout | `90` s default in live (`CODER_BRIDGE_TIMEOUT`) |
| Auth | if `CODER_BRIDGE_API_KEY` set → Bearer / `X-Api-Key` |
| Notify | `CODER_BRIDGE_NOTIFY_URL` → POST JSON when a request is queued |
| Echo | **off** in live. Smoke only: `CODER_BRIDGE_MODE=echo` + `CODER_BRIDGE_ECHO_WORKER=1` |

### Endpoints

- `GET /health` → mode, pending count, worker_alive, notify_url_configured, timeout_s
- `GET /pending` → full pending list (same as `coder_bridge/PENDING.json`)
- `POST /chat` → blocks until outbox reply or timeout

Response:

```json
{"reply": "...", "id": "<request-id>"}
```

### Start (Mac) — live, no echo

```bash
cd ~/JARVIS
./start_coder_bridge.sh
# → mailbox daemon + live notifier (echo worker skipped)
# pids: coder_bridge.pid / coder_bridge_notify.pid
# logs: coder-bridge.log / coder-bridge-notify.log

curl -s http://127.0.0.1:8766/health
# {"ok":true,"mode":"live","pending":0,"echo":false,"notify_url_configured":false,...}
```

**Survive login/reboot** (LaunchAgent):

```bash
cd ~/JARVIS
# After parent creates a Grok Bot webhook routine, export its URL:
# export CODER_BRIDGE_NOTIFY_URL='https://…'
./install_coder_bridge_launchagent.sh
# installs ~/Library/LaunchAgents/com.jonas.jarvis.coder-bridge.plist
```

### JARVIS asks Coder

Any user utterance mentioning **Coder** force-routes to `ask_coder` (no LLM preamble).

```bash
.venv/bin/python jarvis_ask_coder.py "Tell Coder what is 2+2"
```

Env: `CODER_URL`, `CODER_BRIDGE_API_KEY`, `CODER_BRIDGE_TIMEOUT` (live default 90).

### How Coder is woken (parent must configure)

1. **Webhook (preferred, low latency)**  
   Parent creates a Grok Bot **webhook routine** that wakes this Coder chat.  
   Put the URL in the Mac environment / LaunchAgent:

   ```bash
   export CODER_BRIDGE_NOTIFY_URL='https://YOUR_GROK_WEBHOOK_URL'
   ./install_coder_bridge_launchagent.sh   # injects into plist + reloads
   # or: restart with the env set
   CODER_BRIDGE_NOTIFY_URL='…' ./start_coder_bridge.sh
   ```

   Payload POSTed on each new inbox item:

   ```json
   {
     "event": "coder_bridge_pending",
     "id": "<uuid>",
     "message": "Tell Coder what is 2+2",
     "context": {"source": "jarvis-tool"},
     "fulfill_hint": "cd ~/JARVIS && .venv/bin/python fulfill_coder_reply.py --id <uuid> --reply \"YOUR ANSWER\""
   }
   ```

2. **Aggressive poll (fallback)**  
   Parent cron/routine (≥5 min) or a tight Shell poller:

   ```bash
   curl -s http://127.0.0.1:8766/pending
   # or: cat ~/JARVIS/coder_bridge/PENDING.json
   .venv/bin/python fulfill_coder_reply.py --pending
   ```

   Note: cron alone is too slow for voice; prefer webhook.

### Coder answers (fulfill — required in live mode)

```bash
# List pending
.venv/bin/python fulfill_coder_reply.py --pending

# Answer oldest / specific id (spoken text only — no JSON/ids)
.venv/bin/python fulfill_coder_reply.py --reply "Two plus two is four."
.venv/bin/python fulfill_coder_reply.py --id <uuid> --reply "Two plus two is four."

# Or drop a file (notifier promotes to outbox)
# ~/JARVIS/coder_bridge/replies/<id>.json
# {"id":"<id>","reply":"Two plus two is four."}
```

Legacy worker still supports `--once --reply` / stdin, but **do not** run `--echo`
in live mode.

### Mailbox paths (gitignored contents)

- `coder_bridge/inbox/<id>.json`
- `coder_bridge/outbox/<id>.json`
- `coder_bridge/replies/<id>.json` — optional drop
- `coder_bridge/PENDING.json` — poll snapshot
- `coder_bridge/TRIGGER` — mtime bump for instant local wake

### Reverse files

- `coder_bridge_server.py` — mailbox on `:8766` (notify on queue)
- `coder_bridge_notify.py` — live watcher (PENDING + webhook + replies drop)
- `fulfill_coder_reply.py` — Coder writes real replies
- `coder_bridge_watch.py` — kqueue/TRIGGER helpers
- `coder_bridge_autofulfill.py` — timing-test instant fulfiller
- `coder_bridge_worker.py` — legacy echo/stdin worker (**not** started in live)
- `jarvis_ask_coder.py` — CLI client
- `start_coder_bridge.sh` — live mailbox + notifier
- `launchd/com.jonas.jarvis.coder-bridge.plist` + `install_coder_bridge_launchagent.sh`
- `jarvis.py` — tool `ask_coder` / `_force_ask_coder_turn`

### Latency (voice target <5s for simple Q)

Measured wall time is `ask_coder ok after Xs` in `jarvis-debug.log` (TTS is separate).

| Layer | Target | Notes |
|-------|--------|-------|
| force_ask_coder → POST | ms | skips Ollama tool selection |
| Mailbox outbox poll | ≤50–100ms | `CODER_BRIDGE_OUTBOX_POLL` (default 0.05) |
| Notifier / local watcher | ≤100ms | kqueue push + `CODER_BRIDGE_POLL` fallback; writes `TRIGGER` |
| Pure bridge RTT (autofulfill) | ≪1s | `coder_bridge_autofulfill.py --reply "Four."` |
| Real Coder think time | variable | parent agent / LLM — dominates when webhook unset |
| TTS | separate | do not fold into bridge RTT |

Without `CODER_BRIDGE_NOTIFY_URL`, rely on the live notifier `TRIGGER`/`PENDING.json` + a tight local watcher (or parent `/pending` poll ≤0.5s). The 37s "2+2" case was fulfill wait, not tool selection.

Timing-test autofulfill (isolates bridge):

```bash
# Terminal A
.venv/bin/python coder_bridge_autofulfill.py --reply "Four." --once --wait 30
# Terminal B
time .venv/bin/python jarvis_ask_coder.py "what is 2+2"
```

### Success criteria (live)

- Spoken reply is **never** the echo ack `"Coder received your message."`
- Parent has a path to see inbox (webhook and/or `/pending`) and fulfill within ~90s
- JARVIS TTS speaks the real reply text only (no ids/JSON)
