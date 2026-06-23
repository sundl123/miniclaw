"""Paths for session records and SQLite state."""
from __future__ import annotations

import os

from miniclaw.dirs import get_user_data_dir

_RECORDS_SUBDIR = "records"
_STATE_DB_FILENAME = "state.db"


def get_records_dir() -> str:
    """Return ~/.miniclaw/records/, creating it if needed."""
    path = os.path.join(get_user_data_dir(), _RECORDS_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_state_db_path() -> str:
    return os.path.join(get_user_data_dir(), _STATE_DB_FILENAME)


def session_jsonl_path(session_id: str, local_date: str) -> str:
    """Build absolute path for a session JSONL file."""
    filename = f"{local_date}_{session_id}.jsonl"
    return os.path.join(get_records_dir(), filename)
