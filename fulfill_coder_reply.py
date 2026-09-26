#!/usr/bin/env python3
"""Fulfill a pending Coder mailbox request (live mode — no echo).

Coder (Grok Bot) runs this on Jonas's Mac via Shell / machineId to:
  - list pending inbox messages
  - write a real reply into the outbox so JARVIS TTS speaks it

Examples:
  .venv/bin/python fulfill_coder_reply.py --pending
  .venv/bin/python fulfill_coder_reply.py --reply "Two plus two is four."
  .venv/bin/python fulfill_coder_reply.py --id <uuid> --reply "Done."
  echo "Done." | .venv/bin/python fulfill_coder_reply.py --id <uuid>

Env:
  CODER_BRIDGE_DIR   mailbox root (default: <repo>/coder_bridge)
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
    (_root_dir() / "replies").mkdir(parents=True, exist_ok=True)


def list_pending() -> list[dict[str, Any]]:
    ensure_dirs()
    out: list[dict[str, Any]] = []
    files = sorted(_inbox_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    for path in files:
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id") and "message" in data:
            out.append(data)
    return out


def write_reply(req_id: str, reply: str, *, extra: dict[str, Any] | None = None) -> Path:
    ensure_dirs()
    path = _outbox_dir() / f"{req_id}.json"
    payload: dict[str, Any] = {
        "id": req_id,
        "reply": reply,
        "answered_at": time.time(),
        "source": "fulfill_coder_reply",
    }
    if extra:
        payload.update(extra)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    inbox = _inbox_dir() / f"{req_id}.json"
    try:
        inbox.unlink(missing_ok=True)
    except OSError:
        pass
    # Refresh PENDING.json snapshot
    refresh_pending_snapshot()
    return path


def refresh_pending_snapshot() -> None:
    ensure_dirs()
    pending = list_pending()
    snap = _root_dir() / "PENDING.json"
    body = {
        "updated_at": time.time(),
        "count": len(pending),
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
    tmp = snap.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(snap)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List or fulfill pending Coder mailbox requests (live mode)."
    )
    parser.add_argument(
        "--pending",
        action="store_true",
        help="Print pending requests as JSON and exit",
    )
    parser.add_argument(
        "--id",
        default=None,
        help="Request id to fulfill (default: oldest pending)",
    )
    parser.add_argument(
        "--reply",
        default=None,
        help="Reply text (spoken by JARVIS). If omitted, read one line / all stdin.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="Wait up to N seconds for a pending request before failing",
    )
    args = parser.parse_args(argv)

    ensure_dirs()
    refresh_pending_snapshot()

    if args.pending:
        pending = list_pending()
        print(json.dumps({"count": len(pending), "pending": pending}, ensure_ascii=False, indent=2))
        return 0 if pending else 2

    deadline = time.monotonic() + max(0.0, args.wait)
    req: dict[str, Any] | None = None
    while True:
        pending = list_pending()
        if args.id:
            for p in pending:
                if str(p.get("id")) == str(args.id):
                    req = p
                    break
            if req is None and pending and args.wait <= 0:
                print(
                    f"no pending request with id={args.id!r} "
                    f"(have {[p.get('id') for p in pending]})",
                    file=sys.stderr,
                )
                return 2
        elif pending:
            req = pending[0]
        if req is not None:
            break
        if time.monotonic() >= deadline:
            print("no pending requests", file=sys.stderr)
            return 2
        time.sleep(0.2)

    assert req is not None
    req_id = str(req["id"])

    if args.reply is not None:
        reply = args.reply
    else:
        if sys.stdin.isatty():
            print(
                json.dumps({"event": "awaiting_reply", "id": req_id, "message": req.get("message")},
                           ensure_ascii=False),
                file=sys.stderr,
            )
        data = sys.stdin.read()
        if not data:
            print("empty reply (stdin closed)", file=sys.stderr)
            return 1
        # Prefer full stdin (multi-line OK); strip one trailing newline only.
        reply = data[:-1] if data.endswith("\n") and data.count("\n") == 1 else data
        if reply.endswith("\n") and not reply.endswith("\n\n"):
            reply = reply[:-1]

    reply = reply.strip()
    if not reply:
        print("empty reply", file=sys.stderr)
        return 1

    out = write_reply(req_id, reply)
    print(
        json.dumps(
            {
                "event": "answered",
                "id": req_id,
                "outbox": str(out),
                "reply_len": len(reply),
                "reply_preview": reply[:120],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
