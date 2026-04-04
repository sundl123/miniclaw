"""工具集：read、write、edit、glob、grep、bash + plan mode 工具，均限制在 workspace 内。"""
import glob as glob_module
import json
import os
import subprocess

from miniclaw.config import WORKSPACE_ROOT


# ---------------------------------------------------------------------------
# 路径安全
# ---------------------------------------------------------------------------

def resolve_path(path: str, workspace_root: str = None) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    root = workspace_root or WORKSPACE_ROOT
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(root, path))
    if not abs_path.startswith(root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


# ---------------------------------------------------------------------------
# Plan Mode
# ---------------------------------------------------------------------------

READONLY_TOOLS = frozenset({"read", "glob", "grep", "enter_plan_mode", "exit_plan_mode"})


def _is_plan_dir_write(name: str, args: dict, context: dict) -> bool:
    """检查写操作目标是否在 plan 目录内（plan mode 下豁免的写入范围）。"""
    if name not in ("write", "edit"):
        return False
    plan_dir = context.get("plan_dir", "")
    target_path = args.get("path", "")
    if not plan_dir or not target_path:
        return False
    root = context.get("workspace_root") or WORKSPACE_ROOT
    abs_target = resolve_path(target_path, root)
    abs_plan_dir = os.path.normpath(plan_dir)
    return os.path.normpath(abs_target).startswith(abs_plan_dir + os.sep) or \
           os.path.normpath(abs_target) == abs_plan_dir


def _check_plan_mode(name: str, args: dict, context: dict):
    """Plan mode 下拦截写操作，返回错误消息；通过时返回 None。"""
    if not context or context.get("mode") != "plan":
        return None
    if name in READONLY_TOOLS:
        return None
    if _is_plan_dir_write(name, args, context):
        return None
    plan_dir = context.get("plan_dir", "")
    return json.dumps({
        "error": "当前处于 Plan Mode（规划模式），不允许执行写操作。"
                 f"唯一例外是 plan 目录：{plan_dir}/ 下的文件。"
                 "请先完成规划，然后调用 exit_plan_mode 退出规划模式。"
    }, ensure_ascii=False)


def handle_enter_plan_mode(args: dict, workspace_root: str, context: dict) -> str:
    """进入 plan mode：设置 mode='plan'，返回规划阶段指令。"""
    if context.get("mode") == "plan":
        return json.dumps({
            "error": "已在规划模式中，不允许嵌套进入。"
                     "请先调用 exit_plan_mode 退出后再重新进入。"
        }, ensure_ascii=False)

    context["mode"] = "plan"
    plan_dir = context.get("plan_dir", ".miniclaw/plans")
    return (
        "已进入 Plan Mode（规划模式）。\n"
        "\n"
        "你现在处于只读探索和规划阶段，请遵循以下工作流程：\n"
        "\n"
        "## 规则\n"
        "- 可以使用 read、glob、grep 来探索代码库\n"
        "- 不要使用 write、edit、bash 等修改操作（会被拒绝）\n"
        f"- 唯一例外：可以使用 write/edit 工具在 {plan_dir}/ 目录下创建和编辑 plan 文件\n"
        "\n"
        "## 工作流程\n"
        "1. 使用只读工具探索代码库，理解现有结构\n"
        f"2. 在 {plan_dir}/ 目录下创建 plan 文件（文件名自定，如 refactor-api.md），格式要求如下：\n"
        "   - 包含 Context（背景）、Steps（实施步骤）、Verification（验证方式）三个部分\n"
        "   - Steps 部分必须使用 todo list 格式（- [ ] 未完成 / - [x] 已完成）\n"
        "3. 准备好执行时，调用 exit_plan_mode 退出规划模式\n"
        "\n"
        "## plan 文件格式示例\n"
        "```\n"
        "# Plan: [标题]\n"
        "## Context\n"
        "[简述背景和目标]\n"
        "## Steps\n"
        "- [ ] 步骤 1: ...\n"
        "- [ ] 步骤 2: ...\n"
        "- [ ] 步骤 3: ...\n"
        "## Verification\n"
        "[如何验证变更是正确的]\n"
        "```"
    )


def handle_exit_plan_mode(args: dict, workspace_root: str, context: dict) -> str:
    """退出 plan mode：设置 mode='agent'，返回执行阶段指令。"""
    if context.get("mode") != "plan":
        return json.dumps({
            "error": "当前不在规划模式中，无需退出。"
        }, ensure_ascii=False)

    context["mode"] = "agent"
    plan_dir = context.get("plan_dir", ".miniclaw/plans")
    return (
        "已退出 Plan Mode，进入执行模式。\n"
        "你现在可以使用所有工具来实施计划。\n"
        "\n"
        "重要：请遵循以下执行规范：\n"
        f"1. 先用 read 工具读取 {plan_dir}/ 下的 plan 文件确认计划内容\n"
        "2. 按照 Steps 中的 todo list 逐项执行\n"
        "3. 每完成一个步骤后，用 edit 工具更新对应的 plan 文件，将对应的 - [ ] 改为 - [x]\n"
        "4. 所有步骤完成后，执行 Verification 部分描述的验证操作"
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
# 工具注册表与 Schema
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "glob": handle_glob,
    "grep": handle_grep,
    "bash": handle_bash,
}

# Plan mode 工具需要 context 参数，单独注册
PLAN_MODE_HANDLERS = {
    "enter_plan_mode": handle_enter_plan_mode,
    "exit_plan_mode": handle_exit_plan_mode,
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
    elif name in ("enter_plan_mode", "exit_plan_mode"):
        pass
    print(f"[调用工具] {name}{detail}", flush=True)


def execute_tool(name: str, args: dict, workspace_root: str = None,
                 context: dict = None) -> str:
    """按工具名分发执行，返回结果字符串。

    context 承载 plan mode 状态（mode, plan_dir 等），由 REPL 层创建并透传。
    """
    root = workspace_root or WORKSPACE_ROOT
    ctx = context or {}

    # Plan mode 写操作拦截（豁免 plan 文件和只读工具）
    blocked = _check_plan_mode(name, args, ctx)
    if blocked:
        _print_tool_invocation(name, args)
        return blocked

    # Plan mode 专用工具（需要 context 来读写 mode 状态）
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


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 OpenAI function-calling 风格定义。"""
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
        {"type": "function", "function": {
            "name": "enter_plan_mode",
            "description": (
                "Enter plan mode for read-only exploration and planning. "
                "In plan mode, only read tools and writing to the plans directory are allowed. "
                "Use this before making changes to explore the codebase and create a plan."
            ),
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "exit_plan_mode",
            "description": (
                "Exit plan mode and switch to execution mode. "
                "Call this after you have finished your plan and are ready to implement."
            ),
            "parameters": {"type": "object", "properties": {}},
        }},
    ]
