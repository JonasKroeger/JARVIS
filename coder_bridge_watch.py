#!/usr/bin/env python3
"""Shared fast-watch helpers for the Coder reverse mailbox.

- write_trigger(): atomic touch of coder_bridge/TRIGGER (mtime + body)
- watch_inbox_events(): macOS kqueue push on inbox dir, else tight poll
- outbox_poll_interval() / notify_poll_interval(): ≤100–200ms defaults
"""

from __future__ import annotations

import os
import select
import time
from pathlib import Path
from typing import Callable


def root_dir() -> Path:
    override = os.environ.get("CODER_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "coder_bridge"


def trigger_path() -> Path:
    return root_dir() / "TRIGGER"


def write_trigger(*, reason: str = "pending", req_id: str | None = None) -> Path:
    """Atomically bump TRIGGER so local watchers wake instantly."""
    root = root_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = trigger_path()
    body = f"{time.time():.6f}\nreason={reason}\nid={req_id or ''}\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    try:
        os.utime(path, None)
    except OSError:
        pass
    return path


def outbox_poll_interval() -> float:
    """Server-side outbox wait sleep (default 50ms, clamp 20–200ms)."""
    raw = os.environ.get("CODER_BRIDGE_OUTBOX_POLL", "0.05").strip()
    try:
        return max(0.02, min(float(raw), 0.2))
    except ValueError:
        return 0.05


def notify_poll_interval() -> float:
    """Notifier / autofulfill fallback poll (default 100ms, clamp 50–500ms)."""
    raw = os.environ.get("CODER_BRIDGE_POLL", "0.1").strip()
    try:
        return max(0.05, min(float(raw), 0.5))
    except ValueError:
        return 0.1


def watch_inbox_events(
    inbox: Path,
    *,
    on_event: Callable[[], None],
    stop_flag: Callable[[], bool] | None = None,
    poll_fallback: float | None = None,
) -> None:
    """Block until stop_flag(); wake on inbox changes via kqueue or poll.

    Calls on_event() immediately once, then again whenever the inbox dir
    changes (or on each poll tick as a safety net).
    """
    inbox.mkdir(parents=True, exist_ok=True)
    interval = notify_poll_interval() if poll_fallback is None else max(0.05, poll_fallback)
    stop = stop_flag or (lambda: False)

    # Initial pass
    on_event()
    if stop():
        return

    use_kq = hasattr(select, "kqueue") and hasattr(select, "kevent")
    if use_kq:
        try:
            _watch_kqueue(inbox, on_event=on_event, stop=stop, interval=interval)
            return
        except OSError:
            pass  # fall through to poll

    while not stop():
        time.sleep(interval)
        if stop():
            return
        on_event()


def _watch_kqueue(
    inbox: Path,
    *,
    on_event: Callable[[], None],
    stop: Callable[[], bool],
    interval: float,
) -> None:
    fd = os.open(str(inbox), os.O_RDONLY)
    kq = select.kqueue()
    try:
        flags = (
            getattr(select, "KQ_NOTE_WRITE", 0)
            | getattr(select, "KQ_NOTE_EXTEND", 0)
            | getattr(select, "KQ_NOTE_DELETE", 0)
            | getattr(select, "KQ_NOTE_RENAME", 0)
            | getattr(select, "KQ_NOTE_ATTRIB", 0)
        )
        ev = select.kevent(
            fd,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
            fflags=flags,
        )
        kq.control([ev], 0)
        # Also watch TRIGGER for cross-process wake without inbox churn
        trigger = trigger_path()
        trigger.parent.mkdir(parents=True, exist_ok=True)
        if not trigger.exists():
            write_trigger(reason="init")
        tfd = os.open(str(trigger), os.O_RDONLY)
        try:
            tev = select.kevent(
                tfd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=flags,
            )
            kq.control([tev], 0)
            while not stop():
                # Timeout keeps heartbeat / stop_flag responsive
                events = kq.control(None, 4, interval)
                if stop():
                    return
                if events:
                    on_event()
                else:
                    # Safety poll tick even if no vnode event
                    on_event()
        finally:
            os.close(tfd)
    finally:
        kq.close()
        os.close(fd)
