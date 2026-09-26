#!/usr/bin/env python3
"""Minimal localhost HTTP bridge so external clients (e.g. Grok Coder) can chat with JARVIS.

Contract (matches adapter / coder_jarvis_bridge.py):
  POST /chat  JSON {"message": "...", "context": {"source": "...", "grok_draft": "..."}}
  → {"reply": "..."}

Also accepts POST / for convenience. GET /health → {"ok": true}.

Bind: 127.0.0.1 only. Port: JARVIS_BRIDGE_PORT (default 8765).
Auth: if JARVIS_API_KEY is set, require Authorization: Bearer <key>; else allow
localhost unauthenticated.

Started from app.py in a daemon thread via start_bridge_in_thread().
"""

from __future__ import annotations

import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

# Lazy import of jarvis brain to keep standalone health checks light and avoid
# circular imports at module load when only testing the handler.
_LogFn = Callable[[str, BaseException | None], None]


def _noop_log(msg: str, exc: BaseException | None = None) -> None:  # noqa: ARG001
    pass


DEFAULT_PORT = 8765
HOST = "127.0.0.1"


def _env_port() -> int:
    raw = os.environ.get("JARVIS_BRIDGE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        port = DEFAULT_PORT
    return max(1, min(port, 65535))


def _api_key() -> str | None:
    key = os.environ.get("JARVIS_API_KEY", "").strip()
    return key or None


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    """Return True if request is allowed. Localhost-only bind is the primary gate."""
    expected = _api_key()
    if not expected:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {expected}":
        return True
    # Also accept X-Api-Key for convenience
    if handler.headers.get("X-Api-Key", "").strip() == expected:
        return True
    return False


def build_messages(message: str, context: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build a fresh messages list for run_turn (system + optional draft + user)."""
    import jarvis as brain

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": brain.SYSTEM_PROMPT},
    ]
    ctx = context or {}
    draft = ctx.get("grok_draft")
    source = ctx.get("source")
    if draft or source:
        note_parts: list[str] = []
        if source:
            note_parts.append(f"Request source: {source}.")
        if draft:
            note_parts.append(
                "An upstream assistant draft follows — treat it as context, "
                "not as your own prior reply. Prefer your own judgment.\n\n"
                f"{draft}"
            )
        messages.append({"role": "system", "content": "\n".join(note_parts)})
    messages.append({"role": "user", "content": message})
    return messages


def handle_chat(
    payload: dict[str, Any],
    *,
    model: str | None = None,
    log: _LogFn | None = None,
) -> dict[str, Any]:
    """Run one JARVIS turn from a parsed JSON body. Returns {"reply": ...} or raises."""
    import jarvis as brain

    log = log or _noop_log
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("missing or empty 'message'")
    context = payload.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("'context' must be an object when present")

    model_name = model or os.environ.get("OLLAMA_MODEL", brain.DEFAULT_OLLAMA_MODEL)
    messages = build_messages(message.strip(), context)

    client: httpx.Client | None = None
    try:
        client = httpx.Client(timeout=180.0)
        _msgs, reply = brain.run_turn(client, model_name, messages)
        return {"reply": reply or ""}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


def make_handler(
    *,
    model: str | None = None,
    log: _LogFn | None = None,
) -> type[BaseHTTPRequestHandler]:
    log_fn = log or _noop_log

    class BridgeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            try:
                log_fn(f"bridge {self.address_string()} {fmt % args}", None)
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
                self._send_json(200, {"ok": True})
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
                result = handle_chat(payload, model=model, log=log_fn)
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                log_fn(f"bridge chat failed: {type(e).__name__}: {e}", e)
                self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

    return BridgeHandler


def create_server(
    *,
    host: str = HOST,
    port: int | None = None,
    model: str | None = None,
    log: _LogFn | None = None,
) -> ThreadingHTTPServer:
    port = _env_port() if port is None else port
    handler = make_handler(model=model, log=log)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def start_bridge_in_thread(
    *,
    model: str | None = None,
    log: _LogFn | None = None,
) -> threading.Thread | None:
    """Start the bridge in a daemon thread. Returns the thread, or None if disabled.

    Gate with JARVIS_BRIDGE=0 to disable (default: on).
    """
    if os.environ.get("JARVIS_BRIDGE", "1").strip() in ("0", "false", "False", "off", "OFF"):
        if log:
            log("bridge disabled via JARVIS_BRIDGE=0", None)
        return None

    port = _env_port()
    log_fn = log or _noop_log

    def _run() -> None:
        try:
            server = create_server(port=port, model=model, log=log_fn)
            log_fn(
                f"bridge listening http://{HOST}:{port}/chat",
                None,
            )
            server.serve_forever()
        except OSError as e:
            log_fn(f"bridge failed to bind {HOST}:{port}: {e}", e)
        except Exception as e:  # noqa: BLE001
            log_fn(
                f"bridge crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                e,
            )

    t = threading.Thread(target=_run, name="jarvis-bridge", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    # Standalone mode (no Qt) — useful for debugging the bridge alone.
    def _print_log(msg: str, exc: BaseException | None = None) -> None:
        print(msg, flush=True)
        if exc is not None:
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    srv = create_server(log=_print_log)
    print(f"bridge listening http://{HOST}:{srv.server_address[1]}/chat", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bridge stopped", flush=True)
