"""Live agent-activity aggregation with owner-aware redaction.

The app already tracks in-flight work in three places:

* chat / agent streams — ``routes.chat_routes._active_streams``
* research tasks — ``research_handler._active_tasks``
* detached shell/background jobs — the ``src.bg_jobs`` store

This module normalises them into one list and applies a single privacy rule:
a thread's title (and any user-authored text such as the research query) is
only revealed to its owner, or to an admin. Everyone else sees the model name
and the stage ("what it is doing"), never the content.

Kept free of FastAPI/app imports so it can be unit tested directly.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

STAGE_CHAT = "chat"
STAGE_AGENT = "agent"
STAGE_RESEARCH = "research"
STAGE_BACKGROUND = "background"

_STATUS_WORKING = "working"

SessionInfo = Callable[[Optional[str]], Tuple[Optional[str], Optional[str], Optional[str]]]


def make_session_info(session_manager) -> SessionInfo:
    """Build a session_id -> (owner, title, model) resolver."""

    def _info(session_id: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if not session_manager or not session_id:
            return None, None, None
        try:
            sess = session_manager.get_session(session_id)
        except Exception:
            return None, None, None
        if sess is None:
            return None, None, None
        return (
            getattr(sess, "owner", None),
            getattr(sess, "name", None),
            getattr(sess, "model", None),
        )

    return _info


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def collect_activity(
    *,
    chat_streams: Optional[Dict[str, Any]] = None,
    research_tasks: Optional[Dict[str, Any]] = None,
    bg_jobs: Optional[Dict[str, Any]] = None,
    session_info: Optional[SessionInfo] = None,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Return a normalised list of in-flight work items."""
    now = time.time() if now is None else now
    info = session_info or (lambda _sid: (None, None, None))
    items: List[Dict[str, Any]] = []

    for session_id, raw in (chat_streams or {}).items():
        rec = _as_dict(raw)
        if rec.get("status") not in ("streaming", "running"):
            continue
        owner, title, model = info(session_id)
        mode = str(rec.get("mode") or "").lower()
        if rec.get("is_research"):
            stage = STAGE_RESEARCH
        elif mode in ("agent", "plan"):
            stage = STAGE_AGENT
        else:
            stage = STAGE_CHAT
        items.append({
            "session_id": session_id,
            "kind": stage,
            "stage": stage,
            "owner": owner,
            "title": title,
            "model": model or rec.get("model"),
            "query": rec.get("query"),
            "status": _STATUS_WORKING,
            "started_at": rec.get("started_at") or rec.get("started") or now,
            "updated_at": now,
        })

    for session_id, raw in (research_tasks or {}).items():
        entry = _as_dict(raw)
        if entry.get("status") != "running":
            continue
        owner = entry.get("owner") or None
        _owner, title, model = info(session_id)
        items.append({
            "session_id": session_id,
            "kind": STAGE_RESEARCH,
            "stage": STAGE_RESEARCH,
            "owner": owner or _owner,
            "title": title,
            "model": model,
            "query": entry.get("query"),
            "status": _STATUS_WORKING,
            "started_at": entry.get("started_at") or now,
            "updated_at": now,
        })

    for job_id, raw in (bg_jobs or {}).items():
        rec = _as_dict(raw)
        if rec.get("status") != "running":
            continue
        session_id = rec.get("session_id")
        owner, title, model = info(session_id)
        items.append({
            "session_id": session_id,
            "job_id": job_id,
            "kind": STAGE_BACKGROUND,
            "stage": STAGE_BACKGROUND,
            "owner": owner,
            "title": title,
            "model": model,
            "query": rec.get("command"),
            "status": _STATUS_WORKING,
            "started_at": rec.get("started_at") or now,
            "updated_at": now,
        })

    return items


def _reveal(item: Dict[str, Any], user: Optional[str], is_admin: bool) -> bool:
    owner = item.get("owner")
    if is_admin:
        return True
    if not user:
        # Auth disabled / single-user mode: no separate owner to protect.
        return True
    return bool(owner) and owner == user


def redact_items(
    items: Iterable[Dict[str, Any]],
    user: Optional[str],
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """Strip owner-only fields (title, query) from items the caller doesn't own."""
    out: List[Dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        reveal = _reveal(item, user, is_admin)
        item["is_owner"] = reveal
        if not reveal:
            item["title"] = None
            item["query"] = None
            item["session_id"] = None
            item["job_id"] = None
        out.append(item)
    return out


def snapshot(
    items: Iterable[Dict[str, Any]],
    user: Optional[str],
    is_admin: bool = False,
) -> Dict[str, Any]:
    """Owner-aware view used by the web endpoint."""
    redacted = redact_items(items, user, is_admin)
    working = [i for i in redacted if i.get("status") == _STATUS_WORKING]
    return {
        "count": len(working),
        "working": len(working),
        "items": redacted,
        "updated": time.time(),
    }


def describe_item(item: Dict[str, Any]) -> str:
    """Short human label: title when owned, otherwise model + stage."""
    title = item.get("title")
    model = item.get("model") or "unknown model"
    stage = item.get("stage") or "working"
    if title:
        return f"{title} — {model} ({stage})"
    return f"{model} ({stage})"


def anonymized_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Model + stage only — safe for a globally visible entity."""
    return [
        {
            "model": i.get("model") or "unknown",
            "stage": i.get("stage") or "working",
            "status": i.get("status") or _STATUS_WORKING,
        }
        for i in items
    ]