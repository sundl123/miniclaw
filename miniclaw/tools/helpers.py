"""Shared helpers for tool handlers (skill/session allowlists)."""
from __future__ import annotations

import os


def registered_skill_dirs(context: dict | None) -> frozenset[str]:
    registry = (context or {}).get("skill_registry")
    return registry.skill_dirs() if registry else frozenset()


def allowed_read_files(context: dict | None) -> frozenset[str]:
    path = (context or {}).get("records_jsonl_path")
    if not path:
        return frozenset()
    return frozenset({os.path.normpath(path)})
