#!/usr/bin/env python3
"""
基于 MiniMax API 的命令行 LLM 对话工具。
使用方式: MINIMAX_API_KEY=your_key python chat.py
"""
import os
import sys
import json
import requests

# MiniMax 文本对话 API
BASE_URL = "https://api.minimax.io"
CHAT_URL = f"{BASE_URL}/v1/text/chatcompletion_v2"
DEFAULT_MODEL = "MiniMax-M2.5"


def get_api_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        print("错误: 请设置环境变量 MINIMAX_API_KEY", file=sys.stderr)
        print("示例: export MINIMAX_API_KEY=your_api_key", file=sys.stderr)
        sys.exit(1)
    return key


def chat(api_key: str, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> str:
    """调用 MiniMax 对话 API，返回助手回复文本。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        **kwargs,
    }
    resp = requests.post(CHAT_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # 检查业务状态码
    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        msg = base.get("status_msg", "Unknown error")
        raise RuntimeError(f"MiniMax API 错误: {msg} (code={base.get('status_code')})")

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("API 返回无内容")

    msg = choices[0].get("message", {})
    content = msg.get("content", "").strip()
    return content


def main():
    api_key = get_api_key()
    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
    system_prompt = os.environ.get("MINIMAX_SYSTEM", "").strip()
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    print("MiniMax 命令行对话 (输入 /quit 退出, /clear 清空历史, /model 查看当前模型)")
    print("-" * 50)

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not user_input:
            continue

        # 内置命令
        if user_input in ("/quit", "/exit", "/q"):
            print("再见。")
            break
        if user_input == "/clear":
            messages.clear()
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            print("[已清空对话历史]")
            continue
        if user_input == "/model":
            print(f"当前模型: {model}")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            reply = chat(api_key, messages, model=model)
            messages.append({"role": "assistant", "content": reply})
            print(f"\nMiniMax: {reply}\n")
        except requests.RequestException as e:
            print(f"\n[网络/请求错误] {e}\n", file=sys.stderr)
            messages.pop()  # 移除刚加入的用户消息，便于重试
        except RuntimeError as e:
            print(f"\n[API 错误] {e}\n", file=sys.stderr)
            messages.pop()


if __name__ == "__main__":
    main()
