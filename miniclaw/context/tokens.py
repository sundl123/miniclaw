"""Token estimation for context management."""
from __future__ import annotations

import json


def _bytes_per_token(text: str) -> float:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return 2.0
    return 4.0


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(round(len(text) / _bytes_per_token(text))))


def estimate_message_tokens(msg: dict) -> int:
    total = 0
    content = msg.get("content") or ""
    if isinstance(content, str):
        total += estimate_text_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                total += estimate_text_tokens(part.get("text") or "")

    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments") or ""
        if isinstance(args, str):
            total += estimate_text_tokens(args)
        else:
            total += estimate_text_tokens(json.dumps(args, ensure_ascii=False))

    for rd in msg.get("reasoning_details") or []:
        if isinstance(rd, dict):
            total += estimate_text_tokens(rd.get("text") or "")
        else:
            total += estimate_text_tokens(getattr(rd, "text", "") or "")

    return total


def estimate_messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def update_usage_from_response(ctx_mgmt: dict, usage) -> None:
    """Store prompt_tokens from API usage for next estimation."""
    if usage is None:
        return
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if prompt_tokens is not None and prompt_tokens > 0:
        ctx_mgmt["last_prompt_tokens"] = prompt_tokens


def get_estimated_tokens(messages: list[dict], ctx_mgmt: dict) -> int:
    """Prefer last API usage; fall back to local estimate."""
    last = ctx_mgmt.get("last_prompt_tokens")
    if last is not None and last > 0:
        return last
    return estimate_messages_tokens(messages)
