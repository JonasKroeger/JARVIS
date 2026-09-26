#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi
LOG="${HOME}/JARVIS/jarvis-debug.log"
mkdir -p "$(dirname "$LOG")"
{
  echo "==== JARVIS start $(date) pid=$$ ===="
} >> "$LOG"
PY="python3"
if [[ -x ".venv/bin/python3" ]]; then
  PY=".venv/bin/python3"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
fi
exec "$PY" -u app.py >> "$LOG" 2>&1
