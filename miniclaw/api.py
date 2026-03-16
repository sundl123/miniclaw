"""MiniMax API 调用：认证、chat、chat_raw、带 tool 的对话循环。"""
import json
import os
import sys

import requests

from miniclaw.config import CHAT_URL, CHAT_URL_OPENAI, DEFAULT_MODEL
from miniclaw.code_execution import handle_code_execution


def get_api_key() -> str:
    """从环境变量读取 MINIMAX_API_KEY，缺失时打印说明并退出。"""
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        print("错误: 请设置环境变量 MINIMAX_API_KEY", file=sys.stderr)
        print("示例: export MINIMAX_API_KEY=your_api_key", file=sys.stderr)
        sys.exit(1)
    return key


def chat_raw(api_key: str, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> tuple[dict, dict]:
    """调用 MiniMax 对话 API，返回完整 message 与整份 data（含 tool_calls、reasoning_details）。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        **kwargs,
    }
    use_tools = bool(kwargs.get("tools"))
    url = CHAT_URL_OPENAI if use_tools else CHAT_URL
    if use_tools and "extra_body" not in kwargs:
        payload["extra_body"] = {"reasoning_split": True}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        msg = base.get("status_msg", "Unknown error")
        raise RuntimeError(f"MiniMax API 错误: {msg} (code={base.get('status_code')})")

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("API 返回无内容")

    message = choices[0].get("message", {})
    return message, data


def chat(api_key: str, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> str:
    """调用 MiniMax 对话 API，返回助手回复文本（无 tool 时）。"""
    msg, _ = chat_raw(api_key, messages, model=model, **kwargs)
    return (msg.get("content") or "").strip()


def _execute_tool_call(tc: dict) -> str:
    """解析单条 tool_call 并执行，返回结果字符串。"""
    fn = tc.get("function") or {}
    name = fn.get("name", "")
    args_str = fn.get("arguments", "{}")
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError:
        args = {}
    if name == "code_execution":
        return handle_code_execution(args)
    return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)


def run_turn_with_tools(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    *,
    print_reasoning: bool = True,
) -> tuple[str, list[dict]]:
    """带 tool 的对话循环：请求 → 若有 tool_calls 则执行并追加消息 → 再请求，直到无 tool_calls。"""
    while True:
        message, _ = chat_raw(api_key, messages, model=model, tools=tools, tool_choice="auto")
        reasoning_details = message.get("reasoning_details") or []
        if print_reasoning and reasoning_details:
            for d in reasoning_details:
                if isinstance(d, dict) and d.get("text"):
                    print(f"\n💭 Thinking:\n{d['text']}\n")
        tool_calls = message.get("tool_calls") or []

        assistant_msg = {"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls}
        if message.get("reasoning_details"):
            assistant_msg["reasoning_details"] = message["reasoning_details"]
        messages.append(assistant_msg)

        if not tool_calls:
            return (message.get("content") or "").strip(), messages

        for tc in tool_calls:
            tid = tc.get("id") or tc.get("tool_use_id")
            result = _execute_tool_call(tc)
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})
