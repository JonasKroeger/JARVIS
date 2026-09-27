# JARVIS ↔ Coder shared room

Thin **local** transport so the Mac JARVIS orb and Grok Bot **Coder** share a
chat thread. The platform source of truth is the Grok Bot group:

| | |
|---|---|
| Group | **JARVIS ↔ Coder** |
| Id | `832e7e66-c400-4d70-ae0d-88ae44177912` |

Mac Python **cannot** call Grok Bot `SendToAgent`. The split is intentional:

```
User speaks to orb ("Tell Coder …")
  → orb ask_coder posts role=user into room :8767
  → room writes SURFACED.json + TRIGGER (+ optional webhook)
  → parent Coder wakes (webhook routine / surface watcher)
  → parent MUST:
       (a) SendToAgent → group 832e7e66-…   (platform visibility)
       (b) room_reply.py --reply "…"       (unblocks orb SSE)
  → orb speaks only the role=coder text (clean TTS, no ids/JSON)
```

**Nothing** on the Mac invents Hitchhiker / math / ack replies as Coder.

---

## Local room (orb transport) — port 8767

| | |
|---|---|
| Host | `127.0.0.1` only |
| Port | `8767` (`CODER_ROOM_PORT`) |
| Store | `~/JARVIS/coder_room/` (sqlite + jsonl) |
| Autofill | **OFF** — surface only |

### API

- `GET /health`
- `POST /messages` `{ "role": "user"|"jarvis"|"coder", "text": "...", "reply_to": optional }`
- `GET /messages?after_id=`
- `GET /events?after_id=&role=coder` — SSE push (orb waits here)
- `GET /pending` — open user/jarvis handoffs awaiting coder

On each **user/jarvis** handoff the server writes:

- `coder_room/SURFACED.json`
- `coder_room/PENDING.json`
- `coder_room/TRIGGER`
- optional `POST` to `CODER_ROOM_NOTIFY_URL` / `CODER_BRIDGE_NOTIFY_URL`
  (with `Authorization` from `CODER_ROOM_NOTIFY_AUTH` or `CODER_ROOM_NOTIFY_HEADER`)

It does **not** post a coder reply. Surface files alone do **not** wake Grok Bot
Coder — the notify webhook is required for automatic parent wake.

### Wake webhook secrets (`.env`)

LaunchAgent `EnvironmentVariables` is **not** enough for secrets. `start_coder_room.sh`
sources `~/JARVIS/.env` (gitignored) so these load on every start/restart:

```
# ~/JARVIS/.env  (gitignored)
CODER_ROOM_NOTIFY_URL=<Webhook URL from Grok Bot routine jarvis-coder-mailbox>
CODER_ROOM_NOTIFY_AUTH=<Authorization header value from that routine panel>
```

Optional: `CODER_ROOM_NOTIFY_HEADER` as a full `Authorization: …` line (same value).
Do **not** invent URL/key — copy from the Grok Bot routine panel. Until set,
`/health` reports `notify_url_configured: false` (SURFACED.json only).

### Start

```bash
cd ~/JARVIS
./start_coder_room.sh
# or survive login:
./install_coder_room_launchagent.sh   # also retires old :8766 LaunchAgent
curl -s http://127.0.0.1:8767/health
```

### Orb path

Any utterance matching `\bcoder\b` force-routes to `ask_coder`:

1. `POST /messages` role=user
2. Wait on SSE `/events?role=coder` (~90s, `CODER_ROOM_TIMEOUT`)
3. Speak reply text only via `_clean_coder_spoken_text`

CLI smoke:

```bash
.venv/bin/python jarvis_ask_coder.py "Tell Coder what is 2+2"
```

### Parent fulfill (required — two steps)

```bash
# (b) Mac room — unblocks orb
cd ~/JARVIS && .venv/bin/python room_reply.py --pending
cd ~/JARVIS && .venv/bin/python room_reply.py --id <id> --reply "Two plus two is four."

# (a) Grok Bot group — parent agent only (Mac cannot):
# SendToAgent → channel/group id 832e7e66-c400-4d70-ae0d-88ae44177912
# short FYI / same reply text
```

`room_reply.py` prints a group reminder to stderr after every fulfill.

### Surface watcher (wake parent, never answer)

```bash
.venv/bin/python coder_room_surface.py --wait 600
# exits 0 with {id,text} — HOLD; parent fulfills then restarts
```

---

## Hard rules

- NEVER auto-generate Coder replies (no echo / autofulfill / Hitchhiker).
- Surface-only until parent runs `room_reply.py`.
- Orb speaks clean text only (no message ids, no JSON).
- Do not block the orb on the group post — group is best-effort visibility.

---

## Deprecated: :8766 mailbox

The reverse mailbox (`coder_bridge_server.py` on `127.0.0.1:8766`) and its
LaunchAgent `com.jonas.jarvis.coder-bridge` are **retired** for the happy path.

| Old | Replacement |
|-----|-------------|
| `POST :8766/chat` | `POST :8767/messages` + SSE wait |
| `fulfill_coder_reply.py` | `room_reply.py` |
| `coder_bridge_surface.py` | `coder_room_surface.py` |
| `start_coder_bridge.sh` | `start_coder_room.sh` |
| `CODER_URL=…8766/chat` | `CODER_ROOM_URL` / default `:8767` |

Mailbox code may remain in-tree for archaeology; do not start it. Echo worker and
`coder_bridge_autofulfill.py` stay disabled (`CODER_BRIDGE_ECHO_WORKER=0`,
`CODER_BRIDGE_AUTOFULFILL=0`).

See also `BRIDGE.md` (forward :8765 Coder→JARVIS still valid).

---

## Files

- `room_server.py` — room HTTP + SSE
- `room_reply.py` — explicit coder fulfill (b)
- `coder_room_surface.py` — one-shot surface
- `jarvis_ask_coder.py` — CLI client
- `jarvis.py` — `ask_coder` / `_force_ask_coder_turn` → room
- `start_coder_room.sh` / `launchd/com.jonas.jarvis.coder-room.plist`
- `install_coder_room_launchagent.sh`
- `coder_room/` — store (gitignored contents)
