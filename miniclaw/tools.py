"""工具集：read、write、edit、glob、grep、bash，均限制在 workspace 内。"""
from __future__ import annotations

import glob as glob_module
import json
import os
import subprocess

from miniclaw.config import (
    is_allowed_read_path,
    resolve_glob_pattern,
    resolve_path,
    resolve_read_path,
)
from miniclaw.context.tokens import estimate_text_tokens
from miniclaw.plan_mode import (
    PLAN_MODE_HANDLERS,
    check_plan_mode,
    get_plan_tool_schemas,
)
from miniclaw.read_file import FileTooLargeError, read_file_lines
from miniclaw.settings import get_tools_config
from miniclaw.skills import normalize_skill_name
from miniclaw.tool_output import cap_tool_result, truncate_read_output
from miniclaw.tools_config import ToolsConfig
from miniclaw.ui import print_tool_call


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _registered_skill_dirs(context: dict | None) -> frozenset[str]:
    registry = (context or {}).get("skill_registry")
    return registry.skill_dirs() if registry else frozenset()


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
    skill_dirs = _registered_skill_dirs(context)
    try:
        abs_path = resolve_read_path(
            path, workspace_root, registered_skill_dirs=skill_dirs,
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

    content = result.content
    est = estimate_text_tokens(content)
    if est > cfg.max_output_tokens:
        if limit is None:
            return json.dumps(
                {
                    "error": (
                        f"Read output (~{est:,} tokens) exceeds maximum allowed "
                        f"({cfg.max_output_tokens:,} tokens). Use offset and limit "
                        f"(0-based) to read specific portions of the file."
                    ),
                },
                ensure_ascii=False,
            )
        content = truncate_read_output(content, cfg.max_output_tokens)

    return content


def handle_write(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """将 content 写入文件（覆盖），自动创建父目录。"""
    path = args.get("path") or ""
    content = args.get("content") or ""
    if not path:
        return json.dumps({"error": "write 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote to {abs_path}"


def handle_edit(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """精确字符串替换：old_string 必须在文件中恰好出现一次，替换为 new_string。"""
    path = args.get("path") or ""
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not path:
        return json.dumps({"error": "edit 需要 path 参数"}, ensure_ascii=False)
    if not old_string:
        return json.dumps({"error": "edit 需要 old_string 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    if not os.path.isfile(abs_path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    count = content.count(old_string)
    if count == 0:
        return json.dumps({"error": "old_string 未在文件中找到"}, ensure_ascii=False)
    if count > 1:
        return json.dumps({"error": f"old_string 在文件中出现了 {count} 次，需恰好 1 次"}, ensure_ascii=False)
    new_content = content.replace(old_string, new_string, 1)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"Successfully edited {abs_path}"


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
    skill_dirs = _registered_skill_dirs(context)
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
    skill_dirs = _registered_skill_dirs(context)
    try:
        abs_search = resolve_read_path(
            search_path, workspace_root, registered_skill_dirs=skill_dirs,
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


def handle_bash(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """在工作区内执行 bash 命令。"""
    cmd = args.get("command") or ""
    if not cmd:
        return json.dumps({"error": "bash 需要 command 参数"}, ensure_ascii=False)
    r = subprocess.run(
        ["bash", "-c", cmd],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        return f"exit code: {r.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    return out or "(无输出)"


def handle_skill(args: dict, workspace_root: str, context: dict | None = None) -> str:
    """加载 skill：读取 SKILL.md 正文并注入 Base directory 前缀。"""
    raw_name = args.get("skill") or ""
    name = normalize_skill_name(raw_name)
    if not name:
        return json.dumps({"error": "Skill 需要 skill 参数"}, ensure_ascii=False)

    registry = (context or {}).get("skill_registry")
    if registry is None:
        return json.dumps({"error": "skill 注册表未初始化"}, ensure_ascii=False)

    entry = registry.lookup(name)
    if entry is None:
        return json.dumps({"error": f"未找到 skill: {name}"}, ensure_ascii=False)

    try:
        body = registry.load_skill_body(name)
    except OSError as e:
        return json.dumps({"error": f"读取 skill 失败: {e}"}, ensure_ascii=False)

    return body


# ---------------------------------------------------------------------------
# 工具注册表与分发
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "glob": handle_glob,
    "grep": handle_grep,
    "bash": handle_bash,
    "Skill": handle_skill,
}


def _print_tool_invocation(name: str, args: dict) -> None:
    """向 stdout 打印工具调用摘要，便于 REPL 用户看到进度。"""
    detail = ""
    if name in ("read", "write", "edit"):
        p = (args.get("path") or "").strip()
        if p:
            detail = f"path={p}"
    elif name == "bash":
        cmd = (args.get("command") or "").strip()
        if cmd:
            detail = f"command={cmd[:100]}{'…' if len(cmd) > 100 else ''}"
    elif name == "glob":
        detail = f"pattern={args.get('pattern', '')}"
    elif name == "grep":
        detail = f"pattern={args.get('pattern', '')} path={args.get('path', '.')}"
    elif name == "Skill":
        detail = f"skill={args.get('skill', '')}"
    elif name in PLAN_MODE_HANDLERS:
        pass
    print_tool_call(name, detail)


def execute_tool(
    name: str,
    args: dict,
    workspace_root: str = None,
    context: dict = None,
    tools_config: ToolsConfig | None = None,
) -> str:
    """按工具名分发执行，返回结果字符串。

    context 承载 plan mode 状态（mode, plan_dir 等），由 REPL 层创建并透传。
    """
    root = workspace_root or os.getcwd()
    ctx = context or {}
    cfg = tools_config or get_tools_config(root)

    blocked = check_plan_mode(name, args, ctx)
    if blocked:
        _print_tool_invocation(name, args)
        return blocked

    plan_handler = PLAN_MODE_HANDLERS.get(name)
    if plan_handler:
        _print_tool_invocation(name, args)
        try:
            result = plan_handler(args, root, ctx)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return cap_tool_result(result, cfg.max_tool_result_chars, tool_name=name)

    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    _print_tool_invocation(name, args)
    try:
        if name in ("read", "grep", "glob"):
            result = handler(args, root, tools_cfg=cfg, context=ctx)
        elif name == "Skill":
            result = handler(args, root, context=ctx)
        else:
            result = handler(args, root, tools_cfg=cfg)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"{name} 执行超时"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    return cap_tool_result(result, cfg.max_tool_result_chars, tool_name=name)


# ---------------------------------------------------------------------------
# Tool Schema
# ---------------------------------------------------------------------------

def get_tool_schemas() -> list[dict]:
    """返回所有工具的 OpenAI function-calling 风格定义（含 plan mode 工具）。"""
    return [
        {"type": "function", "function": {
            "name": "read",
            "description": (
                "Read a file and return its content with line numbers (0-based offset). "
                "For large files you MUST use limit; without limit, files over 256KB are rejected. "
                "If output is still too large with limit, results may be truncated."
            ),
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to read (must be absolute, not relative)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Start line, 0-based (default 0)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read (required for large files)",
                },
            }, "required": ["path"]},
        }},
        {"type": "function", "function": {
            "name": "write",
            "description": "Write content to a file (overwrites if exists, creates parent directories as needed).",
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to write (must be absolute, not relative)",
                },
                "content": {"type": "string", "description": "File content to write"},
            }, "required": ["path", "content"]},
        }},
        {"type": "function", "function": {
            "name": "edit",
            "description": "Replace a unique string in a file. old_string must appear exactly once.",
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to modify (must be absolute, not relative)",
                },
                "old_string": {"type": "string", "description": "The exact string to find (must appear once)"},
                "new_string": {"type": "string", "description": "The replacement string"},
            }, "required": ["path", "old_string", "new_string"]},
        }},
        {"type": "function", "function": {
            "name": "glob",
            "description": (
                "Find files matching a glob pattern within the workspace or a registered "
                "skill directory. Use absolute patterns (e.g. /path/to/ws/**/*.py). "
                "Use ** for recursive matching. Results are capped (newest first)."
            ),
            "parameters": {"type": "object", "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Absolute glob pattern (e.g. '/path/to/ws/**/*.py')",
                },
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "grep",
            "description": (
                "Search file contents for a pattern (regex) within the workspace or a "
                "registered skill directory (absolute path)."
            ),
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {
                    "type": "string",
                    "description": "Absolute path to search in (default: workspace root as absolute path)",
                },
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "bash",
            "description": "Run a shell command in the workspace directory.",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
            }, "required": ["command"]},
        }},
        {"type": "function", "function": {
            "name": "Skill",
            "description": (
                "Load and activate a skill by name. Call this BEFORE executing "
                "task-specific workflows when a skill matches the user's request. "
                "Available skills are listed in the system prompt."
            ),
            "parameters": {"type": "object", "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name (without leading slash, e.g. code-review)",
                },
            }, "required": ["skill"]},
        }},
    ] + get_plan_tool_schemas()
