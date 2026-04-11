"""Plan Mode：只读探索 + 结构化规划阶段，含权限检查、enter/exit handler 与 tool schema。"""
from __future__ import annotations

import json
import os
import re
import shlex

from miniclaw.config import resolve_path
from miniclaw.settings import get_plan_allowed_patterns


# ---------------------------------------------------------------------------
# Bash 只读命令白名单
# ---------------------------------------------------------------------------

READONLY_BASH_COMMANDS = frozenset({
    # 文件内容查看
    "cat", "head", "tail", "less", "more", "wc", "file", "strings",
    # 目录与文件信息
    "ls", "tree", "du", "df", "stat", "find", "which", "realpath",
    "basename", "dirname", "readlink",
    # 文本搜索与处理（只读类）
    "grep", "rg", "sort", "uniq", "cut", "diff", "comm", "tr", "column",
    # 系统信息
    "pwd", "whoami", "uname", "date", "echo", "printf", "true", "false",
    # 开发工具版本查询
    "node", "python3", "python", "npm", "pip",
})

GIT_READONLY_SUBCOMMANDS = frozenset({
    "log", "status", "diff", "branch", "show", "tag",
    "remote", "ls-files", "blame", "shortlog", "describe",
})

_COMPOUND_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||[;|])\s*")
_REDIRECT_RE = re.compile(r"(?:>>?|<<)")


def _is_single_command_readonly(
    command: str, extra_patterns: list[re.Pattern] | None = None,
) -> bool:
    """判断单条（非复合）命令是否为只读。"""
    stripped = command.strip()
    if not stripped:
        return True

    if _REDIRECT_RE.search(stripped):
        return False

    try:
        tokens = shlex.split(stripped)
    except ValueError:
        return False
    if not tokens:
        return True

    base_cmd = os.path.basename(tokens[0])

    if base_cmd == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        return sub in GIT_READONLY_SUBCOMMANDS

    if base_cmd in READONLY_BASH_COMMANDS:
        return True

    if extra_patterns:
        for pat in extra_patterns:
            if pat.search(stripped):
                return True

    return False


def is_readonly_bash(
    command: str, extra_patterns: list[re.Pattern] | None = None,
) -> bool:
    """判断 bash 命令是否为只读。复合命令要求每段都只读。"""
    parts = _COMPOUND_SPLIT_RE.split(command)
    return all(_is_single_command_readonly(p, extra_patterns) for p in parts)


# ---------------------------------------------------------------------------
# 权限检查
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
    root = context.get("workspace_root") or os.getcwd()
    abs_target = resolve_path(target_path, root)
    abs_plan_dir = os.path.normpath(plan_dir)
    return os.path.normpath(abs_target).startswith(abs_plan_dir + os.sep) or \
           os.path.normpath(abs_target) == abs_plan_dir


def check_plan_mode(name: str, args: dict, context: dict):
    """Plan mode 下拦截写操作，返回错误消息；通过时返回 None。"""
    if not context or context.get("mode") != "plan":
        return None
    if name in READONLY_TOOLS:
        return None
    if _is_plan_dir_write(name, args, context):
        return None

    if name == "bash":
        command = args.get("command", "")
        root = context.get("workspace_root") or os.getcwd()
        extra = context.get("_plan_allowed_patterns")
        if extra is None:
            extra = get_plan_allowed_patterns(root)
            context["_plan_allowed_patterns"] = extra
        if is_readonly_bash(command, extra):
            return None
        return json.dumps({
            "error": "Plan Mode 下只允许执行只读 bash 命令（如 ls, cat, git log, find, wc 等）。"
                     "当前命令可能产生副作用，已被拒绝。"
                     "请继续使用只读命令探索代码库，完成你的 plan 文件。"
        }, ensure_ascii=False)

    plan_dir = context.get("plan_dir", "")
    return json.dumps({
        "error": "Plan Mode 下不允许执行此写操作。"
                 f"你只能在 plan 目录（{plan_dir}/）下创建和编辑 plan 文件。"
                 "请继续探索代码库并完善你的 plan 文件，而不是尝试修改代码。"
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def get_plan_mode_instructions(plan_dir: str) -> str:
    """返回进入 plan mode 时注入给模型的指令文本。

    供 handle_enter_plan_mode（tool call 触发）和 /plan 命令（用户手动触发）共用。
    """
    return (
        "已进入 Plan Mode（规划模式）。\n"
        "\n"
        "你现在处于只读探索和规划阶段，请遵循以下工作流程：\n"
        "\n"
        "## 规则\n"
        "- 可以使用 read、glob、grep 来探索代码库\n"
        "- 可以使用 bash 执行只读命令（如 ls、cat、git log、find、wc、grep 等）\n"
        "- 不允许使用 bash 执行写操作（如 rm、mv、mkdir、git commit/push 等，会被拒绝）\n"
        "- 不允许使用 write、edit 工具修改文件（plan 目录除外）\n"
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


def handle_enter_plan_mode(args: dict, workspace_root: str, context: dict) -> str:
    """进入 plan mode：设置 mode='plan'，返回规划阶段指令。"""
    if context.get("mode") == "plan":
        return json.dumps({
            "error": "已在规划模式中，不允许嵌套进入。"
                     "请先调用 exit_plan_mode 退出后再重新进入。"
        }, ensure_ascii=False)

    context["mode"] = "plan"
    return get_plan_mode_instructions(context.get("plan_dir", ".miniclaw/plans"))


def handle_exit_plan_mode(args: dict, workspace_root: str, context: dict) -> str:
    """退出 plan mode，切换到 agent mode 开始执行。"""
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
# 注册表与 Schema
# ---------------------------------------------------------------------------

PLAN_MODE_HANDLERS = {
    "enter_plan_mode": handle_enter_plan_mode,
    "exit_plan_mode": handle_exit_plan_mode,
}


def get_plan_tool_schemas() -> list[dict]:
    """返回 plan mode 工具的 OpenAI function-calling 风格定义。"""
    return [
        {"type": "function", "function": {
            "name": "enter_plan_mode",
            "description": (
                "Enter plan mode for read-only exploration and planning. "
                "In plan mode, only read tools and writing to the plans directory are allowed. "
                "You SHOULD proactively enter plan mode when the user's request is complex, "
                "involves multiple steps, or requires understanding existing code before making changes. "
                "Do not wait for the user to ask — if the task is non-trivial, plan first."
            ),
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "exit_plan_mode",
            "description": (
                "Exit plan mode and switch to execution mode. "
                "IMPORTANT: Before calling this tool, you MUST present your plan to the user "
                "and explicitly ask for their approval (e.g. '以上是我的实现计划，是否可以开始执行？'). "
                "Only call exit_plan_mode AFTER the user has confirmed they agree with the plan. "
                "If the user requests changes, revise the plan first, then ask again."
            ),
            "parameters": {"type": "object", "properties": {}},
        }},
    ]
