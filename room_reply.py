#!/usr/bin/env python3
"""Explicit Coder fulfill into the shared room (NEVER auto-called).

Parent Coder must:
  1) Run this on the Mac (unblocks orb SSE wait)
  2) ALSO SendToAgent into Grok Bot group 832e7e66-c400-4d70-ae0d-88ae44177912
     (Mac cannot post to the group)

Examples:
  .venv/bin/python room_reply.py --pending
  .venv/bin/python room_reply.py --reply "Two plus two is four."
  .venv/bin/python room_reply.py --id <uuid> --reply "Done."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

GROUP_ID = "832e7e66-c400-4d70-ae0d-88ae44177912"
DEFAULT_BASE = "http://127.0.0.1:8767"


def _base() -> str:
    return (
        os.environ.get("CODER_ROOM_URL", "").strip().rstrip("/")
        or f"http://127.0.0.1:{os.environ.get('CODER_ROOM_PORT', '8767')}"
    )


def _get(path: str, timeout: float = 10.0) -> dict[str, Any]:
    url = f"{_base()}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_message(role: str, text: str, reply_to: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"role": role, "text": text}
    if reply_to:
        body["reply_to"] = reply_to
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{_base()}/messages",
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post an explicit Coder reply into the shared room (no autofulfill)."
    )
    parser.add_argument("--pending", action="store_true", help="List pending handoffs")
    parser.add_argument("--id", default=None, help="Handoff message id to answer")
    parser.add_argument("--reply", default=None, help="Coder reply text (spoken by orb)")
    parser.add_argument(
        "--no-remind-group",
        action="store_true",
        help="Skip printing the SendToAgent group reminder",
    )
    args = parser.parse_args(argv)

    try:
        if args.pending:
            data = _get("/pending")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0 if data.get("count") else 2

        pending = _get("/pending")
        items = list(pending.get("pending") or [])
        target: dict[str, Any] | None = None
        if args.id:
            for p in items:
                if str(p.get("id")) == str(args.id):
                    target = p
                    break
            if target is None:
                # Allow replying to a known id even if already closed
                target = {"id": args.id, "text": "(direct)"}
        elif items:
            target = items[0]
        else:
            print("no pending room handoffs", file=sys.stderr)
            return 2

        if args.reply is not None:
            reply = args.reply
        else:
            data = sys.stdin.read()
            if not data:
                print("empty reply (stdin closed)", file=sys.stderr)
                return 1
            reply = data[:-1] if data.endswith("\n") and data.count("\n") == 1 else data

        reply = reply.strip()
        if not reply:
            print("empty reply", file=sys.stderr)
            return 1

        req_id = str(target["id"])
        result = _post_message("coder", reply, reply_to=req_id)
        msg = (result.get("message") or {}) if isinstance(result, dict) else {}
        out = {
            "event": "room_answered",
            "ok": True,
            "id": msg.get("id"),
            "reply_to": req_id,
            "reply_len": len(reply),
            "reply_preview": reply[:120],
            "group_id": GROUP_ID,
            "group_reminder": (
                f"REQUIRED: also SendToAgent into Grok Bot group {GROUP_ID} "
                f'with short FYI / same reply text (Mac cannot post to group).'
            ),
        }
        print(json.dumps(out, ensure_ascii=False), flush=True)
        if not args.no_remind_group:
            print(
                f"\n→ Parent: SendToAgent channel={GROUP_ID} "
                f"message={reply[:200]!r}",
                file=sys.stderr,
            )
        return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"HTTP {e.code}: {detail or e.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"connection failed: {e.reason} (is room_server running on 8767?)", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
