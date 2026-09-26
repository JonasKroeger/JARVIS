#!/usr/bin/env python3
"""Coder reverse mailbox HTTP server (runs on Jonas's Mac).

JARVIS (or any localhost client) POSTs prompts here; Coder fulfills them by
writing replies into the outbox (via coder_bridge_worker.py) — Coder's compute
is a remote box, so this listener must live on the Mac at 127.0.0.1.

Contract (mirrors forward bridge):
  GET  /health → {"ok": true, "role": "coder-mailbox"}
  POST /chat   JSON {"message": "...", "context": {...}}
           → {"reply": "..."}

Bind: 127.0.0.1 only. Port: CODER_BRIDGE_PORT (default 8766).
Timeout waiting for outbox: CODER_BRIDGE_TIMEOUT (default 25s).
Auth: if CODER_BRIDGE_API_KEY is set, require Authorization: Bearer <key>.

Mailbox layout (under ~/JARVIS/coder_bridge/ by default, or next to this file):
  inbox/<id>.json   — pending requests
  outbox/<id>.json  — replies written by the worker

Optional auto-handler: set CODER_BRIDGE_AUTO=echo to answer in-process with a
Coder-marked echo (smoke only; no worker needed).
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

DEFAULT_PORT = 8766
DEFAULT_TIMEOUT = 25.0
HOST = "127.0.0.1"

_LogFn = Callable[[str, BaseException | None], None]


def _noop_log(msg: str, exc: BaseException | None = None) -> None:  # noqa: ARG001
    pass


def _root_dir() -> Path:
    override = os.environ.get("CODER_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # Prefer repo root next to this file (works for ~/JARVIS and /workspace/JARVIS).
    return Path(__file__).resolve().parent / "coder_bridge"


def _inbox_dir() -> Path:
    return _root_dir() / "inbox"


def _outbox_dir() -> Path:
    return _root_dir() / "outbox"


def ensure_dirs() -> None:
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    _outbox_dir().mkdir(parents=True, exist_ok=True)


def _env_port() -> int:
    raw = os.environ.get("CODER_BRIDGE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        port = DEFAULT_PORT
    return max(1, min(port, 65535))


def _env_timeout() -> float:
    raw = os.environ.get("CODER_BRIDGE_TIMEOUT", str(DEFAULT_TIMEOUT)).strip()
    try:
        t = float(raw)
    except ValueError:
        t = DEFAULT_TIMEOUT
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
    mode = os.environ.get("CODER_BRIDGE_AUTO", "").strip().lower()
    return mode or None


def _auto_reply(message: str, context: dict[str, Any] | None, req_id: str) -> str | None:
    """In-process handler for smoke tests. Returns reply text or None to wait for worker."""
    mode = _auto_mode()
    if mode == "echo":
        src = (context or {}).get("source", "jarvis")
        return (
            f"[Coder echo] id={req_id} source={src} "
            f"message={message!r}"
        )
    return None


def write_inbox(req_id: str, message: str, context: dict[str, Any] | None) -> Path:
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
    return path


def wait_for_outbox(req_id: str, timeout: float) -> dict[str, Any]:
    """Poll until outbox/<id>.json appears or timeout. Returns parsed body."""
    out_path = _outbox_dir() / f"{req_id}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if out_path.is_file():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if isinstance(data, dict) and "reply" in data:
                return data
            # Malformed — keep waiting until timeout (worker may rewrite)
        time.sleep(0.05)
    raise TimeoutError(
        f"Coder bridge: no worker replied within {timeout:.0f}s "
        f"(id={req_id}). Start: python coder_bridge_worker.py --echo"
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

    write_inbox(req_id, message, context)
    log(f"coder-mailbox queued id={req_id}", None)
    try:
        data = wait_for_outbox(req_id, timeout)
    finally:
        # Best-effort cleanup of inbox entry once we've waited (reply or timeout).
        inbox_path = _inbox_dir() / f"{req_id}.json"
        try:
            inbox_path.unlink(missing_ok=True)
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
                pending = [
                    f.name
                    for f in _inbox_dir().glob("*.json")
                    if f.is_file() and f.name != ".gitkeep"
                ]
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
                        "pending": len(pending),
                        "worker_alive": worker_alive,
                        "worker_heartbeat_age_s": worker_age,
                        "timeout_s": _env_timeout(),
                    },
                )
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
            log_fn(f"coder-mailbox listening http://{HOST}:{port}/chat", None)
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
    # First fork
    if os.fork() > 0:
        raise SystemExit(0)
    os.setsid()
    # Second fork
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
    print(f"coder-mailbox listening http://{HOST}:{port}/chat", flush=True)
    print(f"mailbox dir: {_root_dir()}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("coder-mailbox stopped", flush=True)
        sys.exit(0)
