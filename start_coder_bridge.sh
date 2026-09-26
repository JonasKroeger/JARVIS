#!/usr/bin/env bash
# Start the Coder reverse mailbox server (daemon) on 127.0.0.1:8766
# and an echo worker so ask_coder does not hang with no fulfiller.
# Independent of the Qt JARVIS app. Uses Python double-fork --daemon.
# For live Coder (Grok Bot) replies, stop the echo worker and drive
# coder_bridge_worker.py from the Coder side (--once --reply / stdin).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${CODER_BRIDGE_LOG:-$ROOT/coder-bridge.log}"
PIDFILE="${CODER_BRIDGE_PID:-$ROOT/coder_bridge.pid}"
WORKER_LOG="${CODER_BRIDGE_WORKER_LOG:-$ROOT/coder-bridge-worker.log}"
WORKER_PIDFILE="${CODER_BRIDGE_WORKER_PID:-$ROOT/coder_bridge_worker.pid}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

start_mailbox() {
  if [[ -f "$PIDFILE" ]]; then
    old="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${old}" ]] && kill -0 "$old" 2>/dev/null; then
      echo "coder-mailbox already running pid=$old" >&2
      return 0
    fi
    rm -f "$PIDFILE"
  fi
  mkdir -p "$ROOT/coder_bridge/inbox" "$ROOT/coder_bridge/outbox"
  "$PY" "$ROOT/coder_bridge_server.py" --daemon --pidfile "$PIDFILE" --logfile "$LOG"
  sleep 0.4
  if [[ ! -f "$PIDFILE" ]] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "failed to start coder-mailbox; see $LOG" >&2
    exit 1
  fi
  echo "coder-mailbox started pid=$(cat "$PIDFILE") log=$LOG"
}

start_echo_worker() {
  # Skip if CODER_BRIDGE_ECHO_WORKER=0 (Coder will fulfill manually).
  if [[ "${CODER_BRIDGE_ECHO_WORKER:-1}" =~ ^(0|false|False|off|OFF)$ ]]; then
    echo "echo worker skipped (CODER_BRIDGE_ECHO_WORKER=0)" >&2
    return 0
  fi
  if [[ -f "$WORKER_PIDFILE" ]]; then
    wold="$(cat "$WORKER_PIDFILE" 2>/dev/null || true)"
    if [[ -n "${wold}" ]] && kill -0 "$wold" 2>/dev/null; then
      echo "coder-worker already running pid=$wold" >&2
      return 0
    fi
    rm -f "$WORKER_PIDFILE"
  fi
  # Double-fork daemon (survives shell exit); echo acknowledges every inbox item.
  "$PY" "$ROOT/coder_bridge_worker.py" --daemon --echo \
    --pidfile "$WORKER_PIDFILE" --logfile "$WORKER_LOG"
  sleep 0.4
  if [[ ! -f "$WORKER_PIDFILE" ]] || ! kill -0 "$(cat "$WORKER_PIDFILE")" 2>/dev/null; then
    echo "failed to start coder-worker; see $WORKER_LOG" >&2
    exit 1
  fi
  echo "coder-worker (echo) started pid=$(cat "$WORKER_PIDFILE") log=$WORKER_LOG"
}

start_mailbox
start_echo_worker
echo "health: curl -s http://127.0.0.1:${CODER_BRIDGE_PORT:-8766}/health"
