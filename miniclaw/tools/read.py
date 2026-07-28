"""read tool handler."""
from __future__ import annotations

import json
import os

from miniclaw.config import resolve_read_path
from miniclaw.read_file import FileTooLargeError, read_file_lines
from miniclaw.settings import get_tools_config
from miniclaw.tool_output import enforce_read_output_limits
from miniclaw.tools.config import ToolsConfig
from miniclaw.tools.helpers import allowed_read_files, registered_skill_dirs


def handle_read(
    args: dict,
    workspace_root: str,
    tools_cfg: ToolsConfig | None = None,
    *,
    context: dict | None = None,
) -> str:
    """读取文件，返回带行号的内容。支持 offset / limit 做部分读取。"""
    path = args.get("path") or ""
    if not path:
        return json.dumps({"error": "read 需要 path 参数"}, ensure_ascii=False)

    cfg = (tools_cfg or get_tools_config(workspace_root)).read
    skill_dirs = registered_skill_dirs(context)
    allowed_files = allowed_read_files(context)
    try:
        abs_path = resolve_read_path(
            path,
            workspace_root,
            registered_skill_dirs=skill_dirs,
            allowed_read_files=allowed_files,
        )
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    if not os.path.isfile(abs_path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

    offset = args.get("offset")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0

    limit = args.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
            if limit <= 0:
                limit = None
        except (TypeError, ValueError):
            limit = None

    try:
        result = read_file_lines(
            abs_path,
            offset=offset,
            limit=limit,
            max_file_bytes=cfg.max_file_bytes if limit is None else None,
        )
    except FileTooLargeError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    limited = enforce_read_output_limits(
        result.content,
        limit=limit,
        max_output_tokens=cfg.max_output_tokens,
    )
    if limited.error:
        return json.dumps({"error": limited.error}, ensure_ascii=False)
    return limited.content
