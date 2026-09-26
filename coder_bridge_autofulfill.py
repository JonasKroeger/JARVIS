#!/usr/bin/env python3
"""Timing-test / demo auto-fulfiller for the Coder reverse mailbox.

Watches inbox via kqueue (+ ≤100ms poll fallback) and writes an outbox reply
within ~100ms of a pending request. NOT for production live Coder answers —
use fulfill_coder_reply.py for real replies. This isolates pure bridge RTT.

Examples:
  # Measure pure bridge latency (canned reply)
  .venv/bin/python coder_bridge_autofulfill.py --reply "Four." --once --wait 30

  # Background daemon for a timing window
  .venv/bin/python coder_bridge_autofulfill.py --daemon --reply "Two plus two is four."

  # Echo message back (still instant — no LLM)
  .venv/bin/python coder_bridge_autofulfill.py --echo-message --once --wait 10

Env:
  CODER_BRIDGE_DIR    mailbox root
  CODER_BRIDGE_POLL   fallback poll seconds (default 0.1)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from coder_bridge_watch import notify_poll_interval, watch_inbox_events, write_trigger
from fulfill_coder_reply import list_pending, write_reply, ensure_dirs, _inbox_dir


def _daemonize(pidfile: Path, logfile: Path) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fast auto-fulfill pending Coder mailbox requests (timing tests)."
    )
    parser.add_argument(
        "--reply",
        default="Four.",
        help='Canned reply text (default: "Four.")',
    )
    parser.add_argument(
        "--echo-message",
        action="store_true",
        help="Reply with the pending message text instead of --reply",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fulfill one request then exit",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=60.0,
        help="With --once: max seconds to wait for a pending request (default 60)",
    )
    parser.add_argument("--daemon", action="store_true", help="Double-fork background")
    parser.add_argument(
        "--pidfile",
        default=os.environ.get(
            "CODER_BRIDGE_AUTOFULFILL_PID",
            str(Path(__file__).resolve().parent / "coder_bridge_autofulfill.pid"),
        ),
    )
    parser.add_argument(
        "--logfile",
        default=os.environ.get(
            "CODER_BRIDGE_AUTOFULFILL_LOG",
            str(Path(__file__).resolve().parent / "coder-bridge-autofulfill.log"),
        ),
    )
    args = parser.parse_args(argv)

    if args.daemon:
        _daemonize(Path(args.pidfile), Path(args.logfile))

    ensure_dirs()
    interval = notify_poll_interval()
    stop = {"done": False, "answered": 0}
    deadline = time.monotonic() + max(0.0, args.wait) if args.once else None

    print(
        json.dumps(
            {
                "event": "autofulfill_start",
                "inbox": str(_inbox_dir()),
                "reply": None if args.echo_message else args.reply,
                "echo_message": bool(args.echo_message),
                "once": bool(args.once),
                "poll_s": interval,
                "watch": "kqueue+poll",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    def scan_once() -> None:
        if stop["done"]:
            return
        try:
            pending = list_pending()
            if not pending:
                if deadline is not None and time.monotonic() >= deadline:
                    stop["done"] = True
                    print(
                        json.dumps(
                            {"event": "timeout_empty", "waited_s": args.wait},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                return
            req = pending[0]
            rid = str(req["id"])
            seen_at = time.monotonic()
            if args.echo_message:
                reply = str(req.get("message") or "").strip() or args.reply
            else:
                reply = args.reply
            out = write_reply(
                rid,
                reply,
                extra={"source": "autofulfill", "fulfill_latency_hint_s": round(time.monotonic() - seen_at, 4)},
            )
            write_trigger(reason="autofilled", req_id=rid)
            stop["answered"] += 1
            print(
                json.dumps(
                    {
                        "event": "answered",
                        "id": rid,
                        "outbox": str(out),
                        "reply_preview": reply[:120],
                        "detect_to_write_s": round(time.monotonic() - seen_at, 4),
                        "message_preview": str(req.get("message") or "")[:80],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.once:
                stop["done"] = True
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
        if deadline is not None and time.monotonic() >= deadline and stop["answered"] == 0:
            stop["done"] = True
            print(
                json.dumps({"event": "timeout_empty", "waited_s": args.wait}, ensure_ascii=False),
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

    return 0 if stop["answered"] else (2 if args.once else 0)


if __name__ == "__main__":
    raise SystemExit(main())
