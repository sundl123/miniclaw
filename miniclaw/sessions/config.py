"""Sessions / records configuration."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RECORDS_MAX_EVENT_BYTES = 100_000
DEFAULT_SEARCH_DEFAULT_LIMIT = 3
DEFAULT_SEARCH_WINDOW = 5
DEFAULT_BROWSE_LIMIT = 10


@dataclass(frozen=True)
class SessionsConfig:
    enabled: bool = False
    records_max_event_bytes: int = DEFAULT_RECORDS_MAX_EVENT_BYTES
    search_default_limit: int = DEFAULT_SEARCH_DEFAULT_LIMIT
    search_window: int = DEFAULT_SEARCH_WINDOW
    browse_limit: int = DEFAULT_BROWSE_LIMIT
