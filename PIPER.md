# Piper TTS (local neural speech)

Self-contained offline TTS for JARVIS on Apple Silicon (arm64).

## Install (already done on Jonas’s Mac)

- **Package:** `piper-tts==1.8.0` (OHF-Voice / native `macosx_11_0_arm64` wheel) into `~/JARVIS/.venv`
- **CLI:** `~/JARVIS/.venv/bin/piper`
- **Voice:** `en_US-lessac-medium` under `~/JARVIS/piper/voices/`

> Note: the archived rhasspy `piper_macos_aarch64.tar.gz` (2023.11.14-2) ships an **x86_64** binary with missing dylibs — do not use it on this Mac. Prefer `pip install piper-tts` into the JARVIS venv.

### Reinstall

```bash
cd ~/JARVIS
.venv/bin/pip install 'piper-tts==1.8.0'
mkdir -p piper/voices
curl -fsSL -o piper/voices/en_US-lessac-medium.onnx \
  'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true'
curl -fsSL -o piper/voices/en_US-lessac-medium.onnx.json \
  'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true'
```

## Paths

| | |
|---|---|
| Binary / module | `~/JARVIS/.venv/bin/piper` |
| Model | `~/JARVIS/piper/voices/en_US-lessac-medium.onnx` |
| Config | `~/JARVIS/piper/voices/en_US-lessac-medium.onnx.json` |
| Helper | `~/JARVIS/speak_piper.sh` |

## One-line speak command

```bash
echo 'Hello' | ~/JARVIS/.venv/bin/piper -m ~/JARVIS/piper/voices/en_US-lessac-medium.onnx -f /tmp/jarvis-piper.wav && afplay /tmp/jarvis-piper.wav
```

Or via helper:

```bash
~/JARVIS/speak_piper.sh 'Hello from JARVIS'
```

Text is read from **stdin** (or `-i file`). There is no `-t` flag in piper-tts 1.8. Output WAV with `-f` / `--output_file`, then `afplay`.

## Verify

```bash
echo 'Hello. JARVIS Piper TTS is online.' | ~/JARVIS/.venv/bin/piper \
  -m ~/JARVIS/piper/voices/en_US-lessac-medium.onnx \
  -f ~/JARVIS/piper/test.wav
ls -lh ~/JARVIS/piper/test.wav
afplay ~/JARVIS/piper/test.wav
```

Expected: non-empty RIFF/WAVE, mono PCM ~22.05 kHz.
