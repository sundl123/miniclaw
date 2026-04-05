"""工具集：read、write、edit、glob、grep、bash，均限制在 workspace 内。"""
import glob as glob_module
import json
import os
import subprocess

from miniclaw.config import WORKSPACE_ROOT, resolve_path
from miniclaw.plan_mode import (
    PLAN_MODE_HANDLERS,
    check_plan_mode,
    get_plan_tool_schemas,
)


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def handle_read(args: dict, workspace_root: str) -> str:
    """读取文件，返回带行号的内容。支持 offset / limit 做部分读取。"""
    path = args.get("path") or ""
    if not path:
        return json.dumps({"error": "read 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    if not os.path.isfile(abs_path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    offset = args.get("offset") or 0
    limit = args.get("limit")
    end = offset + limit if limit else len(lines)
    numbered = [f"{i + 1:6d}|{line}" for i, line in enumerate(lines[offset:end], offset)]
    return "".join(numbered) if numbered else "(空文件)"


def handle_write(args: dict, workspace_root: str) -> str:
    """将 content 写入文件（覆盖），自动创建父目录。"""
    path = args.get("path") or ""
    content = args.get("content") or ""
    if not path:
        return json.dumps({"error": "write 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote to {path}"


def handle_edit(args: dict, workspace_root: str) -> str:
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
    return f"Successfully edited {path}"


def handle_glob(args: dict, workspace_root: str) -> str:
    """在工作区内按 glob 模式查找文件，按修改时间降序返回。"""
    pattern = args.get("pattern") or ""
    if not pattern:
        return json.dumps({"error": "glob 需要 pattern 参数"}, ensure_ascii=False)
    full_pattern = os.path.join(workspace_root, pattern)
    files = glob_module.glob(full_pattern, recursive=True)
    files = [f for f in files if f.startswith(workspace_root)]
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    rel_files = [os.path.relpath(f, workspace_root) for f in files]
    return "\n".join(rel_files) if rel_files else "No files found"


def handle_grep(args: dict, workspace_root: str) -> str:
    """在工作区内用 grep 搜索文件内容。"""
    pattern = args.get("pattern") or ""
    if not pattern:
        return json.dumps({"error": "grep 需要 pattern 参数"}, ensure_ascii=False)
    search_path = args.get("path") or "."
    abs_search = resolve_path(search_path, workspace_root)
    try:
        r = subprocess.run(
            ["grep", "-rn", "--", pattern, abs_search],
            capture_output=True, text=True, timeout=30, cwd=workspace_root,
        )
        output = (r.stdout or "").strip()
        return output if output else "No matches found"
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "grep 执行超时（30s）"}, ensure_ascii=False)


def handle_bash(args: dict, workspace_root: str) -> str:
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
}


def _print_tool_invocation(name: str, args: dict) -> None:
    """向 stdout 打印工具调用摘要，便于 REPL 用户看到进度。"""
    detail = ""
    if name in ("read", "write", "edit"):
        p = (args.get("path") or "").strip()
        if p:
            detail = f" path={p}"
    elif name == "bash":
        cmd = (args.get("command") or "").strip()
        if cmd:
            detail = f" command={cmd[:100]}{'…' if len(cmd) > 100 else ''}"
    elif name == "glob":
        detail = f" pattern={args.get('pattern', '')}"
    elif name == "grep":
        detail = f" pattern={args.get('pattern', '')} path={args.get('path', '.')}"
    elif name in PLAN_MODE_HANDLERS:
        pass
    print(f"[调用工具] {name}{detail}", flush=True)


def execute_tool(name: str, args: dict, workspace_root: str = None,
                 context: dict = None) -> str:
    """按工具名分发执行，返回结果字符串。

    context 承载 plan mode 状态（mode, plan_dir 等），由 REPL 层创建并透传。
    """
    root = workspace_root or WORKSPACE_ROOT
    ctx = context or {}

    blocked = check_plan_mode(name, args, ctx)
    if blocked:
        _print_tool_invocation(name, args)
        return blocked

    plan_handler = PLAN_MODE_HANDLERS.get(name)
    if plan_handler:
        _print_tool_invocation(name, args)
        try:
            return plan_handler(args, root, ctx)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    _print_tool_invocation(name, args)
    try:
        return handler(args, root)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"{name} 执行超时"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool Schema
# ---------------------------------------------------------------------------

def get_tool_schemas() -> list[dict]:
    """返回所有工具的 OpenAI function-calling 风格定义（含 plan mode 工具）。"""
    return [
        {"type": "function", "function": {
            "name": "read",
            "description": "Read a file and return its content with line numbers. Use offset/limit for partial reads on large files.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path under workspace"},
                "offset": {"type": "integer", "description": "Start line (0-based, default 0)"},
                "limit": {"type": "integer", "description": "Max number of lines to read"},
            }, "required": ["path"]},
        }},
        {"type": "function", "function": {
            "name": "write",
            "description": "Write content to a file (overwrites if exists, creates parent directories as needed).",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path under workspace"},
                "content": {"type": "string", "description": "File content to write"},
            }, "required": ["path", "content"]},
        }},
        {"type": "function", "function": {
            "name": "edit",
            "description": "Replace a unique string in a file. old_string must appear exactly once.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path under workspace"},
                "old_string": {"type": "string", "description": "The exact string to find (must appear once)"},
                "new_string": {"type": "string", "description": "The replacement string"},
            }, "required": ["path", "old_string", "new_string"]},
        }},
        {"type": "function", "function": {
            "name": "glob",
            "description": "Find files matching a glob pattern within the workspace. Use ** for recursive matching.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py', '*.md')"},
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "grep",
            "description": "Search file contents for a pattern (regex) within the workspace.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {"type": "string", "description": "Relative path to search in (default: workspace root)"},
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "bash",
            "description": "Run a shell command in the workspace directory.",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
            }, "required": ["command"]},
        }},
    ] + get_plan_tool_schemas()
