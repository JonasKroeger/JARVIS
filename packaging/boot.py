"""Bootstrap: activate repo venv site-packages and run app.py as __main__."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO = Path("/Users/jonaskroeger/JARVIS").resolve()
VENV = REPO / ".venv"
SITE = VENV / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"

os.chdir(REPO)
os.environ["VIRTUAL_ENV"] = str(VENV)
os.environ.setdefault("PYTHONUNBUFFERED", "1")
# Prefer venv binaries (piper helpers etc.) without replacing system paths entirely.
venv_bin = str(VENV / "bin")
path = os.environ.get("PATH", "")
if venv_bin not in path.split(":"):
    os.environ["PATH"] = venv_bin + (os.pathsep + path if path else "")

# Ensure repo + venv imports (interpreter is the in-bundle copy, not venv/bin/python).
for p in (str(REPO), str(SITE)):
    if p and p not in sys.path:
        sys.path.insert(0, p)

app = REPO / "app.py"
if not app.is_file():
    sys.stderr.write(f"JARVIS boot: missing {app}\n")
    sys.exit(1)

# Make QApplication / crash logs see a sensible argv[0].
sys.argv = [str(app), *sys.argv[1:]]
runpy.run_path(str(app), run_name="__main__")
