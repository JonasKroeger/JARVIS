#!/usr/bin/env bash
# Start the Coder reverse mailbox on 127.0.0.1:8766 in LIVE mode:
#   - mailbox daemon (no in-process echo)
#   - live notifier (PENDING.json + optional CODER_BRIDGE_NOTIFY_URL webhook)
# Echo worker is OFF by default. Set CODER_BRIDGE_MODE=echo and
# CODER_BRIDGE_ECHO_WORKER=1 only for offline smoke.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${CODER_BRIDGE_LOG:-$ROOT/coder-bridge.log}"
PIDFILE="${CODER_BRIDGE_PID:-$ROOT/coder_bridge.pid}"
NOTIFY_LOG="${CODER_BRIDGE_NOTIFY_LOG:-$ROOT/coder-bridge-notify.log}"
NOTIFY_PIDFILE="${CODER_BRIDGE_NOTIFY_PID:-$ROOT/coder_bridge_notify.pid}"
WORKER_LOG="${CODER_BRIDGE_WORKER_LOG:-$ROOT/coder-bridge-worker.log}"
WORKER_PIDFILE="${CODER_BRIDGE_WORKER_PID:-$ROOT/coder_bridge_worker.pid}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

# Live is the product default.
export CODER_BRIDGE_MODE="${CODER_BRIDGE_MODE:-live}"
export CODER_BRIDGE_AUTOFULFILL="${CODER_BRIDGE_AUTOFULFILL:-0}"
export CODER_BRIDGE_AUTO="${CODER_BRIDGE_AUTO:-}"  # must stay unset/off in live
if [[ "$CODER_BRIDGE_MODE" == "live" ]]; then
  export CODER_BRIDGE_TIMEOUT="${CODER_BRIDGE_TIMEOUT:-90}"
  # Echo worker stays off in live mode unless explicitly forced.
  export CODER_BRIDGE_ECHO_WORKER="${CODER_BRIDGE_ECHO_WORKER:-0}"
else
  export CODER_BRIDGE_ECHO_WORKER="${CODER_BRIDGE_ECHO_WORKER:-1}"
fi


stop_autofulfill() {
  # Timing-test fulfiller must NEVER run in live product path.
  pkill -f "coder_bridge_autofulfill" 2>/dev/null || true
  AF_PIDFILE="${CODER_BRIDGE_AUTOFULFILL_PID:-$ROOT/coder_bridge_autofulfill.pid}"
  if [[ -f "$AF_PIDFILE" ]]; then
    aold="$(cat "$AF_PIDFILE" 2>/dev/null || true)"
    if [[ -n "${aold}" ]] && kill -0 "$aold" 2>/dev/null; then
      echo "stopping autofulfill pid=$aold" >&2
      kill "$aold" 2>/dev/null || true
      sleep 0.2
      kill -9 "$aold" 2>/dev/null || true
    fi
    rm -f "$AF_PIDFILE"
  fi
  # Hard off unless explicitly forced for offline timing tests.
  export CODER_BRIDGE_AUTOFULFILL="${CODER_BRIDGE_AUTOFULFILL:-0}"
  if [[ ! "${CODER_BRIDGE_AUTOFULFILL}" =~ ^(0|false|False|off|OFF)$ ]]; then
    echo "WARNING: CODER_BRIDGE_AUTOFULFILL=${CODER_BRIDGE_AUTOFULFILL} but start script will NOT launch it (use coder_bridge_autofulfill.py manually for timing tests only)" >&2
  fi
  echo "autofulfill killed/disabled (CODER_BRIDGE_AUTOFULFILL=0)" >&2
}

stop_echo_worker() {
  if [[ -f "$WORKER_PIDFILE" ]]; then
    wold="$(cat "$WORKER_PIDFILE" 2>/dev/null || true)"
    if [[ -n "${wold}" ]] && kill -0 "$wold" 2>/dev/null; then
      # Only kill if it looks like the echo worker we own.
      echo "stopping previous coder-worker pid=$wold" >&2
      kill "$wold" 2>/dev/null || true
      sleep 0.3
      kill -9 "$wold" 2>/dev/null || true
    fi
    rm -f "$WORKER_PIDFILE"
  fi
}

start_mailbox() {
  if [[ -f "$PIDFILE" ]]; then
    old="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${old}" ]] && kill -0 "$old" 2>/dev/null; then
      echo "coder-mailbox already running pid=$old (restarting for live mode)" >&2
      kill "$old" 2>/dev/null || true
      sleep 0.4
      kill -9 "$old" 2>/dev/null || true
      rm -f "$PIDFILE"
    else
      rm -f "$PIDFILE"
    fi
  fi
  mkdir -p "$ROOT/coder_bridge/inbox" "$ROOT/coder_bridge/outbox" "$ROOT/coder_bridge/replies"
  "$PY" "$ROOT/coder_bridge_server.py" --daemon --pidfile "$PIDFILE" --logfile "$LOG"
  sleep 0.4
  if [[ ! -f "$PIDFILE" ]] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "failed to start coder-mailbox; see $LOG" >&2
    exit 1
  fi
  echo "coder-mailbox started pid=$(cat "$PIDFILE") mode=$CODER_BRIDGE_MODE timeout=${CODER_BRIDGE_TIMEOUT}s log=$LOG"
}

start_live_notifier() {
  if [[ "$CODER_BRIDGE_MODE" != "live" ]]; then
    echo "live notifier skipped (CODER_BRIDGE_MODE=$CODER_BRIDGE_MODE)" >&2
    return 0
  fi
  if [[ -f "$NOTIFY_PIDFILE" ]]; then
    nold="$(cat "$NOTIFY_PIDFILE" 2>/dev/null || true)"
    if [[ -n "${nold}" ]] && kill -0 "$nold" 2>/dev/null; then
      echo "stopping previous live-notifier pid=$nold" >&2
      kill "$nold" 2>/dev/null || true
      sleep 0.3
      kill -9 "$nold" 2>/dev/null || true
    fi
    rm -f "$NOTIFY_PIDFILE"
  fi
  "$PY" "$ROOT/coder_bridge_notify.py" --daemon \
    --pidfile "$NOTIFY_PIDFILE" --logfile "$NOTIFY_LOG"
  sleep 0.4
  if [[ ! -f "$NOTIFY_PIDFILE" ]] || ! kill -0 "$(cat "$NOTIFY_PIDFILE")" 2>/dev/null; then
    echo "failed to start live-notifier; see $NOTIFY_LOG" >&2
    exit 1
  fi
  if [[ -n "${CODER_BRIDGE_NOTIFY_URL:-}" ]]; then
    echo "live-notifier started pid=$(cat "$NOTIFY_PIDFILE") webhook=set log=$NOTIFY_LOG"
  else
    echo "live-notifier started pid=$(cat "$NOTIFY_PIDFILE") webhook=UNSET (PENDING.json only) log=$NOTIFY_LOG"
  fi
}

start_echo_worker() {
  if [[ "${CODER_BRIDGE_ECHO_WORKER}" =~ ^(0|false|False|off|OFF)$ ]]; then
    echo "echo worker skipped (CODER_BRIDGE_ECHO_WORKER=${CODER_BRIDGE_ECHO_WORKER})" >&2
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
  "$PY" "$ROOT/coder_bridge_worker.py" --daemon --echo \
    --pidfile "$WORKER_PIDFILE" --logfile "$WORKER_LOG"
  sleep 0.4
  if [[ ! -f "$WORKER_PIDFILE" ]] || ! kill -0 "$(cat "$WORKER_PIDFILE")" 2>/dev/null; then
    echo "failed to start coder-worker; see $WORKER_LOG" >&2
    exit 1
  fi
  echo "coder-worker (echo) started pid=$(cat "$WORKER_PIDFILE") log=$WORKER_LOG"
}

stop_echo_worker
stop_autofulfill
start_mailbox
start_live_notifier
start_echo_worker
echo "health: curl -s http://127.0.0.1:${CODER_BRIDGE_PORT:-8766}/health"
echo "pending: curl -s http://127.0.0.1:${CODER_BRIDGE_PORT:-8766}/pending"
echo "fulfill: .venv/bin/python fulfill_coder_reply.py --pending"
