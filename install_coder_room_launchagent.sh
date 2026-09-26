#!/usr/bin/env bash
# Install / reload the shared-room LaunchAgent. Retires 8766 mailbox agent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/launchd/com.jonas.jarvis.coder-room.plist"
DST="$HOME/Library/LaunchAgents/com.jonas.jarvis.coder-room.plist"
LABEL="com.jonas.jarvis.coder-room"
OLD_LABEL="com.jonas.jarvis.coder-bridge"
uid="$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DST"

# Inject optional webhook
if [[ -n "${CODER_ROOM_NOTIFY_URL:-${CODER_BRIDGE_NOTIFY_URL:-}}" ]]; then
  URL="${CODER_ROOM_NOTIFY_URL:-$CODER_BRIDGE_NOTIFY_URL}"
  /usr/libexec/PlistBuddy -c "Delete :EnvironmentVariables:CODER_ROOM_NOTIFY_URL" "$DST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:CODER_ROOM_NOTIFY_URL string $URL" "$DST"
  echo "injected CODER_ROOM_NOTIFY_URL into $DST"
fi

# Retire old 8766 mailbox LaunchAgent
launchctl bootout "gui/$uid/$OLD_LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.jonas.jarvis.coder-bridge.plist"
echo "retired LaunchAgent $OLD_LABEL"

# Kill leftover mailbox / autofulfill / echo
pkill -f "coder_bridge_server.py" 2>/dev/null || true
pkill -f "coder_bridge_notify.py" 2>/dev/null || true
pkill -f "coder_bridge_autofulfill" 2>/dev/null || true
pkill -f "coder_bridge_worker.py" 2>/dev/null || true

launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$uid" "$DST"
launchctl enable "gui/$uid/$LABEL" 2>/dev/null || true
launchctl kickstart -k "gui/$uid/$LABEL" 2>/dev/null || launchctl start "$LABEL" || true
echo "LaunchAgent installed: $DST"
echo "Check: curl -s http://127.0.0.1:8767/health"
