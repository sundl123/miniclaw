"""Anchored view helpers for session_search discovery."""
from __future__ import annotations

from typing import Any

from miniclaw.sessions.db import SessionDB


def _shape_message(m: dict[str, Any], *, anchor_seq: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "seq": m.get("seq"),
        "role": m.get("role"),
        "content": m.get("content"),
        "ts": m.get("ts"),
    }
    if m.get("tool_name"):
        entry["tool_name"] = m.get("tool_name")
    if m.get("tool_calls"):
        entry["tool_calls"] = m.get("tool_calls")
    if m.get("tool_call_id"):
        entry["tool_call_id"] = m.get("tool_call_id")
    if anchor_seq is not None and m.get("seq") == anchor_seq:
        entry["anchor"] = True
    return {k: v for k, v in entry.items() if v is not None or k == "content"}


def get_anchored_view(
    db: SessionDB,
    session_id: str,
    around_seq: int,
    *,
    window: int = 5,
    bookend: int = 3,
) -> dict[str, Any]:
    """Return window around anchor plus session bookends."""
    primitive = db.get_messages_around(session_id, around_seq, window=window)
    window_rows = primitive.get("window") or []
    if not window_rows:
        return {
            "window": [],
            "messages_before": 0,
            "messages_after": 0,
            "bookend_start": [],
            "bookend_end": [],
        }

    keep_roles = {"user", "assistant", "tool"}
    filtered = [
        m for m in window_rows
        if m.get("seq") == around_seq or m.get("role") in keep_roles
    ]

    window_min_seq = window_rows[0]["seq"]
    window_max_seq = window_rows[-1]["seq"]
    bookends = db.get_bookends(
        session_id,
        bookend=bookend,
        window_min_seq=window_min_seq,
        window_max_seq=window_max_seq,
    )

    return {
        "window": [_shape_message(m, anchor_seq=around_seq) for m in filtered],
        "messages_before": primitive.get("messages_before", 0),
        "messages_after": primitive.get("messages_after", 0),
        "bookend_start": [_shape_message(m) for m in bookends["bookend_start"]],
        "bookend_end": [_shape_message(m) for m in bookends["bookend_end"]],
    }
