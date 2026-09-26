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
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MAX_TOOL_ROUNDS = 6
CLIPBOARD_MAX_CHARS = 20_000

NOTES_DIR = Path.home() / ".jarvis" / "notes"

SYSTEM_PROMPT = """You are JARVIS, a calm, precise local assistant. Be brief unless asked for detail;
dry wit is fine, never cruel. Call tools for real actions/data — never invent timestamps, notes,
clipboard, weather, GitHub, or command output.

Tools: open_url, open_app, get_clipboard/set_clipboard, get_weather, github_status, time, notes.
Greetings/chitchat → plain text, no tools. Only tool-call for actions or live data.

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
    r"good (?:morning|afternoon|evening|night)|how are you|how(?:'s| is) it going|"
    r"what(?:'s| is) up|morning|evening|bye|goodbye|see you|"
    r"ok|okay|sure|cool|nice|great|awesome|got it)(?:[!.?\s].*)?$",
    re.IGNORECASE,
)


def is_chitchat(text: str) -> bool:
    """Short greetings/thanks — skip tools for a faster Ollama round-trip."""
    t = (text or "").strip()
    if not t or len(t) > 40:
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
