"""Context management configuration and threshold calculation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MicroCompactConfig:
    enabled: bool = True
    keep_recent_tool_results: int = 3
    keep_recent_turns: int = 2
    compact_reasoning_after_turns: int = 1
    placeholder_max_chars: int = 400
    micro_compact_buffer_tokens: int = 8000


@dataclass
class AutoSummarizeConfig:
    enabled: bool = True
    threshold_buffer_tokens: int = 12000
    min_messages_before_summarize: int = 10
    max_consecutive_failures: int = 3


@dataclass
class SummarizeConfig:
    keep_recent_messages: int = 6
    max_summary_output_tokens: int = 4096


@dataclass
class ContextConfig:
    enabled: bool = True
    context_window_tokens: int = 200_000
    reserve_output_tokens: int = 8000
    micro_compact: MicroCompactConfig = field(default_factory=MicroCompactConfig)
    auto_summarize: AutoSummarizeConfig = field(default_factory=AutoSummarizeConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)


@dataclass
class ContextThresholds:
    effective_window: int
    auto_summarize_threshold: int
    micro_compact_threshold: int
    warning_threshold: int


def get_thresholds(cfg: ContextConfig) -> ContextThresholds:
    """Compute token thresholds from config."""
    effective = cfg.context_window_tokens - cfg.reserve_output_tokens
    auto_sum = effective - cfg.auto_summarize.threshold_buffer_tokens
    micro = auto_sum - cfg.micro_compact.micro_compact_buffer_tokens
    warning = effective - 20_000
    return ContextThresholds(
        effective_window=effective,
        auto_summarize_threshold=auto_sum,
        micro_compact_threshold=micro,
        warning_threshold=warning,
    )
