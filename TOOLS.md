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
| `calendar_events` | optional `days` (1–7, default 1) | macOS Calendar.app / `icalBuddy`; title/start/end/location; capped ~25 |
| `volume_control` | `action` get\|set\|mute\|unmute, optional `level` | macOS output volume; `level` clamped 0–100 |
| `start_timer` | `seconds` **or** `minutes`, optional `label` | Background daemon thread; macOS notification on fire; max 24h |
| `list_timers` | — | Active timers with remaining seconds |
| `fetch_url` | `url`, optional `max_chars` (default 8000) | http(s) only; title + readable text (scripts stripped) |
| `stock_quote` | `symbol` | Yahoo Finance chart API (no key); price, currency, change % |
| `dark_mode` | `mode` on\|off\|toggle\|status | macOS System Events appearance preferences |
| `daily_briefing` | optional `city` | Composite: time + system + calendar(today) + weather + github; default city Helsinki; empty city skips weather |

## Safety

- No arbitrary shell tool.
- AppleScript string interpolations are escaped (`\` and `"`).
- `read_file` / `take_screenshot` paths must resolve under `Path.home()` (no `..` escape).
- `notify` / `create_reminder` reject insanely long strings and truncate reasonably.
- `fetch_url` rejects non-http(s) schemes (no `file://`).
- Timers capped at 24 hours; volume level clamped to 0–100.

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
# You › good morning          # → daily_briefing
# You › brief me
# You › stock quote AAPL
# You › set a 5 minute timer for tea
```

Or GUI: `python app.py`.

### Prerequisites for some tools

- **open_app**, **notify**, **create_reminder**, **music_control**, **take_screenshot**, **list_running_apps**, **calendar_events**, **volume_control**, **dark_mode**: macOS
- **start_timer** notification: macOS (timer tracking works cross-platform)
- **clipboard**: macOS (`pbpaste`/`pbcopy`) or Linux with `xclip`
- **get_weather**, **web_search**, **fetch_url**, **stock_quote**: network access
- **github_status**: [GitHub CLI](https://cli.github.com/) installed and `gh auth login`
- **calendar_events**: optional [icalBuddy](https://hasseg.org/icalBuddy/) for cleaner output; else Calendar.app
