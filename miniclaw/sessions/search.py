"""session_search tool: browse, discovery, scroll."""
from __future__ import annotations

import json
from typing import Any

from miniclaw.sessions.anchored import get_anchored_view
from miniclaw.sessions.config import SessionsConfig
from miniclaw.sessions.db import SessionDB

SESSION_SEARCH_DESCRIPTION = (
    "Search past sessions in the local session DB, or scroll inside one. "
    "FTS-backed retrieval over stored messages. No LLM calls — returns actual "
    "messages from the database.\n\n"
    "THREE CALLING SHAPES (inferred from args):\n"
    "1. SCROLL — pass session_id + around_seq. Window of messages around the anchor.\n"
    "2. DISCOVERY — pass query. Full-text search across past sessions.\n"
    "3. BROWSE — no query and no scroll args. Recent sessions list.\n\n"
    "Use this to recall what you discussed before (topics, decisions, progress). "
    "For durable facts and preferences, use the memory tool instead — do not "
    "paste entire conversations into MEMORY.md.\n\n"
    "Current session is excluded from browse/discovery to avoid duplicates."
)


def get_session_search_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "session_search",
            "description": SESSION_SEARCH_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Full-text search query (discovery shape).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions in discovery/browse (default 3, max 10).",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["newest", "oldest"],
                        "description": "Discovery sort order. Omit for relevance (BM25).",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Target session for scroll shape.",
                    },
                    "around_seq": {
                        "type": "integer",
                        "description": "Anchor seq within session for scroll shape.",
                    },
                    "window": {
                        "type": "integer",
                        "description": "Scroll window radius (default 5, max 20).",
                    },
                },
                "required": [],
            },
        },
    }


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(n, hi))


def handle_session_search(
    args: dict,
    *,
    db: SessionDB | None = None,
    current_session_id: str | None = None,
    config: SessionsConfig | None = None,
) -> str:
    if db is None:
        return json.dumps(
            {"success": False, "error": "Sessions are not enabled or DB not initialized."},
            ensure_ascii=False,
        )

    cfg = config or SessionsConfig()
    session_id = (args.get("session_id") or "").strip() or None
    around_seq = args.get("around_seq")
    query = (args.get("query") or "").strip()

    # 1. SCROLL
    if session_id and around_seq is not None:
        return _scroll(
            db, session_id, around_seq,
            window=_clamp_int(args.get("window"), cfg.search_window, 1, 20),
            current_session_id=current_session_id,
        )

    # 2. DISCOVERY
    if query:
        return _discover(
            db, query,
            limit=_clamp_int(args.get("limit"), cfg.search_default_limit, 1, 10),
            sort=args.get("sort"),
            window=cfg.search_window,
            current_session_id=current_session_id,
        )

    # 3. BROWSE
    return _browse(
        db,
        limit=_clamp_int(args.get("limit"), cfg.browse_limit, 1, 20),
        current_session_id=current_session_id,
    )


def _browse(
    db: SessionDB,
    *,
    limit: int,
    current_session_id: str | None,
) -> str:
    results = db.browse_sessions(limit, exclude_session_id=current_session_id)
    return json.dumps({
        "success": True,
        "shape": "browse",
        "results": results,
        "count": len(results),
        "message": (
            f"Showing {len(results)} recent sessions. "
            "Pass query= to search, or session_id+around_seq to scroll."
        ),
    }, ensure_ascii=False)


def _discover(
    db: SessionDB,
    query: str,
    *,
    limit: int,
    sort: str | None,
    window: int,
    current_session_id: str | None,
) -> str:
    raw = db.search_messages(
        query,
        limit=limit,
        sort=sort,
        exclude_session_id=current_session_id,
    )
    if not raw:
        return json.dumps({
            "success": True,
            "shape": "discovery",
            "query": query,
            "hits": [],
            "count": 0,
            "message": "No matching sessions found.",
        }, ensure_ascii=False)

    hits = []
    for row in raw:
        sid = row["session_id"]
        match_seq = row["seq"]
        session_meta = db.get_session(sid) or {}
        view = get_anchored_view(db, sid, match_seq, window=window)
        hits.append({
            "session_id": sid,
            "match_seq": match_seq,
            "snippet": row.get("snippet", ""),
            "role": row.get("role"),
            "ts": row.get("ts"),
            "session_meta": {
                "started_at": session_meta.get("started_at"),
                "updated_at": session_meta.get("updated_at"),
                "workspace": session_meta.get("workspace"),
                "model": session_meta.get("model"),
            },
            "window": view["window"],
            "bookend_start": view["bookend_start"],
            "bookend_end": view["bookend_end"],
            "messages_before": view["messages_before"],
            "messages_after": view["messages_after"],
        })

    return json.dumps({
        "success": True,
        "shape": "discovery",
        "query": query,
        "hits": hits,
        "count": len(hits),
    }, ensure_ascii=False)


def _scroll(
    db: SessionDB,
    session_id: str,
    around_seq: int,
    *,
    window: int,
    current_session_id: str | None,
) -> str:
    try:
        around_seq = int(around_seq)
    except (TypeError, ValueError):
        return json.dumps(
            {"success": False, "error": "scroll requires integer around_seq."},
            ensure_ascii=False,
        )

    if current_session_id and session_id == current_session_id:
        return json.dumps({
            "success": False,
            "error": (
                "scroll rejected: target is the current session "
                "(already in active context)."
            ),
        }, ensure_ascii=False)

    session_meta = db.get_session(session_id)
    if not session_meta:
        return json.dumps(
            {"success": False, "error": f"session_id not found: {session_id}"},
            ensure_ascii=False,
        )

    view = db.get_messages_around(session_id, around_seq, window=window)
    messages = view.get("window") or []
    if not messages:
        return json.dumps({
            "success": False,
            "error": f"around_seq {around_seq} not found in session {session_id}.",
        }, ensure_ascii=False)

    shaped = []
    for m in messages:
        entry = {
            "seq": m.get("seq"),
            "role": m.get("role"),
            "content": m.get("content"),
            "ts": m.get("ts"),
        }
        if m.get("tool_name"):
            entry["tool_name"] = m.get("tool_name")
        if m.get("seq") == around_seq:
            entry["anchor"] = True
        shaped.append(entry)

    return json.dumps({
        "success": True,
        "shape": "scroll",
        "session_id": session_id,
        "around_seq": around_seq,
        "window": window,
        "session_meta": {
            "started_at": session_meta.get("started_at"),
            "updated_at": session_meta.get("updated_at"),
            "workspace": session_meta.get("workspace"),
            "model": session_meta.get("model"),
        },
        "messages": shaped,
        "messages_before": view.get("messages_before", 0),
        "messages_after": view.get("messages_after", 0),
    }, ensure_ascii=False)
