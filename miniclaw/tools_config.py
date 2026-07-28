"""Backward-compatible re-export of tool config dataclasses.

Prefer ``from miniclaw.tools.config import ReadToolConfig, ToolsConfig``.
"""
from __future__ import annotations

from miniclaw.tools.config import ReadToolConfig, ToolsConfig

__all__ = ["ReadToolConfig", "ToolsConfig"]
