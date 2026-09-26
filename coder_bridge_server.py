#!/usr/bin/env python3
"""Coder reverse mailbox HTTP server (runs on Jonas's Mac).

JARVIS (or any localhost client) POSTs prompts here; Coder fulfills them by
writing replies into the outbox (via fulfill_coder_reply.py / worker) — Coder's
compute is a remote box, so this listener must live on the Mac at 127.0.0.1.

Contract (mirrors forward bridge):
  GET  /health  → {"ok": true, "role": "coder-mailbox", ...}
  GET  /pending → {"count": N, "pending": [...]}
  POST /chat    JSON {"message": "...", "context": {...}}
            → {"reply": "...", "id": "..."}

Bind: 127.0.0.1 only. Port: CODER_BRIDGE_PORT (default 8766).
Timeout waiting for outbox: CODER_BRIDGE_TIMEOUT
  (default 90s in live mode, 25s in echo/smoke).
Auth: if CODER_BRIDGE_API_KEY is set, require Authorization: Bearer <key>.

Mailbox layout (under ~/JARVIS/coder_bridge/ by default):
  inbox/<id>.json    — pending requests
  outbox/<id>.json   — replies written by Coder
  replies/<id>.json  — optional drop folder (notifier promotes to outbox)
  PENDING.json       — snapshot for aggressive polling
  TRIGGER            — mtime bump on each inbox write (fast local wake)

Live mode (CODER_BRIDGE_MODE=live, the default):
  - No in-process echo
  - On each inbox write: update PENDING.json + POST CODER_BRIDGE_NOTIFY_URL
  - Coder fulfills via fulfill_coder_reply.py

Smoke: CODER_BRIDGE_AUTO=echo or CODER_BRIDGE_MODE=echo answers in-process.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from coder_bridge_watch import outbox_poll_interval, write_trigger

DEFAULT_PORT = 8766
DEFAULT_TIMEOUT = 25.0
DEFAULT_TIMEOUT_LIVE = 90.0
HOST = "127.0.0.1"

_LogFn = Callable[[str, BaseException | None], None]


def _noop_log(msg: str, exc: BaseException | None = None) -> None:  # noqa: ARG001
    pass


def _root_dir() -> Path:
    override = os.environ.get("CODER_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_bridge"


def _inbox_dir() -> Path:
    return _root_dir() / "inbox"


def _outbox_dir() -> Path:
    return _root_dir() / "outbox"


def _replies_dir() -> Path:
    return _root_dir() / "replies"


def ensure_dirs() -> None:
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    _outbox_dir().mkdir(parents=True, exist_ok=True)
    _replies_dir().mkdir(parents=True, exist_ok=True)


def _bridge_mode() -> str:
    """live (default) | echo. live disables auto-echo and uses longer wait."""
    raw = os.environ.get("CODER_BRIDGE_MODE", "live").strip().lower()
    if raw in ("echo", "smoke"):
        return "echo"
    return "live"


def _notify_url() -> str | None:
    url = os.environ.get("CODER_BRIDGE_NOTIFY_URL", "").strip()
    return url or None


def list_pending_payloads() -> list[dict[str, Any]]:
    ensure_dirs()
    pending: list[dict[str, Any]] = []
    for f in sorted(_inbox_dir().glob("*.json"), key=lambda p: p.stat().st_mtime):
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id") and "message" in data:
            pending.append(data)
    return pending


def refresh_pending_snapshot() -> dict[str, Any]:
    """Write coder_bridge/PENDING.json for aggressive parent polling."""
    pending = list_pending_payloads()
    body = {
        "updated_at": time.time(),
        "count": len(pending),
        "mode": _bridge_mode(),
        "notify_url_configured": bool(_notify_url()),
        "pending": [
            {
                "id": p.get("id"),
                "message": p.get("message"),
                "context": p.get("context") or {},
                "created_at": p.get("created_at"),
            }
            for p in pending
        ],
    }
    snap = _root_dir() / "PENDING.json"
    tmp = snap.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(snap)
    return body


def fire_notify(req: dict[str, Any], *, log: _LogFn | None = None) -> None:
    """Best-effort POST to CODER_BRIDGE_NOTIFY_URL (non-blocking thread)."""
    url = _notify_url()
    if not url:
        return
    log_fn = log or _noop_log

    def _post() -> None:
        payload = {
            "event": "coder_bridge_pending",
            "id": req.get("id"),
            "message": req.get("message"),
            "context": req.get("context") or {},
            "created_at": req.get("created_at"),
            "mailbox": str(_root_dir()),
            "fulfill_hint": (
                f'cd ~/JARVIS && .venv/bin/python fulfill_coder_reply.py '
                f'--id {req.get("id")} --reply "YOUR ANSWER"'
            ),
        }
        body = json.dumps(payload).encode("utf-8")
        try:
            import urllib.request

            http_req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "jarvis-coder-mailbox/1",
                },
            )
            with urllib.request.urlopen(http_req, timeout=8) as resp:
                _ = resp.read(128)
            log_fn(f"coder-mailbox notify ok id={req.get('id')}", None)
        except Exception as e:  # noqa: BLE001
            log_fn(
                f"coder-mailbox notify failed id={req.get('id')}: {type(e).__name__}: {e}",
                e,
            )

    threading.Thread(target=_post, name="coder-notify", daemon=True).start()


def _env_port() -> int:
    raw = os.environ.get("CODER_BRIDGE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        port = DEFAULT_PORT
    return max(1, min(port, 65535))


def _env_timeout() -> float:
    default = DEFAULT_TIMEOUT_LIVE if _bridge_mode() == "live" else DEFAULT_TIMEOUT
    raw = os.environ.get("CODER_BRIDGE_TIMEOUT", str(default)).strip()
    try:
        t = float(raw)
    except ValueError:
        t = default
    return max(1.0, min(t, 3600.0))


def _api_key() -> str | None:
    key = os.environ.get("CODER_BRIDGE_API_KEY", "").strip()
    return key or None


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    expected = _api_key()
    if not expected:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {expected}":
        return True
    if handler.headers.get("X-Api-Key", "").strip() == expected:
        return True
    return False


def _auto_mode() -> str | None:
    # Live mode never auto-echoes unless explicitly forced via CODER_BRIDGE_AUTO.
    mode = os.environ.get("CODER_BRIDGE_AUTO", "").strip().lower()
    if mode:
        return mode
    if _bridge_mode() == "echo":
        return "echo"
    return None


def _auto_reply(message: str, context: dict[str, Any] | None, req_id: str) -> str | None:
    """In-process handler for smoke tests. Returns reply text or None to wait for worker."""
    mode = _auto_mode()
    if mode == "echo":
        _ = (message, context, req_id)
        return "Coder received your message."
    return None


def write_inbox(
    req_id: str,
    message: str,
    context: dict[str, Any] | None,
    *,
    log: _LogFn | None = None,
) -> Path:
    ensure_dirs()
    path = _inbox_dir() / f"{req_id}.json"
    payload = {
        "id": req_id,
        "message": message,
        "context": context or {},
        "created_at": time.time(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    refresh_pending_snapshot()
    write_trigger(reason="inbox_write", req_id=req_id)
    fire_notify(payload, log=log)
    return path


def wait_for_outbox(req_id: str, timeout: float) -> dict[str, Any]:
    """Poll until outbox/<id>.json appears or timeout. Returns parsed body.

    Poll interval defaults to 50ms (CODER_BRIDGE_OUTBOX_POLL, clamped 20–200ms)
    so fulfill → HTTP response stays sub-second once the outbox file lands.
    """
    out_path = _outbox_dir() / f"{req_id}.json"
    interval = outbox_poll_interval()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if out_path.is_file():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                time.sleep(interval)
                continue
            if isinstance(data, dict) and "reply" in data:
                return data
        time.sleep(interval)
    raise TimeoutError(
        f"Coder bridge: no reply within {timeout:.0f}s "
        f"(id={req_id}). Fulfill: python fulfill_coder_reply.py --id {req_id} --reply TEXT"
    )


def handle_chat(
    payload: dict[str, Any],
    *,
    timeout: float | None = None,
    log: _LogFn | None = None,
) -> dict[str, Any]:
    log = log or _noop_log
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("missing or empty 'message'")
    context = payload.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("'context' must be an object when present")

    req_id = uuid.uuid4().hex
    message = message.strip()
    timeout = _env_timeout() if timeout is None else timeout

    auto = _auto_reply(message, context, req_id)
    if auto is not None:
        log(f"coder-mailbox auto-reply id={req_id}", None)
        return {"reply": auto, "id": req_id}

    write_inbox(req_id, message, context, log=log)
    log(f"coder-mailbox queued id={req_id} mode={_bridge_mode()}", None)
    try:
        data = wait_for_outbox(req_id, timeout)
    finally:
        inbox_path = _inbox_dir() / f"{req_id}.json"
        try:
            inbox_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            refresh_pending_snapshot()
        except OSError:
            pass

    reply = data.get("reply", "")
    return {"reply": str(reply) if reply is not None else "", "id": req_id}


def make_handler(*, log: _LogFn | None = None) -> type[BaseHTTPRequestHandler]:
    log_fn = log or _noop_log

    class MailboxHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            try:
                log_fn(f"coder-mailbox {self.address_string()} {fmt % args}", None)
            except Exception:  # noqa: BLE001
                pass

        def _send_json(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/health":
                ensure_dirs()
                pending = list_pending_payloads()
                hb = _root_dir() / "worker.heartbeat"
                worker_age = None
                worker_alive = False
                if hb.is_file():
                    try:
                        worker_age = round(time.time() - hb.stat().st_mtime, 2)
                        worker_alive = worker_age <= 5.0
                    except OSError:
                        pass
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "role": "coder-mailbox",
                        "mode": _bridge_mode(),
                        "pending": len(pending),
                        "worker_alive": worker_alive,
                        "worker_heartbeat_age_s": worker_age,
                        "timeout_s": _env_timeout(),
                        "notify_url_configured": bool(_notify_url()),
                        "echo": False if _bridge_mode() == "live" else True,
                    },
                )
                return
            if path == "/pending":
                body = refresh_pending_snapshot()
                self._send_json(200, body)
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path not in ("/chat", "/"):
                self._send_json(404, {"error": "not found"})
                return
            if not _check_auth(self):
                self._send_json(401, {"error": "unauthorized"})
                return
            length_raw = self.headers.get("Content-Length", "0")
            try:
                length = int(length_raw)
            except ValueError:
                length = 0
            if length < 0 or length > 1_000_000:
                self._send_json(400, {"error": "invalid content-length"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "body must be a json object"})
                return
            try:
                result = handle_chat(payload, log=log_fn)
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except TimeoutError as e:
                self._send_json(504, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                log_fn(f"coder-mailbox chat failed: {type(e).__name__}: {e}", e)
                self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

    return MailboxHandler


def create_server(
    *,
    host: str = HOST,
    port: int | None = None,
    log: _LogFn | None = None,
) -> ThreadingHTTPServer:
    ensure_dirs()
    refresh_pending_snapshot()
    port = _env_port() if port is None else port
    handler = make_handler(log=log)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def start_mailbox_in_thread(*, log: _LogFn | None = None) -> threading.Thread | None:
    """Start mailbox in a daemon thread. Gate with CODER_BRIDGE=0 to disable."""
    if os.environ.get("CODER_BRIDGE", "1").strip() in ("0", "false", "False", "off", "OFF"):
        if log:
            log("coder-mailbox disabled via CODER_BRIDGE=0", None)
        return None

    port = _env_port()
    log_fn = log or _noop_log

    def _run() -> None:
        try:
            server = create_server(port=port, log=log_fn)
            log_fn(
                f"coder-mailbox listening http://{HOST}:{port}/chat "
                f"mode={_bridge_mode()} timeout={_env_timeout():.0f}s",
                None,
            )
            server.serve_forever()
        except OSError as e:
            log_fn(f"coder-mailbox failed to bind {HOST}:{port}: {e}", e)
        except Exception as e:  # noqa: BLE001
            log_fn(
                f"coder-mailbox crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                e,
            )

    t = threading.Thread(target=_run, name="coder-mailbox", daemon=True)
    t.start()
    return t


def _daemonize(pidfile: Path, logfile: Path) -> None:
    """Double-fork detach (Unix). Parent exits after writing pidfile."""
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

    parser = argparse.ArgumentParser(description="Coder reverse mailbox HTTP server")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Double-fork into background; write pidfile and append to logfile",
    )
    parser.add_argument(
        "--pidfile",
        default=os.environ.get(
            "CODER_BRIDGE_PID",
            str(Path(__file__).resolve().parent / "coder_bridge.pid"),
        ),
    )
    parser.add_argument(
        "--logfile",
        default=os.environ.get(
            "CODER_BRIDGE_LOG",
            str(Path(__file__).resolve().parent / "coder-bridge.log"),
        ),
    )
    args = parser.parse_args()

    def _print_log(msg: str, exc: BaseException | None = None) -> None:
        print(msg, flush=True)
        if exc is not None:
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    if args.daemon:
        _daemonize(Path(args.pidfile), Path(args.logfile))

    srv = create_server(log=_print_log)
    port = srv.server_address[1]
    print(
        f"coder-mailbox listening http://{HOST}:{port}/chat "
        f"mode={_bridge_mode()} timeout={_env_timeout():.0f}s",
        flush=True,
    )
    print(f"mailbox dir: {_root_dir()}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("coder-mailbox stopped", flush=True)
        sys.exit(0)
