#!/usr/bin/env python3
"""One-shot surface watcher for the shared room (NEVER fulfills).

Waits until a pending user/jarvis handoff exists, writes SURFACED.json,
prints JSON, exits. Parent must answer via room_reply.py (+ group SendToAgent).

  .venv/bin/python coder_room_surface.py --wait 600
  .venv/bin/python coder_room_surface.py --if-pending
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

GROUP_ID = "832e7e66-c400-4d70-ae0d-88ae44177912"


def _base() -> str:
    return (
        os.environ.get("CODER_ROOM_URL", "").strip().rstrip("/")
        or f"http://127.0.0.1:{os.environ.get('CODER_ROOM_PORT', '8767')}"
    )


def _root() -> Path:
    override = os.environ.get("CODER_ROOM_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_room"


def _get_pending() -> dict[str, Any]:
    url = f"{_base()}/pending"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _watch_trigger(timeout: float) -> dict[str, Any] | None:
    """Poll PENDING (+ TRIGGER mtime) until a handoff appears or timeout."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    trigger = root / "TRIGGER"
    deadline = time.monotonic() + timeout if timeout > 0 else None
    last_mtime = trigger.stat().st_mtime if trigger.exists() else 0.0
    interval = float(os.environ.get("CODER_ROOM_POLL", "0.15"))
    interval = max(0.05, min(interval, 1.0))

    while True:
        try:
            data = _get_pending()
        except Exception:  # noqa: BLE001
            data = {"count": 0, "pending": []}
        pending = list(data.get("pending") or [])
        if pending:
            return pending[0]
        if deadline is not None and time.monotonic() >= deadline:
            return None
        # kqueue-ish: react to TRIGGER mtime bumps quickly
        try:
            if trigger.exists():
                m = trigger.stat().st_mtime
                if m != last_mtime:
                    last_mtime = m
                    continue
        except OSError:
            pass
        time.sleep(interval)


def surface_one(req: dict[str, Any]) -> dict[str, Any]:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    body = {
        "surfaced_at": time.time(),
        "id": req.get("id"),
        "role": req.get("role"),
        "text": req.get("text"),
        "created_at": req.get("created_at"),
        "status": "awaiting_parent_fulfill",
        "group_id": GROUP_ID,
        "fulfill_hint": (
            f'cd ~/JARVIS && .venv/bin/python room_reply.py '
            f'--id {req.get("id")} --reply "YOUR ANSWER"'
        ),
        "group_hint": f"Also SendToAgent group {GROUP_ID}",
    }
    snap = root / "SURFACED.json"
    tmp = snap.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(snap)
    with open(root / "surface.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event": "surfaced", **{k: body[k] for k in ("id", "text")}}, ensure_ascii=False) + "\n")
    result = {
        "event": "coder_room_surfaced",
        "ok": True,
        "id": req.get("id"),
        "role": req.get("role"),
        "text": req.get("text"),
        "group_id": GROUP_ID,
        "action": "HOLD — do not auto-reply; parent must room_reply.py + SendToAgent",
        "fulfill_hint": body["fulfill_hint"],
        "group_hint": body["group_hint"],
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Surface-only shared-room watcher (never fulfills).")
    parser.add_argument("--wait", type=float, default=0.0, help="Max seconds (0=forever). Exit 2 on timeout.")
    parser.add_argument("--if-pending", action="store_true", help="Exit 1 immediately if nothing pending.")
    args = parser.parse_args(argv)

    try:
        data = _get_pending()
    except urllib.error.URLError as e:
        print(json.dumps({"event": "error", "ok": False, "error": f"room unreachable: {e.reason}"}), flush=True)
        return 1

    pending = list(data.get("pending") or [])
    if pending:
        surface_one(pending[0])
        return 0
    if args.if_pending:
        print(json.dumps({"event": "empty", "ok": False, "pending": 0}), flush=True)
        return 1

    print(
        json.dumps(
            {
                "event": "surface_watch_start",
                "mode": "surface_only",
                "fulfill": False,
                "echo": False,
                "group_id": GROUP_ID,
                "wait_s": args.wait or None,
            },
            ensure_ascii=False,
        ),
        flush=True,
        file=sys.stderr,
    )
    found = _watch_trigger(args.wait)
    if not found:
        print(json.dumps({"event": "timeout_empty", "ok": False, "waited_s": args.wait}), flush=True)
        return 2
    surface_one(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
