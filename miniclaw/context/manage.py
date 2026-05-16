"""Orchestrate micro-compaction and summarization."""
from __future__ import annotations

from typing import Optional

from openai import OpenAI

from miniclaw.context.config import ContextConfig, get_thresholds
from miniclaw.context.micro_compact import micro_compact, count_compacted
from miniclaw.context.summarize import summarize_conversation
from miniclaw.context.tokens import (
    estimate_messages_tokens,
    get_estimated_tokens,
    update_usage_from_response,
)


def init_ctx_mgmt(context: Optional[dict]) -> dict:
    """Ensure context['_ctx_mgmt'] exists and return it."""
    if context is None:
        context = {}
    mgmt = context.setdefault("_ctx_mgmt", {})
    mgmt.setdefault("last_prompt_tokens", None)
    mgmt.setdefault("pending_summarize", False)
    mgmt.setdefault("compacting", False)
    mgmt.setdefault("consecutive_summarize_failures", 0)
    mgmt.setdefault("auto_summarize_disabled", False)
    mgmt.setdefault("last_compact_count", 0)
    return mgmt


def get_ctx_mgmt(context: Optional[dict]) -> dict:
    if context is None:
        return init_ctx_mgmt({})
    return init_ctx_mgmt(context)


def manage_messages(
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
) -> list[dict]:
    """Run before each chat_stream: micro-compact + set pending_summarize."""
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

    if (
        cfg.auto_summarize.enabled
        and not ctx.get("auto_summarize_disabled")
        and tokens >= thresholds.auto_summarize_threshold
        and len(messages) >= cfg.auto_summarize.min_messages_before_summarize
    ):
        ctx["pending_summarize"] = True

    return messages


def manage_messages_end_of_turn(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
    *,
    timeout: int = 300,
) -> list[dict]:
    """Run at end of run_turn_with_tools: execute pending auto-summarize."""
    if not cfg.enabled:
        return messages

    ctx = get_ctx_mgmt(context)
    if ctx.get("compacting") or not ctx.get("pending_summarize"):
        ctx["pending_summarize"] = False
        return messages

    if not cfg.auto_summarize.enabled or ctx.get("auto_summarize_disabled"):
        ctx["pending_summarize"] = False
        return messages

    ctx["compacting"] = True
    ctx["pending_summarize"] = False
    try:
        new_messages, ok = summarize_conversation(
            client, model, messages, cfg, timeout=timeout,
        )
        if ok:
            ctx["consecutive_summarize_failures"] = 0
            ctx["last_prompt_tokens"] = None
            return new_messages
        ctx["consecutive_summarize_failures"] = ctx.get("consecutive_summarize_failures", 0) + 1
        if ctx["consecutive_summarize_failures"] >= cfg.auto_summarize.max_consecutive_failures:
            ctx["auto_summarize_disabled"] = True
        return messages
    finally:
        ctx["compacting"] = False


def manual_compact(
    client: OpenAI,
    model: str,
    messages: list[dict],
    cfg: ContextConfig,
    context: Optional[dict],
    *,
    extra_instructions: str = "",
    timeout: int = 300,
) -> tuple[list[dict], bool]:
    """User-triggered /compact."""
    ctx = get_ctx_mgmt(context)
    ctx["compacting"] = True
    try:
        new_messages, ok = summarize_conversation(
            client, model, messages, cfg,
            extra_instructions=extra_instructions,
            timeout=timeout,
        )
        if ok:
            ctx["consecutive_summarize_failures"] = 0
            ctx["last_prompt_tokens"] = None
            ctx["pending_summarize"] = False
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
        f"Pending summarize: {ctx.get('pending_summarize', False)}",
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
