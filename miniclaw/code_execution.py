"""Code execution 工具：run_bash、view_file、create_file、edit_file。"""
import json
import os
import subprocess

from miniclaw.config import WORKSPACE_ROOT


def resolve_path(path: str, workspace_root: str = None) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    root = workspace_root or WORKSPACE_ROOT
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(root, path))
    if not abs_path.startswith(root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


def _run_bash(arguments: dict, workspace_root: str) -> str:
    cmd = arguments.get("command") or ""
    if not cmd:
        return json.dumps({"error": "run_bash 需要 command 参数"}, ensure_ascii=False)
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


def _view_file(arguments: dict, workspace_root: str) -> str:
    path = arguments.get("path") or ""
    if not path:
        return json.dumps({"error": "view_file 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    if not os.path.isfile(abs_path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _create_file(arguments: dict, workspace_root: str) -> str:
    path = arguments.get("path") or ""
    content = arguments.get("content") or ""
    if not path:
        return json.dumps({"error": "create_file 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Created file: {path}"


def _edit_file(arguments: dict, workspace_root: str) -> str:
    path = arguments.get("path") or ""
    content = arguments.get("content") or ""
    mode = (arguments.get("mode") or "replace").strip().lower()
    if not path:
        return json.dumps({"error": "edit_file 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    if mode == "append":
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended to: {path}"
    if mode == "insert":
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content + old)
        return f"Inserted at beginning of: {path}"
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Replaced content of: {path}"


def handle_code_execution(arguments: dict, workspace_root: str = None) -> str:
    """执行 code_execution 工具：根据 action 分发到 run_bash / view_file / create_file / edit_file。"""
    root = workspace_root or WORKSPACE_ROOT
    action = (arguments.get("action") or "").strip()
    if not action:
        return json.dumps({"error": "缺少 action 参数"}, ensure_ascii=False)

    try:
        if action == "run_bash":
            return _run_bash(arguments, root)
        if action == "view_file":
            return _view_file(arguments, root)
        if action == "create_file":
            return _create_file(arguments, root)
        if action == "edit_file":
            return _edit_file(arguments, root)
        return json.dumps({"error": f"未知 action: {action}"}, ensure_ascii=False)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "run_bash 执行超时（60s）"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_code_execution_tool_schema() -> dict:
    """返回 MiniMax/OpenAI 风格的 code_execution 工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": "code_execution",
            "description": "Execute bash commands or read/write files in the workspace. Use view_file to read .skills/<name>/SKILL.md for skill instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run_bash", "view_file", "create_file", "edit_file"],
                        "description": "Operation: run_bash, view_file, create_file, edit_file",
                    },
                    "command": {
                        "type": "string",
                        "description": "Bash command (required when action=run_bash)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path under workspace (required for view_file, create_file, edit_file)",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content (required for create_file, edit_file)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append", "insert"],
                        "description": "For edit_file: replace (default), append, insert",
                    },
                },
                "required": ["action"],
            },
        },
    }
