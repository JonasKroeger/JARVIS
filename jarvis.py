#!/usr/bin/env python3
"""
Local JARVIS — text chat with Ollama, session memory, and a few safe tools.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MAX_TOOL_ROUNDS = 6

NOTES_DIR = Path.home() / ".jarvis" / "notes"

SYSTEM_PROMPT = """You are JARVIS, a calm, precise personal AI assistant running locally for your user.
Speak clearly and briefly unless asked for detail. You may use dry wit sparingly; never cruel or smug.
When tools are needed, call them — do not invent timestamps, file contents, or command output.

Answer factual questions directly. Straightforward history, dates, geography, and well-documented public events
(including conflicts, wars, and historical figures) are normal reference topics: give neutral, encyclopedia-style
facts. Do not refuse ordinary educational or historical questions. Reserve brief refusals for requests that ask
for instructions to harm people, break the law, or produce illegal or exploitative material."""


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


TOOL_DISPATCH = {
    "get_current_time": tool_get_current_time,
    "list_notes": tool_list_notes,
    "read_note": tool_read_note,
    "save_note": tool_save_note,
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


def chat_round(
    client: httpx.Client, model: str, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """One API call; returns updated messages and assistant text (if any)."""
    r = client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "stream": False,
        },
        timeout=600.0,
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
    """Run tool rounds until assistant returns text or cap hit."""
    state = messages
    last_text: str | None = None
    for _ in range(MAX_TOOL_ROUNDS):
        state, text = chat_round(client, model, state)
        if text is not None:
            last_text = text
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
            messages, reply = run_turn(client, model, messages)
            # `messages` already includes the final assistant message from the API turn
            print(f"JARVIS › {reply}\n")


if __name__ == "__main__":
    main()
