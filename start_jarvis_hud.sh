#!/bin/bash
# Silent launch of the JARVIS HUD via the .app bundle (Dock shows "JARVIS").
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="${JARVIS_APP:-$HOME/Applications/JARVIS.app}"
DIST="$ROOT/dist/JARVIS.app"
LOG="$ROOT/jarvis-debug.log"
PIDFILE="$ROOT/jarvis.pid"

if [[ ! -x "$APP/Contents/MacOS/JARVIS" ]]; then
  if [[ -x "$DIST/Contents/MacOS/JARVIS" ]]; then
    APP="$DIST"
  else
    echo "Building JARVIS.app…"
    "$ROOT/packaging/build_jarvis_app.sh"
    APP="$HOME/Applications/JARVIS.app"
  fi
fi

# Stop a previous HUD instance (never touch room_server :8767).
if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "${old}" ]] && kill -0 "$old" 2>/dev/null; then
    cmd="$(ps -p "$old" -o args= 2>/dev/null || true)"
    if echo "$cmd" | grep -qiE 'app\.py|boot\.py|JARVIS\.app|/MacOS/JARVIS'; then
      kill "$old" 2>/dev/null || true
      sleep 0.4
      kill -9 "$old" 2>/dev/null || true
    fi
  fi
fi
pkill -f "/Users/jonaskroeger/JARVIS/app.py" 2>/dev/null || true
pkill -f "JARVIS.app/Contents/Resources/boot.py" 2>/dev/null || true
pkill -f "Applications/JARVIS.app/Contents/MacOS/JARVIS" 2>/dev/null || true

{
  echo "==== JARVIS .app launch $(date) app=$APP ===="
} >> "$LOG"

open -n -a "$APP"

for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 0.25
  pid="$(pgrep -nf "$APP/Contents/MacOS/JARVIS" || true)"
  if [[ -z "$pid" ]]; then
    pid="$(pgrep -nf 'Applications/JARVIS.app/Contents/MacOS/JARVIS' || true)"
  fi
  if [[ -n "$pid" ]]; then
    echo "$pid" > "$PIDFILE"
    echo "JARVIS started pid=$pid via $APP"
    exit 0
  fi
done
echo "JARVIS launch issued (pid not yet visible); check $LOG" >&2
exit 0
