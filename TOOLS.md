# JARVIS tools

All tools return JSON strings. The model must call tools rather than invent results.

| Tool | Params | Notes |
|------|--------|--------|
| `get_current_time` | — | Local ISO timestamp |
| `list_notes` | — | Files in `~/.jarvis/notes/` |
| `read_note` | `filename` | Basename only, sandboxed |
| `save_note` | `filename`, `content` | Basename only, sandboxed |
| `open_url` | `url` | `http://` or `https://` only → default browser |
| `open_app` | `name` | macOS: `open -a <name>` (no shell, rejects `/;|$` etc.) |
| `get_clipboard` | — | `pbpaste` / `xclip`; content truncated at 20 000 chars |
| `set_clipboard` | `text` | `pbcopy` / `xclip` |
| `get_weather` | `location` | Live `wttr.in` JSON (temp, desc, humidity, wind) |
| `github_status` | optional `login` | `gh` CLI: open PRs authored + review-requested |

## Try them (with Ollama running)

```bash
python jarvis.py
# You › what time is it?
# You › weather in Helsinki
# You › open https://example.com
# You › what's on my clipboard?
# You › github status
```

Or GUI: `python app.py`.

### Prerequisites for some tools

- **open_app**: macOS (`open` command)
- **clipboard**: macOS (`pbpaste`/`pbcopy`) or Linux with `xclip`
- **get_weather**: network access
- **github_status**: [GitHub CLI](https://cli.github.com/) installed and `gh auth login`
