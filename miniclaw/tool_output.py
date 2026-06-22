"""Shared helpers for capping tool output size."""
from __future__ import annotations

from dataclasses import dataclass

from miniclaw.context.tokens import estimate_text_tokens


@dataclass(frozen=True)
class ReadOutputLimitResult:
    content: str
    error: str | None = None
    truncated: bool = False


def format_file_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _is_short_json_error(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith('{"error"') and len(text) < 512


def cap_tool_result(text: str, max_chars: int, *, tool_name: str) -> str:
    """Truncate oversized tool results with a footer hint."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if _is_short_json_error(text):
        return text

    footer = (
        f"\n\n[truncated] {tool_name} output was {len(text):,} chars; "
        f"showing first {max_chars:,}. Use a more specific command, pattern, "
        f"or read with offset/limit."
    )
    keep = max(0, max_chars - len(footer))
    return text[:keep] + footer


def truncate_read_output(content: str, max_tokens: int) -> str:
    """Truncate read output when limit was set but content still exceeds token cap."""
    est = estimate_text_tokens(content)
    if est <= max_tokens:
        return content

    max_chars = max(1, max_tokens * 4)
    footer = (
        f"\n\n[truncated] read output was ~{est:,} tokens; "
        f"showing ~{max_tokens:,} tokens. Use offset/limit to read the next portion."
    )
    keep = max(0, max_chars - len(footer))
    return content[:keep] + footer


def enforce_read_output_limits(
    content: str,
    *,
    limit: int | None,
    max_output_tokens: int,
) -> ReadOutputLimitResult:
    """Apply read output token limits: error without limit, truncate when limit is set."""
    est = estimate_text_tokens(content)
    if est <= max_output_tokens:
        return ReadOutputLimitResult(content=content)

    if limit is None:
        return ReadOutputLimitResult(
            content="",
            error=(
                f"Read output (~{est:,} tokens) exceeds maximum allowed "
                f"({max_output_tokens:,} tokens). Use offset and limit "
                f"(0-based) to read specific portions of the file."
            ),
        )

    truncated = truncate_read_output(content, max_output_tokens)
    return ReadOutputLimitResult(content=truncated, truncated=True)
