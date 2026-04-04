"""命令行 REPL：读入、内置命令、调用 API 与 tool 循环。"""
import argparse
import os
import sys
from typing import Optional

import openai

from miniclaw.api import create_client, get_api_key, run_turn_with_tools
from miniclaw.config import DEFAULT_MODEL, WORKSPACE_ROOT
from miniclaw.dev_logging import setup_dev_logging
from miniclaw.skills import build_system_prompt, scan_skills_metadata
from miniclaw.tools import get_tool_schemas


def resolve_workspace(cli_arg: Optional[str]) -> str:
    """按优先级解析工作区目录：CLI 参数 > 环境变量 > 项目根。"""
    raw = cli_arg or os.environ.get("MINICLAW_WORKSPACE", "").strip() or WORKSPACE_ROOT
    workspace = os.path.abspath(raw)
    if not os.path.isdir(workspace):
        print(f"错误: 工作区目录不存在: {workspace}", file=sys.stderr)
        sys.exit(1)
    return workspace


def _init_session(args: argparse.Namespace) -> dict:
    """初始化会话：日志、客户端、技能、system prompt、工具。返回会话配置 dict。"""
    setup_dev_logging()
    api_key = get_api_key()
    client = create_client(api_key)
    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
    workspace = resolve_workspace(args.workspace)

    skills_dir = os.path.join(workspace, ".skills")
    skill_meta = scan_skills_metadata(skills_dir)
    system_prompt = build_system_prompt(skill_meta, workspace_root=workspace)
    extra_system = os.environ.get("MINIMAX_SYSTEM", "").strip()
    if extra_system:
        system_prompt = system_prompt + "\n\n" + extra_system

    return {
        "client": client,
        "model": model,
        "workspace": workspace,
        "system_prompt": system_prompt,
        "tools": get_tool_schemas(),
    }


def _repl_loop(session: dict) -> None:
    """REPL 主循环：读取用户输入、处理内置命令、调用 API。"""
    client = session["client"]
    model = session["model"]
    workspace = session["workspace"]
    system_prompt = session["system_prompt"]
    tools = session["tools"]
    messages = [{"role": "system", "content": system_prompt}]

    plan_file = os.path.join(workspace, ".miniclaw", "plan.md")
    context = {"mode": "agent", "plan_file": plan_file, "workspace_root": workspace}

    print(f"工作区: {workspace}")
    print("MiniMax 命令行对话 + Code Execution + .skills "
          "(输入 /quit 退出, /clear 清空历史, /model 查看当前模型)")
    print("-" * 50)

    while True:
        try:
            mode_label = " [plan]" if context["mode"] == "plan" else ""
            user_input = input(f"你{mode_label}: ").strip()
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
            print("[已清空对话历史]")
            continue
        if user_input == "/model":
            print(f"当前模型: {model}")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            reply, messages = run_turn_with_tools(
                client, model, messages, tools,
                print_reasoning=True, workspace_root=workspace,
                context=context,
            )
            print()
        except (openai.APIError, RuntimeError) as e:
            label = "网络错误" if isinstance(e, openai.APIConnectionError) else \
                    "API 错误" if isinstance(e, openai.APIError) else "错误"
            print(f"\n[{label}] {e}\n", file=sys.stderr)
            messages.pop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MiniMax 命令行 LLM 对话工具，支持 code-execution 与 .skills 技能目录",
    )
    parser.add_argument(
        "-w", "--workspace",
        default=None,
        help="工作区目录（技能扫描与文件操作的根）。也可通过 MINICLAW_WORKSPACE 环境变量设置。"
             "未指定时默认为项目根目录。",
    )
    args = parser.parse_args()
    session = _init_session(args)
    _repl_loop(session)
