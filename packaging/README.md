# JARVIS.app packaging

Builds a real macOS app bundle so Dock / Cmd-Tab / menu bar show **JARVIS** (with icon), not “Python”.

## Build & install

```bash
./packaging/build_jarvis_app.sh
```

Creates `dist/JARVIS.app` and copies it to `~/Applications/JARVIS.app`.

## Launch

```bash
open -a JARVIS
# or
./start_jarvis_hud.sh
```

LaunchAgent (`launchd/com.jonas.jarvis.hud.plist`) runs  
`~/Applications/JARVIS.app/Contents/MacOS/JARVIS` (no Terminal).

## How it works

`Contents/MacOS/JARVIS` is a small Mach-O that **embeds CPython** and runs `Resources/boot.py` in-process. The process binary lives inside the `.app`, so LaunchServices uses `Info.plist` (`CFBundleName` / `com.jonaskroeger.jarvis`). `boot.py` points at the repo venv + `app.py` — no PyInstaller freeze.

Rebuild after changing the stub, icon, or Info.plist. Room server `:8767` is separate and untouched.
