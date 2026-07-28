"""工具注册表与分发：plan/explore 门控 + execute_tool。"""
from __future__ import annotations

import json
import os
import subprocess

from miniclaw.memory.tool import handle_memory
from miniclaw.plan_mode import (
    PLAN_MODE_HANDLERS,
    check_plan_mode,
    is_readonly_bash,
)
from miniclaw.sessions.search import handle_session_search
from miniclaw.settings import get_plan_allowed_patterns, get_tools_config
from miniclaw.subagent.tool import handle_agent
from miniclaw.subagent.types import AGENT_TOOL_NAME
from miniclaw.tool_output import cap_tool_result
from miniclaw.tools.bash import handle_bash
from miniclaw.tools.config import ToolsConfig
from miniclaw.tools.read import handle_read
from miniclaw.tools.search import handle_glob, handle_grep
from miniclaw.tools.skill import handle_skill
from miniclaw.tools.write import handle_edit, handle_write
from miniclaw.ui import print_tool_call

TOOL_HANDLERS = {
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "glob": handle_glob,
    "grep": handle_grep,
    "bash": handle_bash,
    "Skill": handle_skill,
    "memory": handle_memory,
    "session_search": handle_session_search,
    AGENT_TOOL_NAME: handle_agent,
}


def _print_tool_invocation(name: str, args: dict, *, context: dict | None = None) -> None:
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
    elif name == "memory":
        detail = f"action={args.get('action', '')} path={args.get('path', '')}"
    elif name == "session_search":
        if args.get("query"):
            detail = f"query={args.get('query', '')[:60]}"
        elif args.get("session_id"):
            detail = f"session_id={args.get('session_id')} around_seq={args.get('around_seq', '')}"
        else:
            detail = "browse"
    elif name == AGENT_TOOL_NAME:
        detail = (
            f"type={args.get('subagent_type') or 'general'} "
            f"desc={args.get('description', '')}"
        )
    elif name in PLAN_MODE_HANDLERS:
        pass
    indent = int((context or {}).get("agent_depth") or 0)
    print_tool_call(name, detail, indent=indent)


def _check_readonly_bash(name: str, args: dict, context: dict) -> str | None:
    """Explore sub-agent: reject non-readonly bash even outside plan mode."""
    if name != "bash" or not context.get("readonly_bash_only"):
        return None
    command = args.get("command", "")
    root = context.get("workspace_root") or os.getcwd()
    extra = context.get("_plan_allowed_patterns")
    if extra is None:
        extra = get_plan_allowed_patterns(root)
        context["_plan_allowed_patterns"] = extra
    if is_readonly_bash(command, extra):
        return None
    return json.dumps({
        "error": (
            "Explore sub-agent only allows read-only bash commands "
            "(e.g. ls, cat, git log, find, wc). "
            "The current command may have side effects and was rejected."
        ),
    }, ensure_ascii=False)


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
        _print_tool_invocation(name, args, context=ctx)
        return blocked

    readonly_blocked = _check_readonly_bash(name, args, ctx)
    if readonly_blocked:
        _print_tool_invocation(name, args, context=ctx)
        return readonly_blocked

    plan_handler = PLAN_MODE_HANDLERS.get(name)
    if plan_handler:
        _print_tool_invocation(name, args, context=ctx)
        try:
            result = plan_handler(args, root, ctx)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return cap_tool_result(result, cfg.max_tool_result_chars, tool_name=name)

    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    _print_tool_invocation(name, args, context=ctx)
    try:
        if name in ("read", "grep", "glob"):
            result = handler(args, root, tools_cfg=cfg, context=ctx)
        elif name == "Skill":
            result = handler(args, root, context=ctx)
        elif name == AGENT_TOOL_NAME:
            result = handler(args, root, context=ctx)
        elif name == "memory":
            result = handler(args, context=ctx, tools_cfg=cfg)
        elif name == "session_search":
            result = handler(
                args,
                db=ctx.get("session_db"),
                current_session_id=ctx.get("session_id"),
                config=ctx.get("sessions_config"),
            )
        else:
            result = handler(args, root, tools_cfg=cfg)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"{name} 执行超时"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    return cap_tool_result(result, cfg.max_tool_result_chars, tool_name=name)
