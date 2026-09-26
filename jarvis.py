#!/usr/bin/env python3
"""
Local JARVIS — text chat with Ollama, session memory, and a few safe tools.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MAX_TOOL_ROUNDS = 6
CLIPBOARD_MAX_CHARS = 20_000
NOTIFY_TITLE_MAX = 200
NOTIFY_MESSAGE_MAX = 2_000
REMINDER_TEXT_MAX = 2_000
READ_FILE_DEFAULT_MAX = 50_000
READ_FILE_HARD_MAX = 500_000
RUNNING_APPS_CAP = 40
CALENDAR_EVENTS_CAP = 25
TIMER_MAX_SECONDS = 24 * 3600
FETCH_URL_DEFAULT_MAX = 8000
FETCH_URL_HARD_MAX = 100_000

NOTES_DIR = Path.home() / ".jarvis" / "notes"

# Active timers tracked by start_timer / list_timers (daemon threads).
_ACTIVE_TIMERS: list[dict[str, Any]] = []
_TIMERS_LOCK = threading.Lock()

SYSTEM_PROMPT = """You are JARVIS, a calm, precise local assistant. Be brief unless asked for detail;
dry wit is fine, never cruel. Call tools for real actions/data — never invent timestamps, notes,
clipboard, weather, GitHub, system status, search results, file contents, stock prices, calendar
events, or command output.

Tools: time, notes, open_url, open_app, clipboard, get_weather, github_status, get_system_status,
notify, create_reminder, music_control, take_screenshot, list_running_apps, read_file, web_search,
calendar_events, volume_control, start_timer, list_timers, fetch_url, stock_quote, dark_mode,
daily_briefing.

When the user says good morning / brief me / status report (or similar), call daily_briefing and
narrate the structured result — do not invent the briefing. Pure hi/thanks chitchat → plain text,
no tools. Only tool-call for actions or live data.

Answer factual/historical questions neutrally. Refuse only requests for harm, crime, or illegal/
exploitative material."""


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Returns the current local date and time (ISO 8601) for the machine JARVIS runs on.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "Lists saved note filenames in the user's JARVIS notes folder.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Reads the full text of one note by filename (e.g. shopping.txt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Basename only, e.g. reminders.md",
                    }
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "Creates or overwrites a note file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Basename only; letters, numbers, dot, underscore, hyphen.",
                    },
                    "content": {"type": "string", "description": "Full text to store."},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Opens an http:// or https:// URL in the default web browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL starting with http:// or https://",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launches a macOS application by name (e.g. Safari, Notes, Terminal).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Application name as shown in /Applications (no path).",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clipboard",
            "description": "Reads the current system clipboard text (truncated if very long).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_clipboard",
            "description": "Writes text to the system clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to place on the clipboard."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Fetches current weather for a city via wttr.in (live data).",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name, e.g. Helsinki, London",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_status",
            "description": (
                "Summarizes open GitHub PRs authored by the authenticated user and PRs "
                "awaiting their review (via gh CLI). Optional login is informational only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "login": {
                        "type": "string",
                        "description": "Optional GitHub login hint; empty uses gh auth.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Battery, disk free space, uptime, and hostname for this machine.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify",
            "description": "Shows a macOS desktop notification with title and message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Notification title."},
                    "message": {"type": "string", "description": "Notification body."},
                },
                "required": ["title", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Creates a macOS Reminders item. Optional freeform due date; if unparsed, due is appended to the body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Reminder title/body."},
                    "due": {
                        "type": "string",
                        "description": "Optional freeform due hint (e.g. tomorrow 5pm).",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "music_control",
            "description": "Control Music.app (or Spotify fallback): play, pause, next, previous, or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "One of: play, pause, next, previous, status",
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Captures the screen to a PNG under the home directory (default ~/Desktop).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional save path; must resolve under home.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_running_apps",
            "description": "Lists names of visible running applications (capped).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Reads a text file under the home directory (utf-8, truncated if large).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path under home."},
                    "max_bytes": {
                        "type": "integer",
                        "description": "Max bytes to read (default 50000).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "DuckDuckGo Instant Answer search (AbstractText/URL + related snippets). No API key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_events",
            "description": "Lists Calendar.app events for today / next N days (macOS). Returns title, start, end, location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days including today (default 1, max 7).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_control",
            "description": "macOS output volume: get, set (level 0-100), mute, or unmute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "One of: get, set, mute, unmute",
                    },
                    "level": {
                        "type": "integer",
                        "description": "Volume 0-100 when action is set.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_timer",
            "description": "Starts a background timer; fires a macOS notification when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Duration in seconds."},
                    "minutes": {"type": "number", "description": "Duration in minutes (alternative to seconds)."},
                    "label": {"type": "string", "description": "Optional timer label for the notification."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_timers",
            "description": "Lists active (not yet fired) JARVIS timers.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetches an http(s) URL and returns page title plus readable text (truncated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http:// or https:// URL only."},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters of extracted text (default 8000).",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_quote",
            "description": "Live stock/ETF quote via Yahoo Finance chart API (no key). Returns price, currency, change %.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL, NOK.HE"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dark_mode",
            "description": "macOS appearance: turn dark mode on/off, toggle, or report status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "One of: on, off, toggle, status",
                    }
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_briefing",
            "description": (
                "Iron Man-style morning briefing: time, system status, today's calendar, optional "
                "weather, and GitHub status — one structured JSON to narrate. Use for good morning / "
                "brief me / status report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City for weather (default Helsinki). Empty string skips weather.",
                    }
                },
                "required": [],
            },
        },
    },
]


def _ensure_notes_dir() -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


def _safe_basename(name: str) -> str | None:
    base = Path(name).name
    if not base or base in (".", ".."):
        return None
    if not re.fullmatch(r"[\w.\-]{1,120}", base):
        return None
    return base


def _safe_app_name(name: str) -> str | None:
    """Reject path/shell metacharacters; keep simple app names like 'Safari'."""
    name = name.strip()
    if not name or len(name) > 120:
        return None
    if any(c in name for c in ("/", ";", "|", "$", "`", "\n", "\r")):
        return None
    return name


def tool_get_current_time(_: dict[str, Any]) -> str:
    now = datetime.now().astimezone()
    return json.dumps({"iso_local": now.isoformat(), "tz": str(now.tzinfo)})


def tool_list_notes(_: dict[str, Any]) -> str:
    _ensure_notes_dir()
    names = sorted(p.name for p in NOTES_DIR.iterdir() if p.is_file())
    return json.dumps({"notes": names, "dir": str(NOTES_DIR)})


def tool_read_note(args: dict[str, Any]) -> str:
    _ensure_notes_dir()
    base = _safe_basename(str(args.get("filename", "")))
    if not base:
        return json.dumps({"error": "invalid filename"})
    path = NOTES_DIR / base
    if not path.is_file():
        return json.dumps({"error": "not found", "filename": base})
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"filename": base, "content": text})


def tool_save_note(args: dict[str, Any]) -> str:
    _ensure_notes_dir()
    base = _safe_basename(str(args.get("filename", "")))
    if not base:
        return json.dumps({"error": "invalid filename"})
    content = args.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    try:
        (NOTES_DIR / base).write_text(content, encoding="utf-8")
    except OSError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"saved": base, "bytes": len(content.encode("utf-8"))})


def tool_open_url(args: dict[str, Any]) -> str:
    url = str(args.get("url", "")).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return json.dumps({"ok": False, "error": "url must start with http:// or https://"})
    try:
        opened = webbrowser.open(url)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "url": url, "opened": bool(opened)})


def tool_open_app(args: dict[str, Any]) -> str:
    name = _safe_app_name(str(args.get("name", "")))
    if not name:
        return json.dumps(
            {
                "ok": False,
                "error": "invalid app name (no path or shell metacharacters)",
            }
        )
    try:
        proc = subprocess.run(
            ["open", "-a", name],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
    except FileNotFoundError:
        return json.dumps(
            {
                "ok": False,
                "error": "`open` command not found (macOS only)",
            }
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "timed out after 15s"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps(
        {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "").strip(),
            "name": name,
        }
    )


def tool_get_clipboard(_: dict[str, Any]) -> str:
    system = platform.system()
    cmd: list[str] | None = None
    if system == "Darwin":
        cmd = ["pbpaste"]
    else:
        if shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard", "-o"]
        else:
            return json.dumps(
                {
                    "error": "clipboard read unsupported: need pbpaste (macOS) or xclip (Linux)",
                }
            )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=10,
            shell=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"command not found: {cmd[0]}"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "clipboard read timed out"})
    except OSError as e:
        return json.dumps({"error": str(e)})
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return json.dumps({"error": err or f"{cmd[0]} failed", "returncode": proc.returncode})
    content = (proc.stdout or b"").decode("utf-8", errors="replace")
    truncated = False
    if len(content) > CLIPBOARD_MAX_CHARS:
        content = content[:CLIPBOARD_MAX_CHARS]
        truncated = True
    return json.dumps({"content": content, "truncated": truncated})


def tool_set_clipboard(args: dict[str, Any]) -> str:
    text = args.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    system = platform.system()
    cmd: list[str] | None = None
    if system == "Darwin":
        cmd = ["pbcopy"]
    else:
        if shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard"]
        else:
            return json.dumps(
                {
                    "ok": False,
                    "error": "clipboard write unsupported: need pbcopy (macOS) or xclip (Linux)",
                }
            )
    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=10,
            shell=False,
        )
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": f"command not found: {cmd[0]}"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "clipboard write timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return json.dumps(
            {
                "ok": False,
                "error": err or f"{cmd[0]} failed",
                "returncode": proc.returncode,
            }
        )
    return json.dumps({"ok": True, "bytes": len(text.encode("utf-8"))})


def tool_get_weather(args: dict[str, Any]) -> str:
    location = str(args.get("location", "")).strip()
    if not location:
        return json.dumps({"error": "location is required"})
    quoted = urllib.parse.quote(location)
    url = f"https://wttr.in/{quoted}?format=j1"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "jarvis-local/1.0"})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return json.dumps({"error": f"weather request failed: {e}"})
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({"error": f"invalid weather response: {e}"})

    try:
        cond = (data.get("current_condition") or [None])[0]
        if not isinstance(cond, dict):
            return json.dumps({"error": "missing current_condition in weather response"})
        desc_list = cond.get("weatherDesc") or []
        desc = ""
        if desc_list and isinstance(desc_list[0], dict):
            desc = str(desc_list[0].get("value") or "")
        area_name = ""
        areas = data.get("nearest_area") or []
        if areas and isinstance(areas[0], dict):
            an = areas[0].get("areaName") or []
            if an and isinstance(an[0], dict):
                area_name = str(an[0].get("value") or "")
        result: dict[str, Any] = {
            "location_query": location,
            "temp_C": cond.get("temp_C"),
            "weatherDesc": desc,
            "humidity": cond.get("humidity"),
            "windspeedKmph": cond.get("windspeedKmph"),
        }
        if area_name:
            result["nearest_area"] = area_name
        return json.dumps(result)
    except (TypeError, KeyError, IndexError) as e:
        return json.dumps({"error": f"could not parse weather: {e}"})


def _gh_run(argv: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def tool_github_status(args: dict[str, Any]) -> str:
    login_hint = str(args.get("login", "") or "").strip()
    if not shutil.which("gh"):
        return json.dumps(
            {
                "error": "gh CLI not found. Install GitHub CLI and run: gh auth login",
            }
        )

    login = ""
    try:
        code, out, err = _gh_run(["gh", "api", "user", "--jq", ".login"])
        if code == 0 and out:
            login = out
        else:
            # Auth / API failure — still try searches; surface clear guidance if those fail too
            auth_err = err or out or "gh api user failed"
            # Probe whether gh is authed at all
            code2, _, err2 = _gh_run(["gh", "auth", "status"], timeout=15.0)
            if code2 != 0:
                return json.dumps(
                    {
                        "error": "gh is not authenticated. Run: gh auth login",
                        "detail": err2 or auth_err,
                    }
                )
    except FileNotFoundError:
        return json.dumps(
            {
                "error": "gh CLI not found. Install GitHub CLI and run: gh auth login",
            }
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "gh timed out; check network and try again"})
    except OSError as e:
        return json.dumps({"error": str(e)})

    try:
        code_a, out_a, err_a = _gh_run(
            [
                "gh",
                "search",
                "prs",
                "--author=@me",
                "--state=open",
                "--limit",
                "10",
                "--json",
                "number,title,url,repository",
            ]
        )
        code_r, out_r, err_r = _gh_run(
            [
                "gh",
                "search",
                "prs",
                "--review-requested=@me",
                "--state=open",
                "--limit",
                "10",
                "--json",
                "number,title,url,repository",
            ]
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "gh search timed out"})
    except OSError as e:
        return json.dumps({"error": str(e)})

    # If both searches fail with auth-ish errors, tell user to login
    combined_err = f"{err_a}\n{err_r}".lower()
    if code_a != 0 and code_r != 0:
        if "auth" in combined_err or "login" in combined_err or "401" in combined_err:
            return json.dumps(
                {
                    "error": "gh is not authenticated. Run: gh auth login",
                    "detail": (err_a or err_r).strip(),
                }
            )
        return json.dumps(
            {
                "error": "gh search failed",
                "authored_error": err_a or out_a,
                "review_error": err_r or out_r,
            }
        )

    def _parse_prs(raw: str, code: int) -> list[Any]:
        if code != 0 or not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    authored = _parse_prs(out_a, code_a)
    review_requested = _parse_prs(out_r, code_r)
    result: dict[str, Any] = {
        "login": login or login_hint or None,
        "authored_open": authored,
        "review_requested_open": review_requested,
    }
    if code_a != 0:
        result["authored_error"] = err_a or out_a
    if code_r != 0:
        result["review_error"] = err_r or out_r
    return json.dumps(result)


def _escape_applescript(s: str) -> str:
    """Escape a string for safe embedding in AppleScript double-quoted literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _clip_str(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _resolve_under_home(path_str: str) -> Path | None:
    """Resolve path; return None if it escapes the user's home directory."""
    if not path_str or not isinstance(path_str, str):
        return None
    try:
        home = Path.home().resolve()
        p = Path(path_str).expanduser().resolve()
        p.relative_to(home)
        return p
    except (OSError, ValueError, RuntimeError):
        return None


def _run_cmd(argv: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _osascript(script: str, timeout: float = 20.0) -> tuple[int, str, str]:
    return _run_cmd(["osascript", "-e", script], timeout=timeout)


def _parse_battery_pmset(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    # e.g. " -InternalBattery-0 (id=...)	82%; charging; ..."
    m = re.search(r"(\d+)\s*%", out)
    if m:
        info["percent"] = int(m.group(1))
    low = out.lower()
    if "charging" in low and "discharging" not in low:
        info["charging"] = True
    elif "discharging" in low:
        info["charging"] = False
    elif "charged" in low or "ac attached" in low:
        info["charging"] = True
    else:
        info["charging"] = None
    return info


def _linux_battery() -> dict[str, Any] | None:
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        return None
    for bat in sorted(base.glob("BAT*")):
        try:
            cap = (bat / "capacity").read_text(encoding="utf-8").strip()
            status = (bat / "status").read_text(encoding="utf-8").strip().lower()
            percent = int(cap)
            charging = status in ("charging", "full")
            if status == "discharging":
                charging = False
            return {"percent": percent, "charging": charging, "status": status}
        except (OSError, ValueError):
            continue
    return None


def tool_get_system_status(_: dict[str, Any]) -> str:
    system = platform.system()
    result: dict[str, Any] = {"os": system}

    # hostname
    hostname = None
    if system == "Darwin":
        try:
            code, out, err = _run_cmd(["scutil", "--get", "ComputerName"], timeout=5.0)
            if code == 0 and out:
                hostname = out
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    if not hostname:
        try:
            hostname = socket.gethostname()
        except OSError as e:
            hostname = None
            result["hostname_error"] = str(e)
    result["hostname"] = hostname

    # battery
    if system == "Darwin":
        try:
            code, out, err = _run_cmd(["pmset", "-g", "batt"], timeout=10.0)
            if code == 0 and out:
                result["battery"] = _parse_battery_pmset(out)
            else:
                result["battery"] = {"error": err or out or "pmset failed"}
        except FileNotFoundError:
            result["battery"] = {"error": "pmset not found"}
        except subprocess.TimeoutExpired:
            result["battery"] = {"error": "pmset timed out"}
        except OSError as e:
            result["battery"] = {"error": str(e)}
    else:
        bat = _linux_battery()
        result["battery"] = bat if bat is not None else {"error": "battery info unavailable"}

    # disk
    try:
        code, out, err = _run_cmd(["df", "-h", "/"], timeout=10.0)
        if code == 0 and out:
            lines = [ln for ln in out.splitlines() if ln.strip()]
            # header + data; take last data line
            data_line = lines[-1] if len(lines) >= 1 else ""
            parts = data_line.split()
            # Filesystem Size Used Avail Capacity Mounted
            disk: dict[str, Any] = {"raw": data_line}
            if len(parts) >= 5:
                disk["size"] = parts[1]
                disk["used"] = parts[2]
                disk["avail"] = parts[3]
                disk["capacity"] = parts[4]
            result["disk"] = disk
        else:
            result["disk"] = {"error": err or out or "df failed"}
    except FileNotFoundError:
        result["disk"] = {"error": "df not found"}
    except subprocess.TimeoutExpired:
        result["disk"] = {"error": "df timed out"}
    except OSError as e:
        result["disk"] = {"error": str(e)}

    # uptime
    try:
        code, out, err = _run_cmd(["uptime"], timeout=5.0)
        if code == 0 and out:
            result["uptime"] = out
        else:
            result["uptime"] = {"error": err or out or "uptime failed"}
    except FileNotFoundError:
        result["uptime"] = {"error": "uptime not found"}
    except subprocess.TimeoutExpired:
        result["uptime"] = {"error": "uptime timed out"}
    except OSError as e:
        result["uptime"] = {"error": str(e)}

    return json.dumps(result)


def tool_notify(args: dict[str, Any]) -> str:
    title = args.get("title", "")
    message = args.get("message", "")
    if not isinstance(title, str):
        title = str(title)
    if not isinstance(message, str):
        message = str(message)
    title = title.strip()
    message = message.strip()
    if not title and not message:
        return json.dumps({"ok": False, "error": "title and message are empty"})
    if len(title) > NOTIFY_TITLE_MAX * 4 or len(message) > NOTIFY_MESSAGE_MAX * 4:
        return json.dumps({"ok": False, "error": "title or message insanely long"})
    title = _clip_str(title, NOTIFY_TITLE_MAX)
    message = _clip_str(message, NOTIFY_MESSAGE_MAX)
    if platform.system() != "Darwin":
        return json.dumps({"ok": False, "error": "notify is macOS-only (osascript)"})
    et = _escape_applescript(title)
    em = _escape_applescript(message)
    script = f'display notification "{em}" with title "{et}"'
    try:
        code, out, err = _osascript(script, timeout=15.0)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "osascript not found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "osascript timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if code != 0:
        return json.dumps({"ok": False, "error": err or out or "osascript failed", "returncode": code})
    return json.dumps({"ok": True, "title": title, "message": message})


def tool_create_reminder(args: dict[str, Any]) -> str:
    text = args.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    due = args.get("due", "")
    if due is None:
        due = ""
    if not isinstance(due, str):
        due = str(due)
    due = due.strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    if len(text) > REMINDER_TEXT_MAX * 4 or len(due) > REMINDER_TEXT_MAX * 4:
        return json.dumps({"ok": False, "error": "text or due insanely long"})
    text = _clip_str(text, REMINDER_TEXT_MAX)
    due = _clip_str(due, REMINDER_TEXT_MAX) if due else ""
    if platform.system() != "Darwin":
        return json.dumps({"ok": False, "error": "create_reminder is macOS-only (Reminders/osascript)"})
    # Keep due in body when freeform parsing is unreliable
    body = text
    due_note = False
    if due:
        body = f"{text} (due: {due})"
        due_note = True
    et = _escape_applescript(body)
    script = (
        'tell application "Reminders"\n'
        f'  make new reminder with properties {{name:"{et}"}}\n'
        "end tell"
    )
    try:
        code, out, err = _osascript(script, timeout=20.0)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "osascript not found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "osascript timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if code != 0:
        return json.dumps({"ok": False, "error": err or out or "osascript failed", "returncode": code})
    return json.dumps({"ok": True, "text": body, "due_in_body": due_note})


def _music_osascript(app: str, action: str) -> tuple[int, str, str]:
    app_q = _escape_applescript(app)
    if action == "play":
        script = f'tell application "{app_q}" to play'
    elif action == "pause":
        script = f'tell application "{app_q}" to pause'
    elif action == "next":
        script = f'tell application "{app_q}" to next track'
    elif action == "previous":
        script = f'tell application "{app_q}" to previous track'
    elif action == "status":
        script = (
            f'tell application "{app_q}"\n'
            "  set t to name of current track\n"
            "  set a to artist of current track\n"
            "  set p to player state as string\n"
            '  return t & " | " & a & " | " & p\n'
            "end tell"
        )
    else:
        return 1, "", f"unknown action: {action}"
    return _osascript(script, timeout=15.0)


def tool_music_control(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).strip().lower()
    if action not in ("play", "pause", "next", "previous", "status"):
        return json.dumps(
            {
                "ok": False,
                "error": "action must be one of: play, pause, next, previous, status",
            }
        )
    if platform.system() != "Darwin":
        return json.dumps({"ok": False, "error": "music_control is macOS-only"})
    last_err = ""
    for app in ("Music", "Spotify"):
        try:
            code, out, err = _music_osascript(app, action)
        except FileNotFoundError:
            return json.dumps({"ok": False, "error": "osascript not found"})
        except subprocess.TimeoutExpired:
            last_err = f"{app}: timed out"
            continue
        except OSError as e:
            last_err = f"{app}: {e}"
            continue
        if code == 0:
            if action == "status":
                parts = [p.strip() for p in (out or "").split("|")]
                track = parts[0] if len(parts) > 0 else ""
                artist = parts[1] if len(parts) > 1 else ""
                state = parts[2] if len(parts) > 2 else ""
                return json.dumps(
                    {
                        "ok": True,
                        "app": app,
                        "track": track,
                        "artist": artist,
                        "state": state,
                        "raw": out,
                    }
                )
            return json.dumps({"ok": True, "app": app, "action": action})
        last_err = err or out or f"{app} failed ({code})"
    return json.dumps({"ok": False, "error": last_err or "Music and Spotify both failed"})


def tool_take_screenshot(args: dict[str, Any]) -> str:
    if platform.system() != "Darwin":
        return json.dumps({"ok": False, "error": "take_screenshot is macOS-only (screencapture)"})
    path_arg = args.get("path")
    if path_arg is None or str(path_arg).strip() == "":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = Path.home() / "Desktop" / f"jarvis-shot-{stamp}.png"
    else:
        resolved = _resolve_under_home(str(path_arg))
        if resolved is None:
            return json.dumps({"ok": False, "error": "path must resolve under home directory"})
        dest = resolved
    # Ensure parent under home and exists
    try:
        home = Path.home().resolve()
        dest.resolve().relative_to(home)
    except (OSError, ValueError):
        return json.dumps({"ok": False, "error": "path must resolve under home directory"})
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return json.dumps({"ok": False, "error": f"cannot create parent dir: {e}"})
    bin_path = "/usr/sbin/screencapture"
    if not Path(bin_path).is_file():
        bin_path = "/usr/bin/screencapture"
    try:
        code, out, err = _run_cmd([bin_path, "-x", str(dest)], timeout=30.0)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "screencapture not found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "screencapture timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if code != 0:
        return json.dumps({"ok": False, "error": err or out or "screencapture failed", "returncode": code})
    if not dest.is_file():
        return json.dumps({"ok": False, "error": "screencapture reported ok but file missing", "path": str(dest)})
    return json.dumps({"ok": True, "path": str(dest)})


def tool_list_running_apps(_: dict[str, Any]) -> str:
    if platform.system() != "Darwin":
        return json.dumps({"error": "list_running_apps is macOS-only", "apps": []})
    script = (
        'tell application "System Events"\n'
        "  get name of every process whose background only is false\n"
        "end tell"
    )
    try:
        code, out, err = _osascript(script, timeout=20.0)
    except FileNotFoundError:
        return json.dumps({"error": "osascript not found", "apps": []})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "osascript timed out", "apps": []})
    except OSError as e:
        return json.dumps({"error": str(e), "apps": []})
    if code != 0:
        return json.dumps({"error": err or out or "osascript failed", "apps": []})
    # osascript returns comma-separated list
    names = [n.strip() for n in (out or "").split(",") if n.strip()]
    capped = False
    if len(names) > RUNNING_APPS_CAP:
        names = names[:RUNNING_APPS_CAP]
        capped = True
    return json.dumps({"apps": names, "count": len(names), "capped": capped})


def tool_read_file(args: dict[str, Any]) -> str:
    path_str = str(args.get("path", "")).strip()
    if not path_str:
        return json.dumps({"error": "path is required"})
    resolved = _resolve_under_home(path_str)
    if resolved is None:
        return json.dumps({"error": "path must resolve under home directory"})
    max_bytes = args.get("max_bytes", READ_FILE_DEFAULT_MAX)
    try:
        max_bytes = int(max_bytes)
    except (TypeError, ValueError):
        max_bytes = READ_FILE_DEFAULT_MAX
    if max_bytes < 1:
        max_bytes = READ_FILE_DEFAULT_MAX
    if max_bytes > READ_FILE_HARD_MAX:
        max_bytes = READ_FILE_HARD_MAX
    if not resolved.is_file():
        return json.dumps({"error": "not a file", "path": str(resolved)})
    try:
        raw = resolved.read_bytes()
    except OSError as e:
        return json.dumps({"error": str(e), "path": str(resolved)})
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    content = raw.decode("utf-8", errors="replace")
    return json.dumps(
        {
            "path": str(resolved),
            "content": content,
            "truncated": truncated,
            "bytes_read": len(raw),
        }
    )


def tool_web_search(args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "query is required"})
    if len(query) > 500:
        return json.dumps({"error": "query too long"})
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    url = "https://api.duckduckgo.com/"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, params=params, headers={"User-Agent": "jarvis-local/1.0"})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return json.dumps({"error": f"search request failed: {e}", "query": query})
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({"error": f"invalid search response: {e}", "query": query})

    if not isinstance(data, dict):
        return json.dumps({"error": "unexpected search response shape", "query": query})

    related: list[str] = []
    for item in data.get("RelatedTopics") or []:
        if len(related) >= 5:
            break
        if isinstance(item, dict):
            if "Topics" in item and isinstance(item["Topics"], list):
                for sub in item["Topics"]:
                    if len(related) >= 5:
                        break
                    if isinstance(sub, dict) and sub.get("Text"):
                        related.append(str(sub["Text"]))
            elif item.get("Text"):
                related.append(str(item["Text"]))

    return json.dumps(
        {
            "query": query,
            "AbstractText": data.get("AbstractText") or "",
            "AbstractURL": data.get("AbstractURL") or "",
            "RelatedTopics": related,
            "Heading": data.get("Heading") or "",
        }
    )



def tool_calendar_events(args: dict[str, Any]) -> str:
    days_raw = args.get("days", 1)
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = 1
    if days < 1:
        days = 1
    if days > 7:
        days = 7
    if platform.system() != "Darwin":
        return json.dumps(
            {
                "error": "calendar_events is macOS-only (Calendar.app / icalBuddy)",
                "events": [],
            }
        )

    events: list[dict[str, Any]] = []
    # Prefer icalBuddy when available.
    if shutil.which("icalBuddy"):
        try:
            end_label = "today" if days == 1 else f"today+{days - 1}"
            code, out, err = _run_cmd(
                [
                    "icalBuddy",
                    "-n",
                    "-nc",
                    "-nrd",
                    "-iep",
                    "title,datetime,location",
                    "-ps",
                    "| |",
                    "-b",
                    "",
                    "-df",
                    "%Y-%m-%d",
                    "-tf",
                    "%H:%M",
                    "eventsFrom:today",
                    f"to:{end_label}",
                ],
                timeout=30.0,
            )
            if code == 0 and out is not None:
                for line in (out or "").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    title = parts[0] if parts else ""
                    start_s = parts[1] if len(parts) > 1 else ""
                    end_s = ""
                    location = ""
                    if len(parts) >= 4:
                        end_s = parts[2]
                        location = parts[3]
                    elif len(parts) == 3:
                        # title | datetime | location  OR title | start | end
                        if re.search(r"\d", parts[2]) and ":" in parts[2] and " " not in parts[2]:
                            end_s = parts[2]
                        else:
                            location = parts[2]
                    ev: dict[str, Any] = {"title": title, "start": start_s, "end": end_s}
                    if location:
                        ev["location"] = location
                    events.append(ev)
                    if len(events) >= CALENDAR_EVENTS_CAP:
                        break
                return json.dumps(
                    {
                        "events": events[:CALENDAR_EVENTS_CAP],
                        "days": days,
                        "count": len(events[:CALENDAR_EVENTS_CAP]),
                        "capped": len(events) >= CALENDAR_EVENTS_CAP,
                        "source": "icalBuddy",
                    }
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass  # fall through to Calendar.app

    # days is a validated int — safe to interpolate into AppleScript.
    script = f"""set startDate to (current date)
set hours of startDate to 0
set minutes of startDate to 0
set seconds of startDate to 0
set endDate to startDate + ({days} * days)
set output to ""
tell application "Calendar"
  repeat with cal in calendars
    set evts to (every event of cal whose start date ≥ startDate and start date < endDate)
    repeat with e in evts
      set t to summary of e
      set s to (start date of e) as string
      set en to (end date of e) as string
      set loc to ""
      try
        set loc to location of e
        if loc is missing value then set loc to ""
      end try
      set output to output & t & "|||" & s & "|||" & en & "|||" & loc & linefeed
    end repeat
  end repeat
end tell
return output"""
    try:
        code, out, err = _osascript(script, timeout=45.0)
    except FileNotFoundError:
        return json.dumps({"error": "osascript not found", "events": []})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "calendar query timed out", "events": []})
    except OSError as e:
        return json.dumps({"error": str(e), "events": []})
    if code != 0:
        return json.dumps(
            {
                "error": err or out or "Calendar.app query failed",
                "events": [],
                "returncode": code,
            }
        )
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||")
        title = parts[0].strip() if parts else ""
        start_s = parts[1].strip() if len(parts) > 1 else ""
        end_s = parts[2].strip() if len(parts) > 2 else ""
        location = parts[3].strip() if len(parts) > 3 else ""
        ev = {"title": title, "start": start_s, "end": end_s}
        if location:
            ev["location"] = location
        events.append(ev)
        if len(events) >= CALENDAR_EVENTS_CAP:
            break
    capped = len(events) >= CALENDAR_EVENTS_CAP
    return json.dumps(
        {
            "events": events[:CALENDAR_EVENTS_CAP],
            "days": days,
            "count": len(events[:CALENDAR_EVENTS_CAP]),
            "capped": capped,
            "source": "Calendar.app",
        }
    )


def tool_volume_control(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).strip().lower()
    if action not in ("get", "set", "mute", "unmute"):
        return json.dumps(
            {
                "ok": False,
                "error": "action must be one of: get, set, mute, unmute",
            }
        )
    level: int | None = None
    if action == "set":
        level_raw = args.get("level", None)
        if level_raw is None:
            return json.dumps({"ok": False, "error": "level (0-100) required when action is set"})
        try:
            level = int(level_raw)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "level must be an integer 0-100"})
        level = max(0, min(100, level))
    if platform.system() != "Darwin":
        # Still report clamped level on non-Darwin so callers/tests see validation.
        if action == "set" and level is not None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "volume_control is macOS-only (osascript)",
                    "level": level,
                }
            )
        return json.dumps({"ok": False, "error": "volume_control is macOS-only (osascript)"})

    if action == "set":
        assert level is not None
        script = f"set volume output volume {level}"
        try:
            code, out, err = _osascript(script, timeout=10.0)
        except FileNotFoundError:
            return json.dumps({"ok": False, "error": "osascript not found"})
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "osascript timed out"})
        except OSError as e:
            return json.dumps({"ok": False, "error": str(e)})
        if code != 0:
            return json.dumps(
                {"ok": False, "error": err or out or "set volume failed", "returncode": code}
            )
        return json.dumps({"ok": True, "action": "set", "level": level})

    if action == "mute":
        script = "set volume with output muted"
    elif action == "unmute":
        script = "set volume without output muted"
    else:
        script = """set vs to get volume settings
set vol to output volume of vs
set muted to output muted of vs
return (vol as string) & "|" & (muted as string)"""

    try:
        code, out, err = _osascript(script, timeout=10.0)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "osascript not found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "osascript timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if code != 0:
        return json.dumps(
            {"ok": False, "error": err or out or "volume_control failed", "returncode": code}
        )
    if action == "get":
        parts = (out or "").split("|")
        level = None
        muted = None
        try:
            level = int(parts[0].strip())
        except (ValueError, IndexError):
            pass
        if len(parts) > 1:
            muted = parts[1].strip().lower() in ("true", "yes", "1")
        return json.dumps({"ok": True, "action": "get", "level": level, "muted": muted, "raw": out})
    return json.dumps({"ok": True, "action": action})


def _timer_fire(timer_id: int, seconds: int, label: str) -> None:
    try:
        time.sleep(seconds)
    except Exception:  # noqa: BLE001
        return
    finally:
        with _TIMERS_LOCK:
            for i, t in enumerate(_ACTIVE_TIMERS):
                if t.get("id") == timer_id:
                    _ACTIVE_TIMERS.pop(i)
                    break
    note = f"Timer done: {label}" if label else "Timer done"
    if platform.system() == "Darwin":
        try:
            et = _escape_applescript(_clip_str(note, NOTIFY_MESSAGE_MAX))
            title = _escape_applescript("JARVIS Timer")
            _osascript(f'display notification "{et}" with title "{title}"', timeout=10.0)
        except Exception:  # noqa: BLE001
            pass


def tool_start_timer(args: dict[str, Any]) -> str:
    seconds_raw = args.get("seconds", None)
    minutes_raw = args.get("minutes", None)
    seconds: float | None = None
    if seconds_raw is not None and str(seconds_raw).strip() != "":
        try:
            seconds = float(seconds_raw)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "seconds must be a number"})
    elif minutes_raw is not None and str(minutes_raw).strip() != "":
        try:
            seconds = float(minutes_raw) * 60.0
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "minutes must be a number"})
    else:
        return json.dumps({"ok": False, "error": "provide seconds or minutes"})
    if seconds <= 0:
        return json.dumps({"ok": False, "error": "duration must be positive"})
    if seconds > TIMER_MAX_SECONDS:
        return json.dumps(
            {
                "ok": False,
                "error": f"duration capped at {TIMER_MAX_SECONDS}s (24h); got {int(seconds)}",
            }
        )
    sec_int = int(round(seconds))
    if sec_int < 1:
        sec_int = 1
    label = args.get("label", "")
    if label is None:
        label = ""
    if not isinstance(label, str):
        label = str(label)
    label = _clip_str(label.strip(), 200)
    ends_at = (datetime.now().astimezone() + timedelta(seconds=sec_int)).isoformat()
    with _TIMERS_LOCK:
        timer_id = max((t.get("id", 0) for t in _ACTIVE_TIMERS), default=0) + 1
        entry = {
            "id": timer_id,
            "seconds": sec_int,
            "label": label,
            "ends_at": ends_at,
            "started_at": datetime.now().astimezone().isoformat(),
        }
        _ACTIVE_TIMERS.append(entry)
    thread = threading.Thread(
        target=_timer_fire,
        args=(timer_id, sec_int, label),
        name=f"jarvis-timer-{timer_id}",
        daemon=True,
    )
    thread.start()
    return json.dumps(
        {"ok": True, "seconds": sec_int, "label": label, "ends_at": ends_at, "id": timer_id}
    )


def tool_list_timers(_: dict[str, Any]) -> str:
    now = datetime.now().astimezone()
    active: list[dict[str, Any]] = []
    with _TIMERS_LOCK:
        for t in list(_ACTIVE_TIMERS):
            item = dict(t)
            try:
                ends = datetime.fromisoformat(str(t.get("ends_at", "")))
                remaining = max(0, int((ends - now).total_seconds()))
                item["remaining_seconds"] = remaining
            except (TypeError, ValueError):
                item["remaining_seconds"] = None
            active.append(item)
    return json.dumps({"timers": active, "count": len(active)})


class _ReadableTextExtractor(HTMLParser):
    """Extract title + visible text; skip script/style/noscript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript"):
            self._skip_depth += 1
        elif t == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif t == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.body_parts.append(data)


def tool_fetch_url(args: dict[str, Any]) -> str:
    url = str(args.get("url", "")).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return json.dumps({"ok": False, "error": "url must start with http:// or https://"})
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return json.dumps({"ok": False, "error": "only http/https URLs allowed"})
    max_chars = args.get("max_chars", FETCH_URL_DEFAULT_MAX)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = FETCH_URL_DEFAULT_MAX
    if max_chars < 1:
        max_chars = FETCH_URL_DEFAULT_MAX
    if max_chars > FETCH_URL_HARD_MAX:
        max_chars = FETCH_URL_HARD_MAX
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True) as client:
            r = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            r.raise_for_status()
            raw = r.text
    except httpx.HTTPError as e:
        return json.dumps({"ok": False, "error": f"fetch failed: {e}", "url": url})

    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", cleaned)
    extractor = _ReadableTextExtractor()
    try:
        extractor.feed(cleaned)
        extractor.close()
    except Exception:  # noqa: BLE001
        pass
    title = re.sub(r"\s+", " ", "".join(extractor.title_parts)).strip()
    if not title:
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
        if m:
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    text_body = re.sub(r"\s+", " ", "".join(extractor.body_parts)).strip()
    if not text_body:
        text_body = re.sub(r"(?is)<[^>]+>", " ", cleaned)
        text_body = re.sub(r"\s+", " ", text_body).strip()
    truncated = len(text_body) > max_chars
    if truncated:
        text_body = text_body[:max_chars]
    return json.dumps(
        {
            "ok": True,
            "url": url,
            "title": title,
            "text": text_body,
            "truncated": truncated,
            "chars": len(text_body),
        }
    )


def tool_stock_quote(args: dict[str, Any]) -> str:
    symbol = str(args.get("symbol", "")).strip().upper()
    if not symbol:
        return json.dumps({"ok": False, "error": "symbol is required"})
    if not re.fullmatch(r"[A-Z0-9.\-]{1,20}", symbol):
        return json.dumps({"ok": False, "error": "invalid symbol"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
    params = {"interval": "1d", "range": "1d"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(
                url,
                params=params,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return json.dumps({"ok": False, "error": f"quote request failed: {e}", "symbol": symbol})
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({"ok": False, "error": f"invalid quote response: {e}", "symbol": symbol})

    try:
        chart = data.get("chart") or {}
        if chart.get("error"):
            return json.dumps({"ok": False, "error": str(chart["error"]), "symbol": symbol})
        results = chart.get("result") or []
        if not results or not isinstance(results[0], dict):
            return json.dumps({"ok": False, "error": "no quote data for symbol", "symbol": symbol})
        meta = results[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            return json.dumps({"ok": False, "error": "price unavailable", "symbol": symbol})
        currency = meta.get("currency") or ""
        prev = meta.get("chartPreviousClose")
        if prev is None:
            prev = meta.get("previousClose")
        change_pct = None
        if prev is not None:
            try:
                prev_f = float(prev)
                price_f = float(price)
                if prev_f != 0:
                    change_pct = round((price_f - prev_f) / prev_f * 100.0, 4)
            except (TypeError, ValueError):
                change_pct = None
        return json.dumps(
            {
                "ok": True,
                "symbol": meta.get("symbol") or symbol,
                "price": price,
                "currency": currency,
                "change_pct": change_pct,
                "previous_close": prev,
            }
        )
    except (TypeError, KeyError, IndexError) as e:
        return json.dumps({"ok": False, "error": f"could not parse quote: {e}", "symbol": symbol})


def tool_dark_mode(args: dict[str, Any]) -> str:
    mode = str(args.get("mode", "")).strip().lower()
    if mode not in ("on", "off", "toggle", "status"):
        return json.dumps({"ok": False, "error": "mode must be one of: on, off, toggle, status"})
    if platform.system() != "Darwin":
        return json.dumps({"ok": False, "error": "dark_mode is macOS-only (System Events)"})
    if mode == "status":
        script = """tell application "System Events"
  tell appearance preferences
    return dark mode as string
  end tell
end tell"""
    elif mode == "on":
        script = """tell application "System Events"
  tell appearance preferences
    set dark mode to true
  end tell
end tell"""
    elif mode == "off":
        script = """tell application "System Events"
  tell appearance preferences
    set dark mode to false
  end tell
end tell"""
    else:
        script = """tell application "System Events"
  tell appearance preferences
    set dark mode to not dark mode
    return dark mode as string
  end tell
end tell"""
    try:
        code, out, err = _osascript(script, timeout=15.0)
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "osascript not found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "osascript timed out"})
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if code != 0:
        return json.dumps(
            {"ok": False, "error": err or out or "dark_mode failed", "returncode": code}
        )
    dark = None
    if out:
        dark = out.strip().lower() in ("true", "yes", "1")
    result: dict[str, Any] = {"ok": True, "mode": mode}
    if dark is not None:
        result["dark"] = dark
    if mode in ("on", "off"):
        result["dark"] = mode == "on"
    return json.dumps(result)


def tool_daily_briefing(args: dict[str, Any]) -> str:
    """Orchestrate existing tools into one structured briefing JSON."""
    # city: omitted → Helsinki; explicit empty → skip weather
    if "city" not in args:
        city: str | None = "Helsinki"
    else:
        raw_city = args.get("city")
        if raw_city is None:
            city = None
        else:
            city = str(raw_city).strip() or None

    briefing: dict[str, Any] = {"ok": True}

    try:
        briefing["time"] = json.loads(tool_get_current_time({}))
    except Exception as e:  # noqa: BLE001
        briefing["time"] = {"error": str(e)}

    try:
        briefing["system"] = json.loads(tool_get_system_status({}))
    except Exception as e:  # noqa: BLE001
        briefing["system"] = {"error": str(e)}

    try:
        briefing["calendar"] = json.loads(tool_calendar_events({"days": 1}))
    except Exception as e:  # noqa: BLE001
        briefing["calendar"] = {"error": str(e), "events": []}

    if city:
        try:
            briefing["weather"] = json.loads(tool_get_weather({"location": city}))
        except Exception as e:  # noqa: BLE001
            briefing["weather"] = {"error": str(e)}
    else:
        briefing["weather"] = {"skipped": True}

    try:
        briefing["github"] = json.loads(tool_github_status({}))
    except Exception as e:  # noqa: BLE001
        briefing["github"] = {"error": str(e)}

    return json.dumps(briefing)



TOOL_DISPATCH = {
    "get_current_time": tool_get_current_time,
    "list_notes": tool_list_notes,
    "read_note": tool_read_note,
    "save_note": tool_save_note,
    "open_url": tool_open_url,
    "open_app": tool_open_app,
    "get_clipboard": tool_get_clipboard,
    "set_clipboard": tool_set_clipboard,
    "get_weather": tool_get_weather,
    "github_status": tool_github_status,
    "get_system_status": tool_get_system_status,
    "notify": tool_notify,
    "create_reminder": tool_create_reminder,
    "music_control": tool_music_control,
    "take_screenshot": tool_take_screenshot,
    "list_running_apps": tool_list_running_apps,
    "read_file": tool_read_file,
    "web_search": tool_web_search,
    "calendar_events": tool_calendar_events,
    "volume_control": tool_volume_control,
    "start_timer": tool_start_timer,
    "list_timers": tool_list_timers,
    "fetch_url": tool_fetch_url,
    "stock_quote": tool_stock_quote,
    "dark_mode": tool_dark_mode,
    "daily_briefing": tool_daily_briefing,
}


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def run_tool(name: str, arguments: Any) -> str:
    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool: {name}"})
    args = _parse_arguments(arguments)
    try:
        return fn(args)
    except Exception as e:  # noqa: BLE001 — surface to model as tool output
        return json.dumps({"error": str(e)})


def ensure_model(client: httpx.Client, model: str) -> None:
    """Fail fast if the configured model is not present in Ollama.

    Ollama returns names like ``llama3.1:8b``. Matching rules:
    - exact name match, or
    - wanted has no tag (``llama3.1``) and an available name is that base or ``base:…``, or
    - available has no tag and equals the wanted base.
    """
    r = client.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
    r.raise_for_status()
    data = r.json()
    names = [m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict) and m.get("name")]

    def matches(available: str, wanted: str) -> bool:
        if available == wanted:
            return True
        avail_base, _, avail_tag = available.partition(":")
        want_base, _, want_tag = wanted.partition(":")
        if not want_tag and (available == wanted or avail_base == wanted):
            return True
        if not avail_tag and available == want_base:
            return True
        return False

    if any(matches(n, model) for n in names):
        return

    print(
        f"Model not found in Ollama: {model!r}\n"
        f"  Pull it with:  ollama pull {model}\n"
        f"  Or set another model:  OLLAMA_MODEL=<name>\n"
        f"  Available: {', '.join(names) if names else '(none)'}",
        file=sys.stderr,
    )
    sys.exit(1)


_CHITCHAT_RE = re.compile(
    r"^(?:hi|hello|hey|howdy|yo|sup|hiya|thanks|thank you|thx|cheers|"
    r"good (?:afternoon|evening|night)|how are you|how(?:'s| is) it going|"
    r"what(?:'s| is) up|evening|bye|goodbye|see you|"
    r"ok|okay|sure|cool|nice|great|awesome|got it)(?:[!.?\s].*)?$",
    re.IGNORECASE,
)

# These should get tools so daily_briefing can run (not treated as pure chitchat).
_BRIEFING_RE = re.compile(
    r"^(?:good\s+morning|brief\s+me|status\s+report|morning\s+brief(?:ing)?|"
    r"daily\s+brief(?:ing)?|give\s+me\s+(?:a\s+)?(?:brief|status|update))(?:[!.?\s].*)?$",
    re.IGNORECASE,
)


def is_chitchat(text: str) -> bool:
    """Short greetings/thanks — skip tools for a faster Ollama round-trip.

    Briefing phrases (good morning / brief me / status report) keep tools enabled.
    """
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if _BRIEFING_RE.match(t):
        return False
    return bool(_CHITCHAT_RE.match(t))


def chat_round(
    client: httpx.Client,
    model: str,
    messages: list[dict[str, Any]],
    *,
    use_tools: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """One API call; returns updated messages and assistant text (if any)."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if use_tools:
        payload["tools"] = TOOLS
    r = client.post(
        f"{OLLAMA_HOST}/api/chat",
        json=payload,
        timeout=180.0,
    )
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    role = msg.get("role", "assistant")
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls")

    out_messages = list(messages)
    out_messages.append({"role": role, "content": content, "tool_calls": tool_calls})

    if not tool_calls:
        return out_messages, content if content else None

    # Append tool results (Ollama/OpenAI-style)
    for i, call in enumerate(tool_calls):
        func = (call.get("function") or {}) if isinstance(call, dict) else {}
        name = func.get("name") or ""
        arguments = func.get("arguments")
        tool_id = call.get("id") if isinstance(call, dict) else None
        result = run_tool(name, arguments)
        tool_msg: dict[str, Any] = {
            "role": "tool",
            "content": result,
        }
        if tool_id:
            tool_msg["tool_call_id"] = tool_id
        # Some stacks want name on tool message
        tool_msg["name"] = name
        out_messages.append(tool_msg)

    return out_messages, None


def run_turn(
    client: httpx.Client, model: str, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    """Run tool rounds until assistant returns text or cap hit.

    Short greetings/chitchat skip the tools schema for a faster single round-trip.
    """
    state = messages
    last_text: str | None = None
    use_tools = True
    for m in reversed(messages):
        if m.get("role") == "user":
            use_tools = not is_chitchat(str(m.get("content") or ""))
            break

    rounds = 1 if not use_tools else MAX_TOOL_ROUNDS
    for _ in range(rounds):
        state, text = chat_round(client, model, state, use_tools=use_tools)
        if text is not None:
            last_text = text
            break
        # If a no-tools call somehow returned tool_calls (shouldn't), stop
        if not use_tools:
            break
    if last_text is None:
        last_text = "(No reply — try rephrasing or check Ollama logs.)"
    return state, last_text


def main() -> None:
    model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
    print(f"JARVIS — model={model}  ollama={OLLAMA_HOST}")
    print("Commands: /exit /quit  |  /clear  |  /model <name>")
    print("Notes folder:", NOTES_DIR)
    print()

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    with httpx.Client() as client:
        try:
            r = client.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print("Cannot reach Ollama at", OLLAMA_HOST, "—", e, file=sys.stderr)
            print("Start it with: brew services start ollama", file=sys.stderr)
            sys.exit(1)

        ensure_model(client, model)

        while True:
            try:
                line = input("You › ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line in ("/exit", "/quit"):
                break
            if line == "/clear":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("Session cleared.\n")
                continue
            if line.startswith("/model "):
                model = line.split(maxsplit=1)[1].strip() or model
                print(f"Model set to {model}\n")
                continue

            messages.append({"role": "user", "content": line})
            print("JARVIS › Thinking…", flush=True)
            try:
                messages, reply = run_turn(client, model, messages)
            except httpx.TimeoutException:
                print(
                    "JARVIS › (Timed out waiting for Ollama — is the model loaded? try again)\n",
                    flush=True,
                )
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                continue
            except httpx.HTTPError as e:
                print(f"JARVIS › (Ollama error: {e})\n", flush=True)
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                continue
            # `messages` already includes the final assistant message from the API turn
            print(f"JARVIS › {reply}\n")


if __name__ == "__main__":
    main()
