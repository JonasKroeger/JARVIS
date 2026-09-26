#!/usr/bin/env python3
"""Coder-side worker for the reverse mailbox (runs on Jonas's Mac).

Polls ~/JARVIS/coder_bridge/inbox for pending requests and writes replies to
outbox. Coder (remote box) drives this via Shell on machineId
01c88f7a-b822-4887-82b2-33a6f8c6c00c.

Modes:
  --once --reply TEXT   Answer the oldest pending request with TEXT, then exit.
  --once --echo         Answer oldest with a short spoken ack, then exit.
  --echo                Poll forever; echo every request.
  --once                Print oldest request as one JSON line to stdout; wait for
                        a reply line on stdin (or use --reply / --echo).
  (default)             Poll forever; for each request print JSON line to stdout
                        and read one reply line from stdin.

Env:
  CODER_BRIDGE_DIR   mailbox root (default: <repo>/coder_bridge)
  CODER_BRIDGE_POLL  poll interval seconds (default 0.25)

LIVE MODE: do not run --echo. Prefer fulfill_coder_reply.py and
coder_bridge_notify.py (started by start_coder_bridge.sh).
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


def touch_heartbeat() -> None:
    """Mark worker alive so /health can report worker_alive."""
    ensure_dirs()
    hb = _root_dir() / "worker.heartbeat"
    try:
        hb.write_text(f"{time.time()}\n", encoding="utf-8")
    except OSError:
        pass


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
    """Short spoken-friendly ack — never include ids, source, or raw message dump."""
    _ = req  # request available if a future echo wants a brief paraphrase
    return "Coder received your message."


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
        help="Reply with a short spoken-friendly ack (no ids/metadata)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="With --once: wait up to N seconds for a pending request",
    )
    args = parser.parse_args(argv)

    ensure_dirs()
    touch_heartbeat()
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
            touch_heartbeat()
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
        touch_heartbeat()
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


def _daemonize(pidfile: Path, logfile: Path) -> None:
    """Double-fork detach (Unix). Parent exits after writing pidfile."""
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



if __name__ == "__main__":
    # Optional daemon wrapper so continuous --echo survives shell exit.
    if "--daemon" in sys.argv:
        argv = [a for a in sys.argv[1:] if a != "--daemon"]
        pidfile = Path(
            os.environ.get(
                "CODER_BRIDGE_WORKER_PID",
                str(Path(__file__).resolve().parent / "coder_bridge_worker.pid"),
            )
        )
        logfile = Path(
            os.environ.get(
                "CODER_BRIDGE_WORKER_LOG",
                str(Path(__file__).resolve().parent / "coder-bridge-worker.log"),
            )
        )
        # Extract optional --pidfile/--logfile from argv
        cleaned: list[str] = []
        i = 0
        while i < len(argv):
            if argv[i] == "--pidfile" and i + 1 < len(argv):
                pidfile = Path(argv[i + 1])
                i += 2
                continue
            if argv[i] == "--logfile" and i + 1 < len(argv):
                logfile = Path(argv[i + 1])
                i += 2
                continue
            cleaned.append(argv[i])
            i += 1
        _daemonize(pidfile, logfile)
        raise SystemExit(main(cleaned))
    raise SystemExit(main())
