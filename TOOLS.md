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
| `get_system_status` | — | Battery, disk free on `/`, uptime, hostname (Darwin + Linux fallbacks) |
| `notify` | `title`, `message` | macOS notification via `osascript` (escaped/truncated) |
| `create_reminder` | `text`, optional `due` | macOS Reminders; freeform due appended to body |
| `music_control` | `action` | `play`/`pause`/`next`/`previous`/`status` — Music.app then Spotify |
| `take_screenshot` | optional `path` | `screencapture -x`; path must resolve under home |
| `list_running_apps` | — | Visible app process names (capped ~40) |
| `read_file` | `path`, optional `max_bytes` | Text under home only; utf-8 replace; truncated flag |
| `web_search` | `query` | DuckDuckGo Instant Answer API (no key); abstract + up to 5 related |

## Safety

- No arbitrary shell tool.
- AppleScript string interpolations are escaped (`\` and `"`).
- `read_file` / `take_screenshot` paths must resolve under `Path.home()` (no `..` escape).
- `notify` / `create_reminder` reject insanely long strings and truncate reasonably.

## Try them (with Ollama running)

```bash
python jarvis.py
# You › what time is it?
# You › weather in Helsinki
# You › open https://example.com
# You › what's on my clipboard?
# You › github status
# You › system status
# You › search for Finland capital
# You › notify me title Hello message World
```

Or GUI: `python app.py`.

### Prerequisites for some tools

- **open_app**, **notify**, **create_reminder**, **music_control**, **take_screenshot**, **list_running_apps**: macOS
- **clipboard**: macOS (`pbpaste`/`pbcopy`) or Linux with `xclip`
- **get_weather**, **web_search**: network access
- **github_status**: [GitHub CLI](https://cli.github.com/) installed and `gh auth login`
