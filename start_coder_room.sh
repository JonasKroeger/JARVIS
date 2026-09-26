#!/usr/bin/env bash
# Start the shared JARVIS ↔ Coder room on 127.0.0.1:8767 (orb transport).
# Surface-only — NEVER starts autofulfill / echo workers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${CODER_ROOM_LOG:-$ROOT/coder-room.log}"
PIDFILE="${CODER_ROOM_PID:-$ROOT/coder_room.pid}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export CODER_ROOM_PORT="${CODER_ROOM_PORT:-8767}"
# Hard-disable legacy autofulfill paths
export CODER_BRIDGE_AUTOFULFILL=0
export CODER_BRIDGE_ECHO_WORKER=0
export CODER_BRIDGE_MODE="${CODER_BRIDGE_MODE:-live}"

# Kill any leftover autofulfill / echo workers
pkill -f "coder_bridge_autofulfill" 2>/dev/null || true
pkill -f "coder_bridge_worker.py" 2>/dev/null || true

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "${old}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "stopping previous coder-room pid=$old" >&2
    kill "$old" 2>/dev/null || true
    sleep 0.3
    kill -9 "$old" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi

mkdir -p "$ROOT/coder_room"
"$PY" "$ROOT/room_server.py" --daemon --pidfile "$PIDFILE" --logfile "$LOG"
sleep 0.4
if [[ ! -f "$PIDFILE" ]] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "failed to start coder-room; see $LOG" >&2
  exit 1
fi
echo "coder-room started pid=$(cat "$PIDFILE") port=$CODER_ROOM_PORT log=$LOG"
echo "health: curl -s http://127.0.0.1:${CODER_ROOM_PORT}/health"
echo "pending: curl -s http://127.0.0.1:${CODER_ROOM_PORT}/pending"
echo "fulfill: .venv/bin/python room_reply.py --reply TEXT"
