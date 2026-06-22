"""Memory system configuration."""
from __future__ import annotations

from dataclasses import dataclass

MEMORY_MD_FILENAME = "MEMORY.md"

DEFAULT_MEMORY_MD_MAX_BYTES = 25600
DEFAULT_MEMORY_MD_MAX_LINES = 200
DEFAULT_WARN_THRESHOLD_PCT = 80

MEMORY_MD_PLACEHOLDER = """# Memory

<!-- Loaded every session. Keep highest-signal facts here. Details go in other files under ~/.miniclaw/memory/ -->
"""


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = False
    memory_md_max_bytes: int = DEFAULT_MEMORY_MD_MAX_BYTES
    memory_md_max_lines: int = DEFAULT_MEMORY_MD_MAX_LINES
    warn_threshold_pct: int = DEFAULT_WARN_THRESHOLD_PCT
