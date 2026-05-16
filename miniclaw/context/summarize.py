"""Full conversation summarization (compaction)."""
from __future__ import annotations

import json
import re

from openai import OpenAI

from miniclaw.config import DEFAULT_HTTP_TIMEOUT
from miniclaw.context.config import ContextConfig
from miniclaw.context.micro_compact import micro_compact
from miniclaw.context.tokens import estimate_messages_tokens
_SUMMARY_SYSTEM = "You are a helpful AI assistant tasked with summarizing conversations."

_SUMMARY_USER_TEMPLATE = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

Summarize the conversation below for continuation in a new session.

Output format:
<analysis>
(brief internal notes — will be discarded)
</analysis>
<summary>
1. User intent: ...
2. Key files/code: ...
3. Errors and fixes: ...
4. Completed work: ...
5. Pending tasks: ...
6. Next step: ... (quote the most recent user message verbatim if possible)
</summary>

{extra}

<conversation>
{conversation}
</conversation>"""


def _messages_to_text(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            continue
        content = msg.get("content") or ""
        if isinstance(content, str) and content:
            parts.append(f"[{role}]\n{content}")
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                parts.append(
                    f"[assistant tool_call] {fn.get('name')}: {fn.get('arguments', '')[:500]}"
                )
    return "\n\n".join(parts)


def _parse_summary(text: str) -> str | None:
    m = re.search(r"<summary>\s*(.*?)\s*</summary>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip() if text.strip() else None


def _rebuild_messages(
    system_msg: dict,
    summary_text: str,
    tail: list[dict],
) -> list[dict]:
    boundary = (
        "This session is being continued from a previous conversation that ran out of context.\n"
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"Summary:\n{summary_text}\n\n"
        "Recent messages are preserved verbatim below."
    )
    return [
        system_msg,
        {"role": "user", "content": boundary, "is_compact_summary": True},
        *tail,
    ]


def summarize_conversation(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    *,
    extra_instructions: str = "",
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> tuple[list[dict], bool]:
    """Summarize conversation history. Returns (new_messages, success)."""
    if len(messages) < 2:
        return messages, False

    keep = cfg.summarize.keep_recent_messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    system_msg = system_msgs[0] if system_msgs else {"role": "system", "content": ""}
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) <= keep:
        return messages, False

    to_summarize = non_system[:-keep]
    tail = non_system[-keep:]

    # Pre-compact old content to reduce summarize request size
    working = [system_msg, *to_summarize]
    micro_compact(working, cfg)

    conversation = _messages_to_text(to_summarize)
    extra = f"\nAdditional instructions:\n{extra_instructions}" if extra_instructions else ""
    user_prompt = _SUMMARY_USER_TEMPLATE.format(
        extra=extra, conversation=conversation[:120_000],
    )

    summarize_messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        from miniclaw.api import chat_raw  # lazy: avoid circular import with api

        msg, _ = chat_raw(
            client,
            summarize_messages,
            model=model,
            timeout=timeout,
            max_tokens=cfg.summarize.max_summary_output_tokens,
        )
        raw = (msg.get("content") or "").strip()
        summary = _parse_summary(raw)
        if not summary:
            return messages, False
        return _rebuild_messages(system_msg, summary, tail), True
    except Exception:
        return messages, False
