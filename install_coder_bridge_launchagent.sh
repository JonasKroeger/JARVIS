#!/usr/bin/env bash
# Install / reload the live Coder mailbox LaunchAgent (survives login/reboot).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/launchd/com.jonas.jarvis.coder-bridge.plist"
DST="$HOME/Library/LaunchAgents/com.jonas.jarvis.coder-bridge.plist"
LABEL="com.jonas.jarvis.coder-bridge"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DST"
# Optional: inject NOTIFY_URL from env into the installed plist via a sidecar env file.
ENV_FILE="$ROOT/coder_bridge.notify.env"
if [[ -n "${CODER_BRIDGE_NOTIFY_URL:-}" ]]; then
  printf 'CODER_BRIDGE_NOTIFY_URL=%s\n' "$CODER_BRIDGE_NOTIFY_URL" > "$ENV_FILE"
  echo "wrote $ENV_FILE"
fi
# Wrap start script already sources nothing; export via launchctl setenv is session-wide.
# Prefer editing EnvironmentVariables in the plist if URL is known:
if [[ -n "${CODER_BRIDGE_NOTIFY_URL:-}" ]]; then
  /usr/libexec/PlistBuddy -c "Delete :EnvironmentVariables:CODER_BRIDGE_NOTIFY_URL" "$DST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:CODER_BRIDGE_NOTIFY_URL string $CODER_BRIDGE_NOTIFY_URL" "$DST"
  echo "injected CODER_BRIDGE_NOTIFY_URL into $DST"
fi
uid="$(id -u)"
launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$uid" "$DST"
launchctl enable "gui/$uid/$LABEL" 2>/dev/null || true
launchctl kickstart -k "gui/$uid/$LABEL" 2>/dev/null || launchctl start "$LABEL" || true
echo "LaunchAgent installed: $DST"
echo "Check: curl -s http://127.0.0.1:8766/health"
