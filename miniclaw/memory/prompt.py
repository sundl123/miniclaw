"""System prompt block formatting for frozen MEMORY.md snapshot."""
from __future__ import annotations

from miniclaw.memory.budget import ContentMeasure, TruncationMeta, build_usage
from miniclaw.memory.config import MemoryConfig


def format_memory_system_block(
    snapshot: str,
    meta: TruncationMeta,
    config: MemoryConfig,
) -> str | None:
    """Render the frozen auto-memory block for system prompt injection."""
    if not snapshot or not snapshot.strip():
        return None

    measure = ContentMeasure.from_text(snapshot)
    usage = build_usage(measure, config)
    separator = "═" * 46
    header = f"AUTO MEMORY [{usage.display}]"
    lines = [separator, header, separator, snapshot.rstrip()]

    if meta.truncated:
        lines.append("")
        lines.append(
            "[memory truncated: "
            f"{meta.total_bytes:,} bytes / {meta.total_lines} lines on disk; "
            f"showing {meta.shown_bytes:,} bytes / {meta.shown_lines} lines. "
            "Use memory(action=read, path=MEMORY.md) for full file.]"
        )

    lines.append("")
    lines.append(
        "Memory directory: ~/.miniclaw/memory/ — use the memory tool to read/write topic files."
    )
    return "\n".join(lines)
