#!/usr/bin/env python3
"""JARVIS ↔ Coder shared room (local orb transport) on 127.0.0.1:8767.

Source of truth for the *group chat UX* is the Grok Bot group
  JARVIS ↔ Coder  (id 832e7e66-c400-4d70-ae0d-88ae44177912).

Mac Python cannot call Grok Bot SendToAgent. This process is the thin local
transport so the orb can:
  - POST user/jarvis handoff messages
  - wait on SSE for the next role=coder reply
  - speak only that clean text

Parent Coder (when fulfilling) MUST:
  (a) SendToAgent into the Grok Bot group (platform visibility), AND
  (b) POST role=coder here via room_reply.py (unblocks orb SSE).

Hard rules:
  - NEVER invent / auto-fulfill Coder replies
  - user/jarvis posts awaiting coder → write SURFACED.json + TRIGGER only
  - no Hitchhiker/math/echo acks

API:
  GET  /health
  GET  /messages?after_id=<id>   (or after=<id>)
  GET  /pending
  GET  /events?after_id=<id>     SSE push
  POST /messages  {"role":"user"|"jarvis"|"coder","text":"...","reply_to":optional}
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 8767
HOST = "127.0.0.1"
GROUP_ID = "832e7e66-c400-4d70-ae0d-88ae44177912"
VALID_ROLES = frozenset({"user", "jarvis", "coder"})

_LogFn = Callable[[str, BaseException | None], None]


def _noop_log(msg: str, exc: BaseException | None = None) -> None:  # noqa: ARG001
    pass


def _root_dir() -> Path:
    override = os.environ.get("CODER_ROOM_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_room"


def _port() -> int:
    raw = os.environ.get("CODER_ROOM_PORT", str(DEFAULT_PORT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT


def ensure_dirs() -> Path:
    root = _root_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _db_path() -> Path:
    return ensure_dirs() / "room.sqlite"


def _jsonl_path() -> Path:
    return ensure_dirs() / "messages.jsonl"


def _trigger_path() -> Path:
    return ensure_dirs() / "TRIGGER"


def _surfaced_path() -> Path:
    return ensure_dirs() / "SURFACED.json"


def _pending_path() -> Path:
    return ensure_dirs() / "PENDING.json"


def write_trigger(*, reason: str = "pending", msg_id: str | None = None) -> Path:
    root = ensure_dirs()
    path = _trigger_path()
    body = f"{time.time():.6f}\nreason={reason}\nid={msg_id or ''}\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    try:
        os.utime(path, None)
    except OSError:
        pass
    return path


class RoomStore:
    """Append-only message store (sqlite + jsonl mirror). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        ensure_dirs()
        self._conn = sqlite3.connect(
            str(_db_path()),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                seq INTEGER NOT NULL UNIQUE,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                reply_to TEXT,
                created_at REAL NOT NULL,
                meta_json TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_seq ON messages(seq)"
        )
        self._subscribers: list[queue.Queue] = []
        self._seq = self._max_seq()

    def _max_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM messages").fetchone()
        return int(row["m"] if row else 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[queue.Queue] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def append(
        self,
        *,
        role: str,
        text: str,
        reply_to: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        role = (role or "").strip().lower()
        if role not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        if len(text) > 100_000:
            raise ValueError("text too long")
        msg_id = str(uuid.uuid4())
        created = time.time()
        with self._lock:
            self._seq += 1
            seq = self._seq
            meta_json = json.dumps(meta or {}, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO messages (id, seq, role, text, reply_to, created_at, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, seq, role, text, reply_to, created, meta_json),
            )
            msg = {
                "id": msg_id,
                "seq": seq,
                "role": role,
                "text": text,
                "reply_to": reply_to,
                "created_at": created,
                "meta": meta or {},
            }
            try:
                with open(_jsonl_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except OSError:
                pass
            self._broadcast(msg)
        return msg

    def get_after(self, after_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            if after_id:
                row = self._conn.execute(
                    "SELECT seq FROM messages WHERE id = ?", (after_id,)
                ).fetchone()
                after_seq = int(row["seq"]) if row else 0
            else:
                after_seq = 0
            rows = self._conn.execute(
                "SELECT id, seq, role, text, reply_to, created_at, meta_json "
                "FROM messages WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                (after_seq, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                meta = json.loads(r["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            out.append(
                {
                    "id": r["id"],
                    "seq": r["seq"],
                    "role": r["role"],
                    "text": r["text"],
                    "reply_to": r["reply_to"],
                    "created_at": r["created_at"],
                    "meta": meta if isinstance(meta, dict) else {},
                }
            )
        return out

    def get_by_id(self, msg_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT id, seq, role, text, reply_to, created_at, meta_json "
                "FROM messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
        if not r:
            return None
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return {
            "id": r["id"],
            "seq": r["seq"],
            "role": r["role"],
            "text": r["text"],
            "reply_to": r["reply_to"],
            "created_at": r["created_at"],
            "meta": meta if isinstance(meta, dict) else {},
        }

    def pending_for_coder(self) -> list[dict[str, Any]]:
        """User/jarvis messages that still await a later coder reply.

        A handoff is pending if no coder message with reply_to=<id> exists,
        and no coder message was appended after it (loose pairing).
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, seq, role, text, reply_to, created_at, meta_json "
                "FROM messages ORDER BY seq ASC"
            ).fetchall()
        answered: set[str] = set()
        messages: list[dict[str, Any]] = []
        for r in rows:
            try:
                meta = json.loads(r["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            m = {
                "id": r["id"],
                "seq": r["seq"],
                "role": r["role"],
                "text": r["text"],
                "reply_to": r["reply_to"],
                "created_at": r["created_at"],
                "meta": meta if isinstance(meta, dict) else {},
            }
            messages.append(m)
            if m["role"] == "coder" and m.get("reply_to"):
                answered.add(str(m["reply_to"]))

        # Also treat any coder msg after a handoff as answering the latest open one
        pending: list[dict[str, Any]] = []
        open_handoffs: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] in ("user", "jarvis"):
                awaiting = (m.get("meta") or {}).get("awaiting_coder")
                # Default: user/jarvis posts are handoffs unless marked otherwise
                if awaiting is False:
                    continue
                open_handoffs.append(m)
            elif m["role"] == "coder":
                if m.get("reply_to") and str(m["reply_to"]) in {h["id"] for h in open_handoffs}:
                    open_handoffs = [h for h in open_handoffs if h["id"] != m["reply_to"]]
                elif open_handoffs:
                    # FIFO: coder reply closes oldest open handoff
                    open_handoffs.pop(0)
        for h in open_handoffs:
            if h["id"] not in answered:
                pending.append(h)
        return pending


_STORE: RoomStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> RoomStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = RoomStore()
        return _STORE


def refresh_pending_snapshot(store: RoomStore | None = None) -> dict[str, Any]:
    store = store or get_store()
    pending = store.pending_for_coder()
    body = {
        "updated_at": time.time(),
        "count": len(pending),
        "group_id": GROUP_ID,
        "pending": [
            {
                "id": p["id"],
                "role": p["role"],
                "text": p["text"],
                "created_at": p["created_at"],
                "meta": p.get("meta") or {},
            }
            for p in pending
        ],
        "fulfill_hint": (
            'cd ~/JARVIS && .venv/bin/python room_reply.py --id <id> --reply "YOUR ANSWER" '
            f"&& SendToAgent group {GROUP_ID}"
        ),
    }
    path = _pending_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return body


def write_surfaced(msg: dict[str, Any]) -> Path:
    body = {
        "surfaced_at": time.time(),
        "id": msg.get("id"),
        "role": msg.get("role"),
        "text": msg.get("text"),
        "created_at": msg.get("created_at"),
        "status": "awaiting_parent_fulfill",
        "group_id": GROUP_ID,
        "fulfill_hint": (
            f'cd ~/JARVIS && .venv/bin/python room_reply.py --id {msg.get("id")} '
            f'--reply "YOUR ANSWER"'
        ),
        "group_hint": (
            f"Parent must ALSO SendToAgent into Grok Bot group {GROUP_ID} "
            "(Mac cannot post to the group)."
        ),
    }
    path = _surfaced_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    log = ensure_dirs() / "surface.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "event": "surfaced",
                    "id": msg.get("id"),
                    "role": msg.get("role"),
                    "text": (msg.get("text") or "")[:200],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


def _notify_url() -> str | None:
    url = (
        os.environ.get("CODER_ROOM_NOTIFY_URL", "").strip()
        or os.environ.get("CODER_BRIDGE_NOTIFY_URL", "").strip()
    )
    return url or None


def _fire_notify(msg: dict[str, Any], log: _LogFn) -> None:
    url = _notify_url()
    if not url:
        return

    def _post() -> None:
        try:
            import urllib.request

            payload = json.dumps(
                {
                    "event": "coder_room_pending",
                    "id": msg.get("id"),
                    "role": msg.get("role"),
                    "text": msg.get("text"),
                    "group_id": GROUP_ID,
                    "fulfill_hint": (
                        f'cd ~/JARVIS && .venv/bin/python room_reply.py '
                        f'--id {msg.get("id")} --reply "YOUR ANSWER"'
                    ),
                    "group_hint": f"Also SendToAgent group {GROUP_ID}",
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            log(f"notify ok id={msg.get('id')}", None)
        except Exception as e:  # noqa: BLE001
            log(f"notify failed: {type(e).__name__}: {e}", e)

    threading.Thread(target=_post, name="room-notify", daemon=True).start()


def on_handoff_posted(msg: dict[str, Any], log: _LogFn) -> None:
    """Surface-only: never invent a coder reply."""
    write_surfaced(msg)
    refresh_pending_snapshot()
    write_trigger(reason="surfaced", msg_id=str(msg.get("id") or ""))
    _fire_notify(msg, log)
    log(f"surfaced handoff id={msg.get('id')} role={msg.get('role')}", None)


def make_handler(store: RoomStore, log: _LogFn) -> type[BaseHTTPRequestHandler]:
    class RoomHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            log(f"http {self.address_string()} {fmt % args}", None)

        def _send_json(self, code: int, body: dict[str, Any] | list[Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(f"invalid JSON: {e}") from e
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            if path == "/health":
                pending = store.pending_for_coder()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "role": "coder-room",
                        "port": _port(),
                        "group_id": GROUP_ID,
                        "pending": len(pending),
                        "autofulfill": False,
                        "echo": False,
                        "notify_url_configured": bool(_notify_url()),
                        "store": str(_root_dir()),
                    },
                )
                return

            if path == "/pending":
                body = refresh_pending_snapshot(store)
                self._send_json(200, body)
                return

            if path == "/messages":
                after = (qs.get("after_id") or qs.get("after") or [None])[0]
                try:
                    limit = int((qs.get("limit") or ["200"])[0])
                except ValueError:
                    limit = 200
                msgs = store.get_after(after, limit=limit)
                self._send_json(200, {"ok": True, "messages": msgs, "count": len(msgs)})
                return

            if path == "/events":
                self._sse(qs)
                return

            self._send_json(404, {"ok": False, "error": "not found"})

        def _sse(self, qs: dict[str, list[str]]) -> None:
            after = (qs.get("after_id") or qs.get("after") or [None])[0]
            role_filter = (qs.get("role") or [None])[0]
            roles = None
            if role_filter:
                roles = {r.strip().lower() for r in role_filter.split(",") if r.strip()}

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def _emit(event: str, data: dict[str, Any]) -> None:
                payload = json.dumps(data, ensure_ascii=False)
                chunk = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()

            # Replay backlog after cursor
            try:
                backlog = store.get_after(after, limit=500)
                for m in backlog:
                    if roles and m["role"] not in roles:
                        continue
                    _emit("message", m)
                    after = m["id"]
                _emit("ready", {"ok": True, "after_id": after})
            except (BrokenPipeError, ConnectionResetError):
                return

            q = store.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15.0)
                    except queue.Empty:
                        try:
                            _emit("ping", {"ts": time.time()})
                        except (BrokenPipeError, ConnectionResetError):
                            break
                        continue
                    if roles and msg.get("role") not in roles:
                        continue
                    try:
                        _emit("message", msg)
                    except (BrokenPipeError, ConnectionResetError):
                        break
            finally:
                store.unsubscribe(q)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path != "/messages":
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            try:
                data = self._read_json()
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            role = str(data.get("role") or "").strip().lower()
            text = str(data.get("text") or data.get("message") or "").strip()
            reply_to = data.get("reply_to")
            reply_to_s = str(reply_to).strip() if reply_to else None
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            # Handoffs from orb default to awaiting coder
            if role in ("user", "jarvis") and "awaiting_coder" not in meta:
                meta = {**meta, "awaiting_coder": True}
            try:
                msg = store.append(role=role, text=text, reply_to=reply_to_s, meta=meta)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            except Exception as e:  # noqa: BLE001
                log(f"append failed: {e}", e)
                self._send_json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
                return

            if role in ("user", "jarvis") and (msg.get("meta") or {}).get("awaiting_coder", True):
                on_handoff_posted(msg, log)
            elif role == "coder":
                refresh_pending_snapshot(store)
                write_trigger(reason="coder_reply", msg_id=msg["id"])
                log(f"coder reply id={msg['id']} reply_to={reply_to_s}", None)

            self._send_json(200, {"ok": True, "message": msg})

    return RoomHandler


def create_server(
    *,
    host: str = HOST,
    port: int | None = None,
    log: _LogFn = _noop_log,
) -> ThreadingHTTPServer:
    store = get_store()
    ensure_dirs()
    refresh_pending_snapshot(store)
    handler = make_handler(store, log)
    bind_port = _port() if port is None else port
    # Try bind_port, then next few if conflict
    last_err: OSError | None = None
    for p in range(bind_port, bind_port + 5):
        try:
            server = ThreadingHTTPServer((host, p), handler)
            server.daemon_threads = True
            if p != bind_port:
                log(f"port {bind_port} busy; bound {p}", None)
            return server
        except OSError as e:
            last_err = e
            continue
    assert last_err is not None
    raise last_err


def _daemonize(pidfile: Path, logfile: Path) -> None:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    if os.fork() > 0:
        raise SystemExit(0)
    os.setsid()
    if os.fork() > 0:
        raise SystemExit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    with open(logfile, "a", encoding="utf-8") as logf:
        os.dup2(logf.fileno(), sys.stdout.fileno())
        os.dup2(logf.fileno(), sys.stderr.fileno())
    with open(os.devnull, "r") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    pidfile.write_text(str(os.getpid()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JARVIS ↔ Coder shared room server")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument(
        "--pidfile",
        default=os.environ.get(
            "CODER_ROOM_PID",
            str(Path(__file__).resolve().parent / "coder_room.pid"),
        ),
    )
    parser.add_argument(
        "--logfile",
        default=os.environ.get(
            "CODER_ROOM_LOG",
            str(Path(__file__).resolve().parent / "coder-room.log"),
        ),
    )
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    def _print_log(msg: str, exc: BaseException | None = None) -> None:
        print(msg, flush=True)
        if exc is not None:
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    if args.daemon:
        _daemonize(Path(args.pidfile), Path(args.logfile))

    if args.port is not None:
        os.environ["CODER_ROOM_PORT"] = str(args.port)

    srv = create_server(log=_print_log)
    host, port = srv.server_address
    print(
        f"coder-room listening http://{host}:{port}/ "
        f"group={GROUP_ID} store={_root_dir()} autofulfill=OFF",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("coder-room stopped", flush=True)
        sys.exit(0)
