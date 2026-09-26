#!/usr/bin/env bash
# Start the Coder reverse mailbox server (daemon) on 127.0.0.1:8766.
# Independent of the Qt JARVIS app. Uses Python double-fork --daemon.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${CODER_BRIDGE_LOG:-$ROOT/coder-bridge.log}"
PIDFILE="${CODER_BRIDGE_PID:-$ROOT/coder_bridge.pid}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "${old}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "coder-mailbox already running pid=$old" >&2
    echo "log: $LOG" >&2
    exit 0
  fi
  rm -f "$PIDFILE"
fi

mkdir -p "$ROOT/coder_bridge/inbox" "$ROOT/coder_bridge/outbox"
# Double-fork inside Python so the listener survives the parent shell exiting.
"$PY" "$ROOT/coder_bridge_server.py" --daemon --pidfile "$PIDFILE" --logfile "$LOG"
sleep 0.4
if [[ ! -f "$PIDFILE" ]] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "failed to start coder-mailbox; see $LOG" >&2
  exit 1
fi
echo "coder-mailbox started pid=$(cat "$PIDFILE") log=$LOG"
echo "health: curl -s http://127.0.0.1:${CODER_BRIDGE_PORT:-8766}/health"
