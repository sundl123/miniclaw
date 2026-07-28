"""glob / grep tool handlers."""
from __future__ import annotations

import glob as glob_module
import json
import os
import subprocess

from miniclaw.config import (
    is_allowed_read_path,
    resolve_glob_pattern,
    resolve_read_path,
)
from miniclaw.settings import get_tools_config
from miniclaw.tools.config import ToolsConfig
from miniclaw.tools.helpers import allowed_read_files, registered_skill_dirs


def handle_glob(
    args: dict,
    workspace_root: str,
    tools_cfg: ToolsConfig | None = None,
    *,
    context: dict | None = None,
) -> str:
    """在工作区或已注册 skill 目录内按 glob 模式查找文件，按修改时间降序返回。"""
    pattern = args.get("pattern") or ""
    if not pattern:
        return json.dumps({"error": "glob 需要 pattern 参数"}, ensure_ascii=False)

    cfg = tools_cfg or get_tools_config(workspace_root)
    skill_dirs = registered_skill_dirs(context)
    workspace_root = os.path.normpath(workspace_root)
    try:
        full_pattern, result_base = resolve_glob_pattern(
            pattern, workspace_root, registered_skill_dirs=skill_dirs,
        )
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    files = glob_module.glob(full_pattern, recursive=True)
    files = [
        f for f in files
        if is_allowed_read_path(
            os.path.normpath(f), workspace_root, registered_skill_dirs=skill_dirs,
        )
    ]
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    if result_base == workspace_root:
        rel_files = [os.path.relpath(f, workspace_root) for f in files]
    else:
        rel_files = [os.path.normpath(f) for f in files]

    if not rel_files:
        return "No files found"

    max_files = cfg.max_glob_files
    if len(rel_files) <= max_files:
        return "\n".join(rel_files)

    shown = rel_files[:max_files]
    more = len(rel_files) - max_files
    return "\n".join(shown) + f"\n… and {more} more files (truncated)"


def handle_grep(
    args: dict,
    workspace_root: str,
    tools_cfg: ToolsConfig | None = None,
    *,
    context: dict | None = None,
) -> str:
    """在工作区或已注册 skill 目录内用 grep 搜索文件内容。"""
    pattern = args.get("pattern") or ""
    if not pattern:
        return json.dumps({"error": "grep 需要 pattern 参数"}, ensure_ascii=False)
    search_path = args.get("path") or workspace_root
    skill_dirs = registered_skill_dirs(context)
    allowed_files = allowed_read_files(context)
    try:
        abs_search = resolve_read_path(
            search_path,
            workspace_root,
            registered_skill_dirs=skill_dirs,
            allowed_read_files=allowed_files,
        )
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    try:
        r = subprocess.run(
            ["grep", "-rn", "--", pattern, abs_search],
            capture_output=True, text=True, timeout=30, cwd=workspace_root,
        )
        output = (r.stdout or "").strip()
        return output if output else "No matches found"
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "grep 执行超时（30s）"}, ensure_ascii=False)
