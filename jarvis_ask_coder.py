#!/usr/bin/env python3
"""JARVIS → Coder client via shared room (127.0.0.1:8767).

Posts a user handoff into the room and waits (SSE) for an explicit coder reply.
NEVER invents answers. Parent fulfills with room_reply.py (+ group SendToAgent).

  python jarvis_ask_coder.py "Tell Coder what is 2+2"

Env:
  CODER_ROOM_URL / CODER_ROOM_PORT   default http://127.0.0.1:8767
  CODER_ROOM_TIMEOUT                 default 90

Legacy CODER_URL :8766 mailbox is deprecated and ignored for the happy path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _base() -> str:
    explicit = os.environ.get("CODER_ROOM_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    port = os.environ.get("CODER_ROOM_PORT", "8767").strip() or "8767"
    return f"http://127.0.0.1:{port}"


def _post_json(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_coder(base: str, after_id: str, handoff_id: str, timeout: float) -> str:
    """Poll /messages for role=coder after handoff (SSE via urllib is awkward)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = _get_json(f"{base}/messages?after_id={after_id}&limit=50", timeout=5.0)
            for msg in data.get("messages") or []:
                if not isinstance(msg, dict) or msg.get("role") != "coder":
                    continue
                if msg.get("reply_to") and str(msg.get("reply_to")) != str(handoff_id):
                    continue
                return str(msg.get("text") or "")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.15)
    raise TimeoutError(
        f"no coder reply within {timeout:.0f}s "
        "(fulfill: .venv/bin/python room_reply.py --reply TEXT)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post to shared room and wait for Coder reply.")
    parser.add_argument("prompt", nargs="?", default="", help="Message for Coder")
    parser.add_argument("--demo", action="store_true", help="Mock reply without contacting room")
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("CODER_ROOM_TIMEOUT", os.environ.get("CODER_BRIDGE_TIMEOUT", "90"))),
    )
    args = parser.parse_args(argv)

    prompt = (args.prompt or "").strip()
    if args.demo:
        print(f"[demo] Coder would reply to: {prompt or '(demo)'}")
        return 0
    if not prompt:
        print('usage: jarvis_ask_coder.py "prompt here"', file=sys.stderr)
        return 1

    base = _base()
    try:
        posted = _post_json(
            f"{base}/messages",
            {"role": "user", "text": prompt, "meta": {"source": "jarvis_ask_coder", "awaiting_coder": True}},
            timeout=10.0,
        )
        handoff = posted.get("message") or {}
        handoff_id = str(handoff.get("id") or "")
        if not handoff_id:
            print("room post missing id", file=sys.stderr)
            return 1
        reply = _wait_coder(base, handoff_id, handoff_id, args.timeout)
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"HTTP {e.code}: {detail or e.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"connection failed: {e.reason}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
