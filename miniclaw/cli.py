"""命令行 REPL：读入、内置命令、调用 API 与 tool 循环。"""
import argparse
import os
import sys

import openai
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

from prompt_toolkit.formatted_text import HTML

from miniclaw.api import create_client, run_turn_with_tools
from miniclaw.dev_logging import setup_dev_logging
from miniclaw.dirs import ensure_user_config, get_log_dir, get_user_data_dir, resolve_workspace
from miniclaw.settings import get_llm_config, get_context_config
from miniclaw.context import format_context_status, manual_compact, init_ctx_mgmt
from miniclaw.skills import build_system_prompt, discover_skills
from miniclaw.plan_mode import get_plan_mode_instructions
from miniclaw.tools import get_tool_schemas
from miniclaw.ui import print_banner, print_compact_progress, print_error, print_status


def _create_prompt_session() -> PromptSession:
    """创建支持 CJK 和多行编辑的 PromptSession。"""
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    @bindings.add("c-j")
    def _insert_newline(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        key_bindings=bindings,
        multiline=False,
    )


def _init_session(args: argparse.Namespace) -> dict:
    """初始化会话：日志、客户端、技能、system prompt、工具。返回会话配置 dict。"""
    config_path, created = ensure_user_config()
    if created:
        print(f"[首次运行] 已创建默认配置: {config_path}")
    setup_dev_logging()
    workspace = resolve_workspace(args.workspace)
    llm_cfg = get_llm_config(workspace)
    client = create_client(llm_cfg["api_key"], llm_cfg["base_url"])

    registry = discover_skills(workspace)
    system_prompt = build_system_prompt(registry.list_metadata(), workspace_root=workspace)

    return {
        "client": client,
        "model": llm_cfg["model"],
        "timeout": llm_cfg["timeout"],
        "workspace": workspace,
        "system_prompt": system_prompt,
        "skill_registry": registry,
        "tools": get_tool_schemas(),
        "context_config": get_context_config(workspace),
    }


def _repl_loop(session: dict) -> None:
    """REPL 主循环：读取用户输入、处理内置命令、调用 API。"""
    client = session["client"]
    model = session["model"]
    timeout = session["timeout"]
    workspace = session["workspace"]
    system_prompt = session["system_prompt"]
    skill_registry = session["skill_registry"]
    tools = session["tools"]
    context_config = session["context_config"]
    messages = [{"role": "system", "content": system_prompt}]

    plan_dir = os.path.join(workspace, ".miniclaw", "plans")
    context = {
        "mode": "agent",
        "plan_dir": plan_dir,
        "workspace_root": workspace,
        "skill_registry": skill_registry,
    }
    init_ctx_mgmt(context)

    prompt_session = _create_prompt_session()

    print_banner(model, workspace)

    while True:
        try:
            if context["mode"] == "plan":
                prompt_text = HTML("<style fg='ansiyellow'>[plan]</style> <style fg='ansigreen'>❯</style> ")
            else:
                prompt_text = HTML("<style fg='ansigreen'>❯</style> ")
            user_input = prompt_session.prompt(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "/q"):
            print("再见。")
            break
        if user_input == "/clear":
            messages = [{"role": "system", "content": system_prompt}]
            context["mode"] = "agent"
            context.pop("_ctx_mgmt", None)
            init_ctx_mgmt(context)
            print_status("已清空对话历史")
            continue
        if user_input == "/model":
            print_status(f"当前模型: {model}")
            continue
        if user_input == "/context":
            print_status(format_context_status(messages, context_config, context))
            continue
        if user_input == "/compact" or user_input.startswith("/compact "):
            extra = user_input[8:].strip() if user_input.startswith("/compact ") else ""
            new_messages, ok = manual_compact(
                client, model, messages, context_config, context,
                extra_instructions=extra, timeout=timeout,
                on_compact_progress=print_compact_progress,
            )
            if ok:
                messages = new_messages
                print_status("对话已压缩为摘要")
            else:
                print_error("压缩", "摘要生成失败或对话过短")
            continue
        if user_input == "/plan" or user_input.startswith("/plan "):
            if context["mode"] == "plan":
                print_status("已在 Plan Mode 中")
                continue
            context["mode"] = "plan"
            instructions = get_plan_mode_instructions(plan_dir)
            print_status(f"已进入 Plan Mode，plan 目录: {plan_dir}/")
            description = user_input[5:].strip()
            content = (f"{instructions}\n\n用户需求：{description}"
                       if description else instructions)
            messages.append({"role": "user", "content": content})
            try:
                reply, messages = run_turn_with_tools(
                    client, model, messages, tools,
                    print_reasoning=True, timeout=timeout,
                    workspace_root=workspace, context=context,
                    context_config=context_config,
                    on_compact_progress=print_compact_progress,
                )
                print()
            except (openai.APIError, RuntimeError) as e:
                label = "网络错误" if isinstance(e, openai.APIConnectionError) else \
                        "API 错误" if isinstance(e, openai.APIError) else "错误"
                print_error(label, str(e))
                messages.pop()
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            reply, messages = run_turn_with_tools(
                client, model, messages, tools,
                print_reasoning=True, timeout=timeout,
                workspace_root=workspace, context=context,
                context_config=context_config,
                on_compact_progress=print_compact_progress,
            )
            print()
        except (openai.APIError, RuntimeError) as e:
            label = "网络错误" if isinstance(e, openai.APIConnectionError) else \
                    "API 错误" if isinstance(e, openai.APIError) else "错误"
            print_error(label, str(e))
            messages.pop()


def _handle_init(args: argparse.Namespace) -> None:
    """处理 miniclaw init 子命令。"""
    config_path, created = ensure_user_config(force=args.force)
    if created:
        print(f"已创建默认配置: {config_path}")
    else:
        print(f"配置文件已存在: {config_path}（使用 --force 覆盖）")
    print(f"用户数据目录: {get_user_data_dir()}")
    print(f"日志目录: {get_log_dir()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="miniclaw — 命令行 LLM 对话工具，支持 code-execution 与 .skills 技能目录",
    )
    parser.add_argument(
        "-w", "--workspace",
        default=None,
        help="工作区目录（技能扫描与文件操作的根）。也可通过 MINICLAW_WORKSPACE 环境变量设置。"
             "未指定时默认为当前目录。",
    )
    subparsers = parser.add_subparsers(dest="command")
    init_parser = subparsers.add_parser(
        "init", help="初始化 ~/.miniclaw/ 目录和默认配置",
    )
    init_parser.add_argument(
        "--force", action="store_true", help="覆盖已有配置文件",
    )

    args = parser.parse_args()
    if args.command == "init":
        _handle_init(args)
        return
    session = _init_session(args)
    _repl_loop(session)
