#!/bin/bash
# Build dist/JARVIS.app (and install to ~/Applications/JARVIS.app).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packaging"
DIST="${JARVIS_APP_DIST:-$ROOT/dist/JARVIS.app}"
INSTALL_TO="${JARVIS_APP_INSTALL:-$HOME/Applications/JARVIS.app}"
PYCFG="${JARVIS_PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "error: $ROOT/.venv/bin/python missing — create the venv first" >&2
  exit 1
fi
if [[ ! -x "$PYCFG" ]]; then
  echo "error: python-config not found at $PYCFG" >&2
  exit 1
fi

echo "Building $DIST"

rm -rf "$DIST"
mkdir -p "$DIST/Contents/MacOS" "$DIST/Contents/Resources"

cp "$PKG/Info.plist" "$DIST/Contents/Info.plist"
cp "$PKG/boot.py" "$DIST/Contents/Resources/boot.py"
if [[ -f "$PKG/AppIcon.icns" ]]; then
  cp "$PKG/AppIcon.icns" "$DIST/Contents/Resources/AppIcon.icns"
fi
echo -n "APPL????" > "$DIST/Contents/PkgInfo"

# Embed CPython so the running Mach-O is Contents/MacOS/JARVIS (Dock name).
# shellcheck disable=SC2046
clang -arch arm64 -Os \
  -o "$DIST/Contents/MacOS/JARVIS" \
  "$PKG/jarvis_stub.c" \
  $($PYCFG --includes) \
  $($PYCFG --ldflags --embed)
chmod +x "$DIST/Contents/MacOS/JARVIS"

if [[ "${JARVIS_APP_SKIP_INSTALL:-0}" != "1" ]]; then
  mkdir -p "$(dirname "$INSTALL_TO")"
  rm -rf "$INSTALL_TO"
  ditto "$DIST" "$INSTALL_TO"
  echo "Installed $INSTALL_TO"
fi

echo "Done."
echo "Launch: open -a JARVIS   OR   ./start_jarvis_hud.sh"
