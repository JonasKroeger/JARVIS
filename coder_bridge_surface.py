#!/usr/bin/env python3
"""One-shot surface-only watcher for the Coder reverse mailbox.

Watches inbox / TRIGGER via kqueue (+ poll fallback). When ONE pending
request appears:
  1. Writes coder_bridge/SURFACED.json (id + message + context)
  2. Appends a line to coder_bridge/surface.log
  3. Prints a JSON result payload to stdout
  4. Exits 0

NEVER fulfills. NEVER invents reply text. NEVER calls fulfill_coder_reply.
Parent Coder must answer later via fulfill_coder_reply.py, then restart this.

Examples:
  .venv/bin/python coder_bridge_surface.py              # wait forever for one
  .venv/bin/python coder_bridge_surface.py --wait 120   # timeout after 120s
  .venv/bin/python coder_bridge_surface.py --if-pending # exit immediately if already pending

Env:
  CODER_BRIDGE_DIR   mailbox root
  CODER_BRIDGE_POLL  fallback poll seconds (default 0.1)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from coder_bridge_watch import notify_poll_interval, watch_inbox_events, write_trigger


def _root_dir() -> Path:
    override = os.environ.get("CODER_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_bridge"


def _inbox_dir() -> Path:
    return _root_dir() / "inbox"


def ensure_dirs() -> None:
    root = _root_dir()
    root.mkdir(parents=True, exist_ok=True)
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    (root / "outbox").mkdir(parents=True, exist_ok=True)
    (root / "replies").mkdir(parents=True, exist_ok=True)


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


def write_surfaced(req: dict[str, Any]) -> Path:
    ensure_dirs()
    snap = _root_dir() / "SURFACED.json"
    body = {
        "surfaced_at": time.time(),
        "id": req.get("id"),
        "message": req.get("message"),
        "context": req.get("context") or {},
        "created_at": req.get("created_at"),
        "status": "awaiting_parent_fulfill",
        "fulfill_hint": (
            f'cd ~/JARVIS && .venv/bin/python fulfill_coder_reply.py '
            f'--id {req.get("id")} --reply "YOUR ANSWER"'
        ),
    }
    tmp = snap.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(snap)
    return snap


def append_surface_log(req: dict[str, Any]) -> None:
    ensure_dirs()
    log = _root_dir() / "surface.log"
    line = json.dumps(
        {
            "ts": time.time(),
            "event": "surfaced",
            "id": req.get("id"),
            "message": req.get("message"),
        },
        ensure_ascii=False,
    )
    with open(log, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def surface_one(req: dict[str, Any]) -> dict[str, Any]:
    """Surface pending to parent — no fulfill, no invented text."""
    write_surfaced(req)
    append_surface_log(req)
    write_trigger(reason="surfaced", req_id=str(req.get("id") or ""))
    result = {
        "event": "coder_bridge_surfaced",
        "ok": True,
        "id": req.get("id"),
        "message": req.get("message"),
        "context": req.get("context") or {},
        "created_at": req.get("created_at"),
        "surfaced_at": time.time(),
        "action": "HOLD — do not auto-reply; parent must fulfill_coder_reply.py",
        "fulfill_hint": (
            f'cd ~/JARVIS && .venv/bin/python fulfill_coder_reply.py '
            f'--id {req.get("id")} --reply "YOUR ANSWER"'
        ),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot surface-only Coder mailbox watcher (NEVER fulfills)."
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="Max seconds to wait (0 = forever). Exit 2 on timeout.",
    )
    parser.add_argument(
        "--if-pending",
        action="store_true",
        help="If nothing pending, exit 1 immediately (no watch).",
    )
    args = parser.parse_args(argv)

    ensure_dirs()
    interval = notify_poll_interval()
    stop = {"done": False, "result": None}
    deadline = time.monotonic() + max(0.0, args.wait) if args.wait > 0 else None

    # Immediate check
    pending = list_pending()
    if pending:
        surface_one(pending[0])
        return 0
    if args.if_pending:
        print(
            json.dumps({"event": "empty", "ok": False, "pending": 0}, ensure_ascii=False),
            flush=True,
        )
        return 1

    print(
        json.dumps(
            {
                "event": "surface_watch_start",
                "inbox": str(_inbox_dir()),
                "mode": "surface_only",
                "fulfill": False,
                "echo": False,
                "poll_s": interval,
                "wait_s": args.wait or None,
            },
            ensure_ascii=False,
        ),
        flush=True,
        file=sys.stderr,
    )

    def scan_once() -> None:
        if stop["done"]:
            return
        try:
            pending_now = list_pending()
            if pending_now:
                stop["result"] = surface_one(pending_now[0])
                stop["done"] = True
                return
            if deadline is not None and time.monotonic() >= deadline:
                stop["done"] = True
                print(
                    json.dumps(
                        {"event": "timeout_empty", "ok": False, "waited_s": args.wait},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        except Exception as e:  # noqa: BLE001
            print(
                json.dumps(
                    {
                        "event": "error",
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-400:],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
                file=sys.stderr,
            )

    def _stop() -> bool:
        if deadline is not None and time.monotonic() >= deadline and not stop["result"]:
            if not stop["done"]:
                stop["done"] = True
                print(
                    json.dumps(
                        {"event": "timeout_empty", "ok": False, "waited_s": args.wait},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        return stop["done"]

    try:
        watch_inbox_events(
            _inbox_dir(),
            on_event=scan_once,
            stop_flag=_stop,
            poll_fallback=interval,
        )
    except KeyboardInterrupt:
        stop["done"] = True
        print(
            json.dumps({"event": "interrupted", "ok": False}, ensure_ascii=False),
            flush=True,
        )
        return 130

    return 0 if stop["result"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
