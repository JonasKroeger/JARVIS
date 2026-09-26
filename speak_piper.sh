#!/usr/bin/env bash
# Speak text with local Piper TTS + afplay (Apple Silicon / JARVIS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PIPER="${ROOT}/.venv/bin/piper"
MODEL="${ROOT}/piper/voices/en_US-lessac-medium.onnx"
OUT="${TMPDIR:-/tmp}/jarvis-piper-$$.wav"
cleanup() { rm -f "$OUT"; }
trap cleanup EXIT

if [[ ! -x "$PIPER" ]]; then
  echo "piper not found at $PIPER — run: .venv/bin/pip install 'piper-tts==1.8.0'" >&2
  exit 1
fi
if [[ ! -f "$MODEL" ]]; then
  echo "voice model missing: $MODEL" >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  TEXT="$*"
else
  TEXT="$(cat)"
fi

printf '%s' "$TEXT" | "$PIPER" -m "$MODEL" -f "$OUT"
afplay "$OUT"
