"""Inline micro-compaction: per-tool input/output policies."""
from __future__ import annotations

import json
from dataclasses import dataclass

from miniclaw.context.config import ContextConfig
from miniclaw.context.tokens import estimate_message_tokens, estimate_text_tokens


@dataclass
class CompactPolicy:
    compact_input_fields: frozenset[str] = frozenset()
    compact_output: bool = False
    truncate_input_fields: frozenset[str] = frozenset()
    truncate_chars: int = 80


TOOL_COMPACT_POLICY: dict[str, CompactPolicy] = {
    "read": CompactPolicy(compact_output=True),
    "write": CompactPolicy(compact_input_fields=frozenset({"content"}), compact_output=False),
    "edit": CompactPolicy(
        compact_input_fields=frozenset(),
        compact_output=False,
        truncate_input_fields=frozenset({"old_string", "new_string"}),
        truncate_chars=80,
    ),
    "glob": CompactPolicy(compact_output=True),
    "grep": CompactPolicy(compact_output=True),
    "bash": CompactPolicy(compact_output=True),
    "enter_plan_mode": CompactPolicy(compact_output=False),
    "exit_plan_mode": CompactPolicy(compact_output=False),
}


def _parse_arguments(args_str: str) -> dict:
    if not args_str:
        return {}
    try:
        return json.loads(args_str) if isinstance(args_str, str) else dict(args_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_result_placeholder(tool_name: str, original_content: str) -> str:
    est = estimate_text_tokens(original_content)
    return f"[compacted] {tool_name} ~{est} tokens — re-invoke {tool_name} if needed"


def _compact_arguments(tool_name: str, args: dict, policy: CompactPolicy) -> dict:
    out = dict(args)
    out["_compacted"] = True

    for field in policy.compact_input_fields:
        if field in out:
            val = out.pop(field)
            if field == "content" and isinstance(val, str):
                out["_content_chars"] = len(val)

    for field in policy.truncate_input_fields:
        if field in out and isinstance(out[field], str):
            val = out[field]
            if len(val) > policy.truncate_chars:
                out[field] = val[: policy.truncate_chars] + "..."
                out["_truncated"] = True

    if tool_name == "write" and "path" in out:
        out.setdefault("_hint", "content on disk; use read to view")

    return out


def _find_assistant_for_tool(messages: list[dict], tool_call_id: str) -> tuple[int, int] | None:
    """Return (assistant_idx, tool_call_index) for a tool message."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "assistant":
            continue
        for j, tc in enumerate(msg.get("tool_calls") or []):
            tid = tc.get("id") or tc.get("tool_use_id")
            if tid == tool_call_id:
                return i, j
    return None


def _assistant_round_indices(messages: list[dict]) -> list[int]:
    """Indices of assistant messages that have tool_calls."""
    return [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]


def _protected_indices(messages: list[dict], cfg: ContextConfig) -> set[int]:
    """Message indices that must not be compacted."""
    protected: set[int] = set()
    mc = cfg.micro_compact

    # Always protect system
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            protected.add(i)

    # Protect recent assistant rounds and their following tool messages
    round_starts = _assistant_round_indices(messages)
    recent_rounds = round_starts[-mc.keep_recent_turns :] if round_starts else []
    for start in recent_rounds:
        for i in range(start, len(messages)):
            protected.add(i)
            if i > start and messages[i].get("role") not in ("tool", "assistant"):
                break

    # Protect last N tool messages by count
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for idx in tool_indices[-mc.keep_recent_tool_results :]:
        protected.add(idx)
        match = _find_assistant_for_tool(messages, messages[idx].get("tool_call_id") or "")
        if match:
            protected.add(match[0])

    return protected


def _compact_reasoning(messages: list[dict], cfg: ContextConfig) -> int:
    """Strip reasoning_details from old assistant messages."""
    mc = cfg.micro_compact
    round_indices = [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant"
    ]
    if len(round_indices) <= mc.compact_reasoning_after_turns:
        return 0

    protected = _protected_indices(messages, cfg)
    count = 0
    stale_assistants = round_indices[: -mc.compact_reasoning_after_turns]
    for i in stale_assistants:
        if i in protected:
            continue
        msg = messages[i]
        if msg.get("reasoning_details"):
            msg["reasoning_details"] = [{"type": "reasoning.text", "text": "[reasoning compacted]"}]
            count += 1
    return count


def micro_compact(messages: list[dict], cfg: ContextConfig) -> int:
    """Apply inline micro-compaction. Returns number of items compacted."""
    if not cfg.enabled or not cfg.micro_compact.enabled:
        return 0

    protected = _protected_indices(messages, cfg)
    max_chars = cfg.micro_compact.placeholder_max_chars
    compacted = 0

    compacted += _compact_reasoning(messages, cfg)

    for i, msg in enumerate(messages):
        if i in protected:
            continue

        if msg.get("role") == "tool":
            if msg.get("_compacted"):
                continue
            content = msg.get("content") or ""
            if len(content) <= max_chars:
                continue

            tid = msg.get("tool_call_id") or ""
            match = _find_assistant_for_tool(messages, tid)
            if not match:
                continue
            a_idx, tc_idx = match
            assistant = messages[a_idx]
            tc = (assistant.get("tool_calls") or [])[tc_idx]
            tool_name = (tc.get("function") or {}).get("name", "")
            policy = TOOL_COMPACT_POLICY.get(tool_name, CompactPolicy(compact_output=True))

            if not policy.compact_output:
                continue

            msg["content"] = _format_result_placeholder(tool_name, content)
            msg["_compacted"] = True
            compacted += 1

    # Compact assistant tool_calls arguments for stale assistants
    for i, msg in enumerate(messages):
        if i in protected or msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_name = fn.get("name", "")
            policy = TOOL_COMPACT_POLICY.get(tool_name)
            if not policy:
                continue
            args = _parse_arguments(fn.get("arguments", "{}"))
            if args.get("_compacted"):
                continue
            if not policy.compact_input_fields and not policy.truncate_input_fields:
                continue
            est = estimate_text_tokens(fn.get("arguments", ""))
            if est * 4 <= max_chars and not policy.compact_input_fields:
                continue
            new_args = _compact_arguments(tool_name, args, policy)
            fn["arguments"] = json.dumps(new_args, ensure_ascii=False)
            compacted += 1

    return compacted


def count_compacted(messages: list[dict]) -> int:
    n = sum(1 for m in messages if m.get("role") == "tool" and m.get("_compacted"))
    n += sum(
        1
        for m in messages
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
        if "_compacted" in _parse_arguments((tc.get("function") or {}).get("arguments", "{}"))
    )
    return n
