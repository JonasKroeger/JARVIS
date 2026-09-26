#!/usr/bin/env python3
"""Live-mode notifier for the Coder reverse mailbox (no echo / no auto-reply).

Watches coder_bridge/inbox. When a pending request appears:
  1. Updates coder_bridge/PENDING.json (aggressive poll snapshot)
  2. Optionally POSTs JSON to CODER_BRIDGE_NOTIFY_URL (Grok Bot webhook routine)
  3. Never writes an outbox reply — Coder must fulfill via fulfill_coder_reply.py
     or by dropping coder_bridge/replies/<id>.json

Also watches replies/ drop folder and promotes files into outbox.

Modes:
  (default)     Poll forever (foreground)
  --daemon      Double-fork background; write pidfile + logfile
  --once        Notify/promote once then exit

Env:
  CODER_BRIDGE_DIR          mailbox root
  CODER_BRIDGE_NOTIFY_URL   webhook URL (optional; pending file still updated)
  CODER_BRIDGE_POLL         fallback poll seconds (default 0.1; kqueue push on macOS)
  CODER_BRIDGE_NOTIFY_RETRY seconds between re-notify of same id (default 30)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
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


def _outbox_dir() -> Path:
    return _root_dir() / "outbox"


def _replies_dir() -> Path:
    return _root_dir() / "replies"


def ensure_dirs() -> None:
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    _outbox_dir().mkdir(parents=True, exist_ok=True)
    _replies_dir().mkdir(parents=True, exist_ok=True)


def _poll_interval() -> float:
    return notify_poll_interval()


def _notify_url() -> str | None:
    url = os.environ.get("CODER_BRIDGE_NOTIFY_URL", "").strip()
    return url or None


def _notify_retry() -> float:
    raw = os.environ.get("CODER_BRIDGE_NOTIFY_RETRY", "30").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 30.0


def touch_heartbeat() -> None:
    ensure_dirs()
    hb = _root_dir() / "worker.heartbeat"
    try:
        hb.write_text(f"{time.time()}\n", encoding="utf-8")
    except OSError:
        pass


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


def write_pending_snapshot(pending: list[dict[str, Any]]) -> None:
    ensure_dirs()
    snap = _root_dir() / "PENDING.json"
    body = {
        "updated_at": time.time(),
        "count": len(pending),
        "mode": "live",
        "notify_url_configured": bool(_notify_url()),
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


def write_surfaced(req: dict[str, Any] | None) -> None:
    """Surface-only snapshot for parent wake (never fulfills)."""
    ensure_dirs()
    snap = _root_dir() / "SURFACED.json"
    if not req:
        body = {"surfaced_at": time.time(), "count": 0, "pending": None, "status": "idle"}
    else:
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
    log = _root_dir() / "surface.log"
    if req:
        with open(log, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "event": "surfaced",
                        "id": req.get("id"),
                        "message": req.get("message"),
                        "via": "notify_daemon",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )



def post_notify(req: dict[str, Any]) -> tuple[bool, str]:
    url = _notify_url()
    if not url:
        return False, "CODER_BRIDGE_NOTIFY_URL unset"
    payload = {
        "event": "coder_bridge_pending",
        "id": req.get("id"),
        "message": req.get("message"),
        "context": req.get("context") or {},
        "created_at": req.get("created_at"),
        "mailbox": str(_root_dir()),
        "fulfill_hint": (
            f'cd ~/JARVIS && .venv/bin/python fulfill_coder_reply.py '
            f'--id {req.get("id")} --reply "YOUR ANSWER"'
        ),
    }
    body = json.dumps(payload).encode("utf-8")
    req_http = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "jarvis-coder-bridge-notify/1"},
    )
    try:
        with urllib.request.urlopen(req_http, timeout=10) as resp:
            _ = resp.read(256)
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"URLError: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def promote_replies_drop() -> list[str]:
    """Move coder_bridge/replies/<id>.json into outbox (Coder drop path)."""
    ensure_dirs()
    promoted: list[str] = []
    for path in sorted(_replies_dir().glob("*.json")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        req_id = str(data.get("id") or path.stem)
        reply = data.get("reply")
        if reply is None:
            continue
        out = _outbox_dir() / f"{req_id}.json"
        payload = {
            "id": req_id,
            "reply": str(reply),
            "answered_at": time.time(),
            "source": "replies_drop",
        }
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out)
        inbox = _inbox_dir() / f"{req_id}.json"
        try:
            inbox.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        promoted.append(req_id)
    return promoted


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


def run_loop(*, once: bool = False) -> int:
    ensure_dirs()
    interval = _poll_interval()
    retry = _notify_retry()
    # id -> last notify monotonic time
    notified: dict[str, float] = {}
    stop = {"done": False}
    print(
        json.dumps(
            {
                "event": "notify_start",
                "inbox": str(_inbox_dir()),
                "notify_url": bool(_notify_url()),
                "mode": "live",
                "echo": False,
                "poll_s": interval,
                "watch": "kqueue+poll",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    def scan_once() -> None:
        touch_heartbeat()
        try:
            promoted = promote_replies_drop()
            for rid in promoted:
                print(
                    json.dumps({"event": "promoted_reply", "id": rid}, ensure_ascii=False),
                    flush=True,
                )
                notified.pop(rid, None)

            pending = list_pending()
            write_pending_snapshot(pending)
            write_surfaced(pending[0] if pending else None)
            if pending:
                # Instant wake for sibling watchers / parent pollers
                write_trigger(reason="pending", req_id=str(pending[0].get("id") or ""))
            live_ids = {str(p.get("id")) for p in pending}
            for old in list(notified.keys()):
                if old not in live_ids:
                    notified.pop(old, None)

            now = time.monotonic()
            for req in pending:
                rid = str(req.get("id"))
                last = notified.get(rid)
                if last is not None and (now - last) < retry:
                    continue
                ok, detail = post_notify(req)
                notified[rid] = now
                print(
                    json.dumps(
                        {
                            "event": "notify",
                            "id": rid,
                            "ok": ok,
                            "detail": detail,
                            "message_preview": str(req.get("message") or "")[:160],
                        },
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
                        "trace": traceback.format_exc()[-500:],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
                file=sys.stderr,
            )

    if once:
        scan_once()
        return 0

    def _stop() -> bool:
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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Live Coder mailbox notifier (no echo — webhook + PENDING.json)."
    )
    parser.add_argument("--once", action="store_true", help="One scan then exit")
    parser.add_argument("--daemon", action="store_true", help="Double-fork background")
    parser.add_argument(
        "--pidfile",
        default=os.environ.get(
            "CODER_BRIDGE_NOTIFY_PID",
            str(Path(__file__).resolve().parent / "coder_bridge_notify.pid"),
        ),
    )
    parser.add_argument(
        "--logfile",
        default=os.environ.get(
            "CODER_BRIDGE_NOTIFY_LOG",
            str(Path(__file__).resolve().parent / "coder-bridge-notify.log"),
        ),
    )
    args = parser.parse_args(argv)

    if args.daemon:
        _daemonize(Path(args.pidfile), Path(args.logfile))
    return run_loop(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
