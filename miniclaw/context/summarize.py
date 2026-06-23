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

Write an <analysis> block (brief notes), then a <summary> block with six numbered sections.
Each section MUST contain concrete facts from the conversation — never use "..." or placeholder text.

Required sections inside <summary>:
1. User intent: (what the user asked for)
2. Key files/code: (paths, modules, snippets mentioned)
3. Errors and fixes: (errors encountered and how they were resolved, or "none")
4. Completed work: (what was done)
5. Pending tasks: (what remains, or "none")
6. Next step: (quote the latest user message verbatim when possible)

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
            parts.append(f"[{role}]\n{content[:8000]}")
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                parts.append(
                    f"[assistant tool_call] {fn.get('name')}: {fn.get('arguments', '')[:500]}"
                )
    return "\n\n".join(parts)


_STRIP_BLOCK_PATTERNS = (
    r"<think>.*?</think>",
    r"<thinking>.*?</thinking>",
    r"<analysis>.*?</analysis>",
)


def _strip_non_summary_blocks(text: str) -> str:
    """Remove thinking/analysis drafts before parsing summary."""
    cleaned = text
    for pattern in _STRIP_BLOCK_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _parse_summary(text: str) -> str | None:
    """Extract summary body; never fall back to full raw on parse failure."""
    cleaned = _strip_non_summary_blocks(text)
    if not cleaned:
        return None

    m = re.search(
        r"<summary>\s*(.*?)\s*</summary>",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        body = m.group(1).strip()
        return body if body else None

    open_m = re.search(r"<summary>\s*", cleaned, re.IGNORECASE)
    if open_m:
        body = cleaned[open_m.end() :].strip()
        return body if body else None

    return None


def _is_valid_summary(summary: str) -> bool:
    """Reject empty summaries, template echoes, or leaked thinking tags."""
    text = summary.strip()
    if len(text) < 80:
        return False
    if re.search(
        r"</?\s*(?:redacted_thinking|thinking|analysis)\s*>",
        text,
        re.IGNORECASE,
    ):
        return False
    # MiniMax sometimes copies the old template literally.
    if re.search(r"User intent:\s*\.\.\.", text, re.IGNORECASE):
        return False
    if text.count("...") >= 4 and len(text) < 400:
        return False
    return True


def _tool_call_id(tc: dict) -> str:
    return tc.get("id") or tc.get("tool_use_id") or ""


def _assistant_has_tool_id(msg: dict, tool_call_id: str) -> bool:
    if msg.get("role") != "assistant" or not tool_call_id:
        return False
    for tc in msg.get("tool_calls") or []:
        if _tool_call_id(tc) == tool_call_id:
            return True
    return False


def prepare_tail_for_rebuild(non_system: list[dict], keep: int) -> tuple[list[dict], list[dict]]:
    """Split messages into (to_summarize, tail) with valid tool pairings in tail.

    Naive ``non_system[-keep:]`` can leave tool messages whose parent assistant
    was summarized away, which breaks OpenAI-compatible APIs.
    """
    if len(non_system) <= keep:
        return [], list(non_system)

    start = len(non_system) - keep

    # Expand backward so leading tool messages include their assistant parent.
    while start > 0 and non_system[start].get("role") == "tool":
        tid = non_system[start].get("tool_call_id") or ""
        parent_idx = None
        for i in range(start - 1, -1, -1):
            if _assistant_has_tool_id(non_system[i], tid):
                parent_idx = i
                break
        if parent_idx is None:
            start += 1
        else:
            start = parent_idx

    to_summarize = list(non_system[:start])
    tail = list(non_system[start:])

    # Drop tool messages with no matching assistant in tail.
    assistant_ids: set[str] = set()
    for msg in tail:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tid = _tool_call_id(tc)
                if tid:
                    assistant_ids.add(tid)

    filtered: list[dict] = []
    for msg in tail:
        if msg.get("role") == "tool":
            if msg.get("tool_call_id") not in assistant_ids:
                continue
        filtered.append(msg)

    # Strip tool_calls from assistant when matching tool messages are missing.
    result: list[dict] = []
    for i, msg in enumerate(filtered):
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            result.append(msg)
            continue

        following_ids: set[str] = set()
        for j in range(i + 1, len(filtered)):
            role = filtered[j].get("role")
            if role in ("user", "assistant"):
                break
            if role == "tool":
                tid = filtered[j].get("tool_call_id")
                if tid:
                    following_ids.add(tid)

        complete = [
            tc for tc in msg["tool_calls"]
            if _tool_call_id(tc) in following_ids
        ]
        if not complete:
            cleaned = {k: v for k, v in msg.items() if k != "tool_calls"}
            result.append(cleaned)
        elif len(complete) < len(msg["tool_calls"]):
            cleaned = dict(msg)
            cleaned["tool_calls"] = complete
            result.append(cleaned)
        else:
            result.append(msg)

    return to_summarize, result


_COMPACT_SUMMARY_MARKER = "Summary:\n"
_COMPACT_TAIL_MARKER = "\n\nRecent messages"


def extract_compact_summary(messages: list[dict], *, max_chars: int = 4000) -> str:
    """Extract summary body from a compact boundary user message."""
    for msg in messages:
        if not msg.get("is_compact_summary"):
            continue
        content = msg.get("content") or ""
        if _COMPACT_SUMMARY_MARKER not in content:
            continue
        body = content.split(_COMPACT_SUMMARY_MARKER, 1)[-1].split(
            _COMPACT_TAIL_MARKER, 1
        )[0].strip()
        if not body:
            continue
        return body[:max_chars]
    return ""


def _rebuild_messages(
    system_msg: dict,
    summary_text: str,
    tail: list[dict],
) -> list[dict]:
    boundary = (
        "This session is being continued from a previous conversation that ran out of context.\n"
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"{_COMPACT_SUMMARY_MARKER}{summary_text}\n\n"
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

    to_summarize, tail = prepare_tail_for_rebuild(non_system, keep)
    if not tail or not to_summarize:
        return messages, False

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
        if not summary or not _is_valid_summary(summary):
            return messages, False
        return _rebuild_messages(system_msg, summary, tail), True
    except Exception:
        return messages, False
