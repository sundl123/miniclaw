"""Plan Mode：只读探索 + 结构化规划阶段，含权限检查、enter/exit handler 与 tool schema。"""
import json
import os

from miniclaw.config import WORKSPACE_ROOT, resolve_path


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
    root = context.get("workspace_root") or WORKSPACE_ROOT
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
    plan_dir = context.get("plan_dir", "")
    return json.dumps({
        "error": "当前处于 Plan Mode（规划模式），不允许执行写操作。"
                 f"唯一例外是 plan 目录：{plan_dir}/ 下的文件。"
                 "请先完成规划，然后调用 exit_plan_mode 退出规划模式。"
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

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
    """退出 plan mode：需用户审批通过后才切换到 agent mode。

    用户输入 y/yes/空回车 → 批准，切换 mode；其他输入视为修改意见，
    mode 保持 plan，反馈通过 tool result 回传给模型继续优化。
    """
    if context.get("mode") != "plan":
        return json.dumps({
            "error": "当前不在规划模式中，无需退出。"
        }, ensure_ascii=False)

    plan_dir = context.get("plan_dir", ".miniclaw/plans")

    print(f"\n[Plan Mode] 模型已完成规划，plan 文件位于 {plan_dir}/")
    print("请审阅后输入 y 批准执行，或输入修改意见继续优化：")
    response = input("审阅: ").strip()

    if response.lower() in ("y", "yes", ""):
        context["mode"] = "agent"
        return (
            "用户已批准计划，进入执行模式。\n"
            "你现在可以使用所有工具来实施计划。\n"
            "\n"
            "重要：请遵循以下执行规范：\n"
            f"1. 先用 read 工具读取 {plan_dir}/ 下的 plan 文件确认计划内容\n"
            "2. 按照 Steps 中的 todo list 逐项执行\n"
            "3. 每完成一个步骤后，用 edit 工具更新对应的 plan 文件，将对应的 - [ ] 改为 - [x]\n"
            "4. 所有步骤完成后，执行 Verification 部分描述的验证操作"
        )

    return (
        "用户未批准计划，仍处于 Plan Mode。\n"
        f"用户反馈：{response}\n"
        "请根据反馈修改 plan 文件，完成后再次调用 exit_plan_mode。"
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
