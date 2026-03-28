#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi
exec python3 app.py
