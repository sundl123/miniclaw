"""Sub-Agent configuration."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_TURNS = 30


@dataclass(frozen=True)
class SubagentConfig:
    enabled: bool = False
    max_turns: int = DEFAULT_MAX_TURNS
