"""Orchestrate micro-compaction and summarization."""
from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from openai import OpenAI

from miniclaw.context.config import ContextConfig, get_thresholds
from miniclaw.context.micro_compact import micro_compact, count_compacted
from miniclaw.context.summarize import compact_boundary_content, summarize_conversation
from miniclaw.context.tokens import (
    estimate_messages_tokens,
    get_estimated_tokens,
    update_usage_from_response,
)

CompactProgressCallback = Callable[[str], None]


def init_ctx_mgmt(context: Optional[dict]) -> dict:
    """Ensure context['_ctx_mgmt'] exists and return it."""
    if context is None:
        context = {}
    mgmt = context.setdefault("_ctx_mgmt", {})
    mgmt.setdefault("last_prompt_tokens", None)
    mgmt.setdefault("compacting", False)
    mgmt.setdefault("consecutive_summarize_failures", 0)
    mgmt.setdefault("auto_summarize_disabled", False)
    mgmt.setdefault("last_compact_count", 0)
    return mgmt


def get_ctx_mgmt(context: Optional[dict]) -> dict:
    if context is None:
        return init_ctx_mgmt({})
    return init_ctx_mgmt(context)


def _notify_progress(
    on_progress: CompactProgressCallback | None,
    phase: str,
) -> None:
    if on_progress is not None:
        on_progress(phase)


def _record_context_compact(
    context: Optional[dict],
    *,
    messages_before: int,
    new_messages: list[dict],
) -> None:
    writer = (context or {}).get("records_writer")
    if writer is None:
        return
    writer.append_meta(
        "context_compact",
        content=compact_boundary_content(new_messages),
        messages_before=messages_before,
        messages_after=len(new_messages),
    )


def _finalize_summarize_success(
    ctx: dict,
    on_progress: CompactProgressCallback | None,
    context: Optional[dict],
    *,
    messages_before: int,
    new_messages: list[dict],
) -> None:
    ctx["consecutive_summarize_failures"] = 0
    ctx["last_prompt_tokens"] = None
    _notify_progress(on_progress, "done")
    _record_context_compact(
        context,
        messages_before=messages_before,
        new_messages=new_messages,
    )


def _try_auto_summarize(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
    *,
    timeout: int = 300,
    on_progress: CompactProgressCallback | None = None,
) -> list[dict]:
    """Run full summarization when over threshold. Returns updated messages."""
    ctx = get_ctx_mgmt(context)
    if ctx.get("compacting"):
        return messages

    if not cfg.auto_summarize.enabled or ctx.get("auto_summarize_disabled"):
        return messages

    thresholds = get_thresholds(cfg)
    tokens = get_estimated_tokens(messages, ctx)
    if tokens < thresholds.auto_summarize_threshold:
        return messages
    if len(messages) < cfg.auto_summarize.min_messages_before_summarize:
        return messages

    ctx["compacting"] = True
    _notify_progress(on_progress, "start")
    messages_before = len(messages)
    try:
        new_messages, ok = summarize_conversation(
            client, model, messages, cfg, timeout=timeout,
        )
        if ok:
            _finalize_summarize_success(
                ctx, on_progress, context,
                messages_before=messages_before,
                new_messages=new_messages,
            )
            return new_messages
        ctx["consecutive_summarize_failures"] = ctx.get("consecutive_summarize_failures", 0) + 1
        if ctx["consecutive_summarize_failures"] >= cfg.auto_summarize.max_consecutive_failures:
            ctx["auto_summarize_disabled"] = True
        _notify_progress(on_progress, "failed")
        return messages
    finally:
        ctx["compacting"] = False


def manage_messages(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
    *,
    timeout: int = 300,
    on_compact_progress: CompactProgressCallback | None = None,
) -> list[dict]:
    """Before each chat_stream: micro-compact, then auto-summarize if over threshold."""
    if not cfg.enabled:
        return messages

    ctx = get_ctx_mgmt(context)
    if ctx.get("compacting"):
        return messages

    thresholds = get_thresholds(cfg)
    tokens = get_estimated_tokens(messages, ctx)

    if (
        cfg.micro_compact.enabled
        and tokens >= thresholds.micro_compact_threshold
    ):
        n = micro_compact(messages, cfg)
        ctx["last_compact_count"] = n
        tokens = estimate_messages_tokens(messages)

    messages = _try_auto_summarize(
        client, model, messages, cfg, context,
        timeout=timeout,
        on_progress=on_compact_progress,
    )
    return messages


def manual_compact(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
    *,
    extra_instructions: str = "",
    timeout: int = 300,
    on_compact_progress: CompactProgressCallback | None = None,
) -> tuple[list[dict], bool]:
    """User-triggered /compact."""
    ctx = get_ctx_mgmt(context)
    ctx["compacting"] = True
    _notify_progress(on_compact_progress, "start")
    try:
        new_messages, ok = summarize_conversation(
            client, model, messages, cfg,
            extra_instructions=extra_instructions,
            timeout=timeout,
        )
        if ok:
            _finalize_summarize_success(
                ctx, on_compact_progress, context,
                messages_before=len(messages),
                new_messages=new_messages,
            )
        else:
            _notify_progress(on_compact_progress, "failed")
        return new_messages, ok
    finally:
        ctx["compacting"] = False


def format_context_status(
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
) -> str:
    """Human-readable status for /context command."""
    ctx = get_ctx_mgmt(context)
    thresholds = get_thresholds(cfg)
    tokens = get_estimated_tokens(messages, ctx)
    compacted = count_compacted(messages)
    lines = [
        f"Estimated tokens: {tokens:,}",
        f"Effective window: {thresholds.effective_window:,}",
        f"Micro-compact threshold: {thresholds.micro_compact_threshold:,}",
        f"Auto-summarize threshold: {thresholds.auto_summarize_threshold:,}",
        f"Warning threshold: {thresholds.warning_threshold:,}",
        f"Compacted items: {compacted}",
        f"Compacting: {ctx.get('compacting', False)}",
        f"Auto-summarize disabled: {ctx.get('auto_summarize_disabled', False)}",
        f"Messages: {len(messages)}",
    ]
    if tokens >= thresholds.warning_threshold:
        lines.append("Status: approaching context limit")
    return "\n".join(lines)


def record_usage(context: Optional[dict], usage) -> None:
    """Update ctx mgmt from API usage after chat_stream."""
    ctx = get_ctx_mgmt(context)
    update_usage_from_response(ctx, usage)
