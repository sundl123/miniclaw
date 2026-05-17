"""Tool output limit configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReadToolConfig:
    max_file_bytes: int = 262144  # 256 KB
    max_output_tokens: int = 8000


@dataclass
class ToolsConfig:
    read: ReadToolConfig
    max_tool_result_chars: int = 100_000
    max_glob_files: int = 500
