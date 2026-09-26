#!/usr/bin/env python3
"""JARVIS → Coder client (reverse bridge).

Send a prompt to the local Coder mailbox server and print the reply.

  python jarvis_ask_coder.py "your prompt here"

Env:
  CODER_URL              default http://127.0.0.1:8766/chat
  CODER_BRIDGE_API_KEY   optional Bearer token (only if server has the same key)

Flags:
  --demo   print a mock reply without contacting the server (offline smoke)

Exit 0 on success, 1 on error. Reply text only on stdout; diagnostics on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8766/chat"


def _post(url: str, message: str, api_key: str | None, source: str, timeout: float) -> str:
    body = json.dumps(
        {
            "message": message,
            "context": {"source": source},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or "reply" not in data:
        raise RuntimeError(f"unexpected response: {raw[:200]!r}")
    return str(data["reply"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send a prompt to local Coder mailbox and print the reply."
    )
    parser.add_argument("prompt", nargs="?", default="", help="Message for Coder")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Print a mock reply without contacting the server",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("CODER_URL", DEFAULT_URL),
        help=f"Coder mailbox URL (default {DEFAULT_URL})",
    )
    parser.add_argument(
        "--source",
        default="jarvis",
        help="context.source tag (default: jarvis)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("CODER_BRIDGE_TIMEOUT", "90")),
        help="HTTP timeout seconds (default 90 / CODER_BRIDGE_TIMEOUT)",
    )
    args = parser.parse_args(argv)

    prompt = (args.prompt or "").strip()
    if args.demo:
        if not prompt:
            prompt = "(demo)"
        print(f"[demo] Coder would reply to: {prompt}")
        return 0

    if not prompt:
        print('usage: jarvis_ask_coder.py "prompt here"', file=sys.stderr)
        return 1

    api_key = os.environ.get("CODER_BRIDGE_API_KEY", "").strip() or None
    try:
        reply = _post(args.url, prompt, api_key, args.source, args.timeout)
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
