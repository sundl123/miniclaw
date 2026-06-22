"""Path sandbox for ~/.miniclaw/memory/."""
from __future__ import annotations

import os

from miniclaw.dirs import get_user_data_dir
from miniclaw.memory.config import MEMORY_MD_FILENAME

_MEMORY_SUBDIR = "memory"


def get_memory_dir() -> str:
    """Return ~/.miniclaw/memory/, creating it if needed."""
    path = os.path.join(get_user_data_dir(), _MEMORY_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_memory_md_path() -> str:
    return os.path.join(get_memory_dir(), MEMORY_MD_FILENAME)


def normalize_memory_rel_path(rel_path: str) -> str:
    """Normalize a relative path under the memory directory."""
    raw = (rel_path or "").strip().replace("\\", "/")
    if not raw:
        raise PermissionError("path 不能为空")
    if os.path.isabs(raw):
        raise PermissionError(f"memory path 必须为相对路径: {rel_path!r}")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PermissionError(f"memory path 不允许 ..: {rel_path!r}")
        parts.append(part)
    if not parts:
        raise PermissionError("path 不能为空")
    return "/".join(parts)


def resolve_memory_path(rel_path: str) -> str:
    """Resolve rel_path to an absolute path under ~/.miniclaw/memory/."""
    norm_rel = normalize_memory_rel_path(rel_path)
    memory_dir = os.path.normpath(get_memory_dir())
    abs_path = os.path.normpath(os.path.join(memory_dir, norm_rel.replace("/", os.sep)))
    if abs_path != memory_dir and not abs_path.startswith(memory_dir + os.sep):
        raise PermissionError(f"路径不允许超出 memory 目录: {rel_path}")
    return abs_path


def is_memory_md_path(rel_path: str) -> bool:
    try:
        return normalize_memory_rel_path(rel_path) == MEMORY_MD_FILENAME
    except PermissionError:
        return False
