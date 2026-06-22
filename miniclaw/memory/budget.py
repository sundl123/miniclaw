"""MEMORY.md byte/line budget measurement, preflight, and truncation."""
from __future__ import annotations

from dataclasses import dataclass

from miniclaw.memory.config import MemoryConfig


@dataclass(frozen=True)
class ContentMeasure:
    used_bytes: int
    used_lines: int

    @classmethod
    def from_text(cls, content: str) -> ContentMeasure:
        if not content:
            return cls(used_bytes=0, used_lines=0)
        used_bytes = len(content.encode("utf-8"))
        if content.endswith("\n"):
            used_lines = content.count("\n")
        else:
            used_lines = content.count("\n") + 1
        return cls(used_bytes=used_bytes, used_lines=used_lines)


@dataclass(frozen=True)
class MemoryMdUsage:
    """MEMORY.md capacity snapshot (0–100 integers for *_percent fields)."""

    used_bytes: int
    limit_bytes: int
    used_lines: int
    limit_lines: int
    bytes_percent: int
    lines_percent: int
    display: str

    def to_dict(self) -> dict:
        return {
            "used_bytes": self.used_bytes,
            "limit_bytes": self.limit_bytes,
            "used_lines": self.used_lines,
            "limit_lines": self.limit_lines,
            "bytes_percent": self.bytes_percent,
            "lines_percent": self.lines_percent,
            "display": self.display,
        }


@dataclass(frozen=True)
class BudgetCheckResult:
    ok: bool
    measure: ContentMeasure
    violations: tuple[str, ...]


@dataclass(frozen=True)
class TruncationMeta:
    truncated: bool
    total_bytes: int
    total_lines: int
    shown_bytes: int
    shown_lines: int


def _pct(used: int, limit: int) -> int:
    if limit <= 0:
        return 0
    return min(100, int((used / limit) * 100))


def _format_display(measure: ContentMeasure, config: MemoryConfig) -> str:
    pct_b = _pct(measure.used_bytes, config.memory_md_max_bytes)
    kb_used = measure.used_bytes / 1024
    kb_limit = config.memory_md_max_bytes / 1024
    return (
        f"{pct_b}% — {kb_used:.1f}/{kb_limit:.1f} KB, "
        f"{measure.used_lines}/{config.memory_md_max_lines} lines"
    )


def build_usage(measure: ContentMeasure, config: MemoryConfig) -> MemoryMdUsage:
    return MemoryMdUsage(
        used_bytes=measure.used_bytes,
        limit_bytes=config.memory_md_max_bytes,
        used_lines=measure.used_lines,
        limit_lines=config.memory_md_max_lines,
        bytes_percent=_pct(measure.used_bytes, config.memory_md_max_bytes),
        lines_percent=_pct(measure.used_lines, config.memory_md_max_lines),
        display=_format_display(measure, config),
    )


def check_budget(content: str, config: MemoryConfig) -> BudgetCheckResult:
    measure = ContentMeasure.from_text(content)
    violations: list[str] = []
    if measure.used_bytes > config.memory_md_max_bytes:
        violations.append("bytes")
    if measure.used_lines > config.memory_md_max_lines:
        violations.append("lines")
    return BudgetCheckResult(
        ok=not violations,
        measure=measure,
        violations=tuple(violations),
    )


def truncate_for_prompt(content: str, config: MemoryConfig) -> tuple[str, TruncationMeta]:
    """Truncate content to fit MEMORY.md limits for system prompt injection."""
    full_measure = ContentMeasure.from_text(content)
    check = check_budget(content, config)
    if check.ok:
        return content, TruncationMeta(
            truncated=False,
            total_bytes=full_measure.used_bytes,
            total_lines=full_measure.used_lines,
            shown_bytes=full_measure.used_bytes,
            shown_lines=full_measure.used_lines,
        )

    if not content:
        return "", TruncationMeta(
            truncated=False,
            total_bytes=0,
            total_lines=0,
            shown_bytes=0,
            shown_lines=0,
        )

    lines = content.splitlines(keepends=True)
    if not lines and content:
        lines = [content]

    selected: list[str] = []
    used_bytes = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8"))
        next_lines = len(selected) + 1
        if next_lines > config.memory_md_max_lines:
            break
        if used_bytes + line_bytes > config.memory_md_max_bytes:
            break
        selected.append(line)
        used_bytes += line_bytes

    if not selected and lines:
        # Single line (or first line) exceeds byte budget — take a byte prefix.
        first = lines[0]
        encoded = first.encode("utf-8")
        budget = config.memory_md_max_bytes
        if len(encoded) > budget:
            prefix = encoded[:budget].decode("utf-8", errors="ignore")
            selected = [prefix]
        else:
            selected = [first]

    truncated_text = "".join(selected)
    shown = ContentMeasure.from_text(truncated_text)
    return truncated_text, TruncationMeta(
        truncated=True,
        total_bytes=full_measure.used_bytes,
        total_lines=full_measure.used_lines,
        shown_bytes=shown.used_bytes,
        shown_lines=shown.used_lines,
    )


def budget_error_message(
    would_be: ContentMeasure,
    config: MemoryConfig,
    violations: tuple[str, ...],
) -> str:
    parts: list[str] = []
    if "bytes" in violations:
        parts.append(
            f"{would_be.used_bytes:,} bytes > {config.memory_md_max_bytes:,}"
        )
    if "lines" in violations:
        parts.append(
            f"{would_be.used_lines} lines > {config.memory_md_max_lines}"
        )
    detail = "; ".join(parts)
    return (
        f"MEMORY.md would exceed limits ({detail}). "
        "Shorten content, remove stale items, or move detail to another file "
        "under ~/.miniclaw/memory/ and keep a short summary or link in MEMORY.md."
    )


BUDGET_HINTS = (
    "MEMORY.md is loaded every session (frozen in system prompt) — keep highest-signal facts only.",
    "Move long notes to a topic file (e.g. notes/foo.md); no size limit on topic files.",
    "Leave a one-line summary or relative link in MEMORY.md when demoting detail.",
    "Use edit to remove stale sections; deleting MEMORY.md is not allowed.",
)


def usage_warning(measure: ContentMeasure, config: MemoryConfig) -> str | None:
    pct_b = _pct(measure.used_bytes, config.memory_md_max_bytes)
    pct_l = _pct(measure.used_lines, config.memory_md_max_lines)
    peak = max(pct_b, pct_l)
    if peak >= config.warn_threshold_pct:
        return (
            f"MEMORY.md at {peak}% capacity ({build_usage(measure, config).display}). "
            "Consider consolidating or moving detail to topic files."
        )
    return None
