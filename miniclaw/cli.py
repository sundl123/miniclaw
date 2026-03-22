"""命令行 REPL：读入、内置命令、调用 API 与 tool 循环。"""
import os
import sys

import requests

from miniclaw.api import get_api_key, run_turn_with_tools
from miniclaw.config import DEFAULT_MODEL
from miniclaw.dev_logging import setup_dev_logging
from miniclaw.skills import build_system_prompt, scan_skills_metadata
from miniclaw.code_execution import get_code_execution_tool_schema


def main() -> None:
    setup_dev_logging()
    api_key = get_api_key()
    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
    skill_meta = scan_skills_metadata()
    system_prompt = build_system_prompt(skill_meta)
    extra_system = os.environ.get("MINIMAX_SYSTEM", "").strip()
    if extra_system:
        system_prompt = system_prompt + "\n\n" + extra_system
    tools = [get_code_execution_tool_schema()]

    messages = [{"role": "system", "content": system_prompt}]

    print("MiniMax 命令行对话 + Code Execution + .skills (输入 /quit 退出, /clear 清空历史, /model 查看当前模型)")
    print("-" * 50)

    while True:
        try:
            user_input = input("你: ").strip()
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
            print("[已清空对话历史]")
            continue
        if user_input == "/model":
            print(f"当前模型: {model}")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            reply, messages = run_turn_with_tools(
                api_key, model, messages, tools, print_reasoning=True
            )
            print(f"\nMiniMax: {reply}\n")
        except requests.RequestException as e:
            print(f"\n[网络/请求错误] {e}\n", file=sys.stderr)
            messages.pop()
        except RuntimeError as e:
            print(f"\n[API 错误] {e}\n", file=sys.stderr)
            messages.pop()
