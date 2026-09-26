"""Durable long-term memory for JARVIS (local JSON store)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Injectable for tests (patch or assign before calls).
MEMORY_PATH: Path = Path.home() / ".jarvis" / "memory.json"

MEMORY_TEXT_MAX = 500
MEMORY_INJECT_CAP = 6
RECALL_TOP = 10
RECALL_RECENT = 15
LIST_DEFAULT_LIMIT = 20

MEMORY_BLOCK_MARKER = "## Long-term memory"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return f"m_{uuid.uuid4().hex[:12]}"


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        s = str(t).strip()
        if s and s not in out:
            out.append(s[:64])
    return out[:20]


def ensure_memory_dir(path: Path | None = None) -> Path:
    p = path or MEMORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_memories(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or MEMORY_PATH
    if not p.is_file():
        return []
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            out.append(item)
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def save_memories(items: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or MEMORY_PATH
    ensure_memory_dir(p)
    _atomic_write(p, json.dumps(items, indent=2, ensure_ascii=False) + "\n")


def remember(
    text: str,
    tags: list[str] | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Upsert by exact text match; cap text length. Returns the saved record."""
    cleaned = (text or "").strip()
    if not cleaned:
        return {"error": "text is required"}
    if len(cleaned) > MEMORY_TEXT_MAX:
        cleaned = cleaned[:MEMORY_TEXT_MAX]
    tag_list = _normalize_tags(tags)
    items = load_memories(path)
    now = _utc_now_iso()
    for item in items:
        if item.get("text") == cleaned:
            item["updated_at"] = now
            if tag_list:
                # Merge tags on update
                existing = _normalize_tags(item.get("tags"))
                merged = existing[:]
                for t in tag_list:
                    if t not in merged:
                        merged.append(t)
                item["tags"] = merged[:20]
            save_memories(items, path)
            return {"ok": True, "updated": True, "memory": item}
    record = {
        "id": _new_id(),
        "text": cleaned,
        "tags": tag_list,
        "created_at": now,
        "updated_at": now,
    }
    items.append(record)
    save_memories(items, path)
    return {"ok": True, "updated": False, "memory": record}


def _sort_newest(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(m: dict[str, Any]) -> str:
        return str(m.get("updated_at") or m.get("created_at") or "")

    return sorted(items, key=key, reverse=True)


def recall(query: str | None = None, *, path: Path | None = None) -> dict[str, Any]:
    """Case-insensitive substring match on text/tags (top 10), or newest 15 if no query."""
    items = load_memories(path)
    if query is None or not str(query).strip():
        recent = _sort_newest(items)[:RECALL_RECENT]
        return {"ok": True, "count": len(recent), "memories": recent}
    q = str(query).strip().lower()
    hits: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or "").lower()
        tags = " ".join(str(t).lower() for t in (item.get("tags") or []))
        if q in text or q in tags:
            hits.append(item)
    hits = _sort_newest(hits)[:RECALL_TOP]
    return {"ok": True, "query": query, "count": len(hits), "memories": hits}


def list_memories(limit: int = LIST_DEFAULT_LIMIT, *, path: Path | None = None) -> dict[str, Any]:
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = LIST_DEFAULT_LIMIT
    lim = max(1, min(lim, 100))
    items = _sort_newest(load_memories(path))[:lim]
    return {"ok": True, "count": len(items), "memories": items, "path": str(path or MEMORY_PATH)}


def forget(
    *,
    id: str | None = None,
    text: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Delete by id or exact text. Returns ok/not found."""
    mid = (id or "").strip() if id else ""
    exact = (text or "").strip() if text else ""
    if not mid and not exact:
        return {"ok": False, "error": "id or text required"}
    items = load_memories(path)
    kept: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for item in items:
        match = False
        if mid and str(item.get("id") or "") == mid:
            match = True
        elif exact and str(item.get("text") or "") == exact:
            match = True
        if match and removed is None:
            removed = item
            continue
        kept.append(item)
    if removed is None:
        return {"ok": False, "found": False, "error": "not found"}
    save_memories(kept, path)
    return {"ok": True, "found": True, "deleted": removed}


def format_memory_block(path: Path | None = None, *, cap: int = MEMORY_INJECT_CAP) -> str:
    """Compact bullet list for system-message injection (newest first)."""
    items = _sort_newest(load_memories(path))[: max(0, cap)]
    lines = [MEMORY_BLOCK_MARKER]
    if not items:
        lines.append("(none yet)")
    else:
        for item in items:
            text = str(item.get("text") or "").strip().replace("\n", " ")
            if len(text) > 120:
                text = text[:117] + "..."
            lines.append(f"- {text}")
    return "\n".join(lines)


def inject_memory_messages(messages: list[dict[str, Any]], path: Path | None = None) -> list[dict[str, Any]]:
    """Ensure a sticky memory system message sits after the main system prompt.

    Refreshes content each call so tool updates are visible on the next model round.
    """
    block = format_memory_block(path)
    out = list(messages)
    for i, m in enumerate(out):
        content = m.get("content")
        if (
            m.get("role") == "system"
            and isinstance(content, str)
            and content.lstrip().startswith(MEMORY_BLOCK_MARKER)
        ):
            out[i] = {"role": "system", "content": block}
            return out
    insert_at = 1 if out and out[0].get("role") == "system" else 0
    out.insert(insert_at, {"role": "system", "content": block})
    return out
