#!/usr/bin/env python3
"""Coder-side worker for the reverse mailbox (runs on Jonas's Mac).

Polls ~/JARVIS/coder_bridge/inbox for pending requests and writes replies to
outbox. Coder (remote box) drives this via Shell on machineId
01c88f7a-b822-4887-82b2-33a6f8c6c00c.

Modes:
  --once --reply TEXT   Answer the oldest pending request with TEXT, then exit.
  --once --echo         Answer oldest with a Coder-marked echo, then exit.
  --echo                Poll forever; echo every request.
  --once                Print oldest request as one JSON line to stdout; wait for
                        a reply line on stdin (or use --reply / --echo).
  (default)             Poll forever; for each request print JSON line to stdout
                        and read one reply line from stdin.

Env:
  CODER_BRIDGE_DIR   mailbox root (default: <repo>/coder_bridge)
  CODER_BRIDGE_POLL  poll interval seconds (default 0.25)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _root_dir() -> Path:
    override = os.environ.get("CODER_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_bridge"


def _inbox_dir() -> Path:
    return _root_dir() / "inbox"


def _outbox_dir() -> Path:
    return _root_dir() / "outbox"


def ensure_dirs() -> None:
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    _outbox_dir().mkdir(parents=True, exist_ok=True)


def list_pending() -> list[Path]:
    ensure_dirs()
    files = sorted(
        _inbox_dir().glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return [p for p in files if p.is_file()]


def read_request(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if "id" not in data or "message" not in data:
        return None
    return data


def write_reply(req_id: str, reply: str, *, extra: dict[str, Any] | None = None) -> Path:
    ensure_dirs()
    path = _outbox_dir() / f"{req_id}.json"
    payload: dict[str, Any] = {
        "id": req_id,
        "reply": reply,
        "answered_at": time.time(),
    }
    if extra:
        payload.update(extra)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    # Remove inbox entry so it is not re-processed.
    inbox = _inbox_dir() / f"{req_id}.json"
    try:
        inbox.unlink(missing_ok=True)
    except OSError:
        pass
    return path


def echo_reply(req: dict[str, Any]) -> str:
    msg = str(req.get("message", ""))
    rid = str(req.get("id", ""))
    src = (req.get("context") or {}).get("source", "jarvis") if isinstance(req.get("context"), dict) else "jarvis"
    return f"[Coder] echo id={rid} source={src}: {msg}"


def _poll_interval() -> float:
    raw = os.environ.get("CODER_BRIDGE_POLL", "0.25").strip()
    try:
        return max(0.05, float(raw))
    except ValueError:
        return 0.25


def claim_oldest() -> dict[str, Any] | None:
    for path in list_pending():
        req = read_request(path)
        if req is not None:
            return req
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Answer pending Coder mailbox requests (reverse bridge)."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Handle a single pending request then exit (exit 2 if none)",
    )
    parser.add_argument(
        "--reply",
        default=None,
        help="Reply text for --once (skips stdin)",
    )
    parser.add_argument(
        "--echo",
        action="store_true",
        help="Reply with a Coder-marked echo of the message",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="With --once: wait up to N seconds for a pending request",
    )
    args = parser.parse_args(argv)

    ensure_dirs()
    interval = _poll_interval()

    def handle_one(req: dict[str, Any]) -> None:
        # Always emit the request as a JSON line for Coder observability.
        print(json.dumps({"event": "request", **req}, ensure_ascii=False), flush=True)
        if args.echo:
            reply = echo_reply(req)
        elif args.reply is not None:
            reply = args.reply
        else:
            # Interactive: one line from stdin is the reply body.
            line = sys.stdin.readline()
            if not line:
                raise RuntimeError("stdin closed before reply")
            reply = line.rstrip("\n")
        out = write_reply(str(req["id"]), reply)
        print(
            json.dumps(
                {"event": "answered", "id": req["id"], "outbox": str(out)},
                ensure_ascii=False,
            ),
            flush=True,
        )

    if args.once:
        deadline = time.monotonic() + max(0.0, args.wait)
        while True:
            req = claim_oldest()
            if req is not None:
                handle_one(req)
                return 0
            if time.monotonic() >= deadline:
                print("no pending requests", file=sys.stderr)
                return 2
            time.sleep(interval)

    # Continuous poll
    print(
        json.dumps(
            {
                "event": "worker_start",
                "inbox": str(_inbox_dir()),
                "outbox": str(_outbox_dir()),
                "echo": bool(args.echo),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    while True:
        req = claim_oldest()
        if req is None:
            time.sleep(interval)
            continue
        try:
            handle_one(req)
        except Exception as e:  # noqa: BLE001
            print(
                json.dumps(
                    {"event": "error", "error": f"{type(e).__name__}: {e}"},
                    ensure_ascii=False,
                ),
                flush=True,
                file=sys.stderr,
            )
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
