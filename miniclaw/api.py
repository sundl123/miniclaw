"""MiniMax API 调用：认证、流式 chat、带 tool 的对话循环、TTFT 与缓存指标监控。"""
import json
import os
import sys
import time

from openai import OpenAI

from miniclaw.config import DEFAULT_MODEL, HTTP_TIMEOUT, OPENAI_BASE_URL
from miniclaw.tools import execute_tool
from miniclaw.dev_logging import get_dev_logger


# ---------------------------------------------------------------------------
# 认证与客户端
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """从环境变量读取 MINIMAX_API_KEY，缺失时打印说明并退出。"""
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        print("错误: 请设置环境变量 MINIMAX_API_KEY", file=sys.stderr)
        print("示例: export MINIMAX_API_KEY=your_api_key", file=sys.stderr)
        sys.exit(1)
    return key


def create_client(api_key: str) -> OpenAI:
    """创建 MiniMax OpenAI 兼容客户端。"""
    return OpenAI(base_url=OPENAI_BASE_URL, api_key=api_key)


# ---------------------------------------------------------------------------
# 日志辅助
# ---------------------------------------------------------------------------

def _log_request(messages: list[dict], model: str, kwargs: dict) -> None:
    """记录请求参数到 dev log（含完整 messages 用于排查）。"""
    log_payload = {"base_url": OPENAI_BASE_URL, "model": model, "messages": messages}
    log_payload.update({k: v for k, v in kwargs.items()})
    try:
        text = json.dumps(log_payload, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        text = repr(log_payload)
    get_dev_logger().info("chat request\n%s", text)


def _log_cache_metrics(usage) -> None:
    """从 usage 中提取缓存指标并记录到 dev log。"""
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    ratio = (cached / prompt_tokens * 100) if prompt_tokens > 0 else 0.0
    get_dev_logger().info(
        "Cache metrics: prompt_tokens=%d, cached_tokens=%d, "
        "cache_hit_ratio=%.2f%%, completion_tokens=%d",
        prompt_tokens, cached, ratio, completion_tokens,
    )


# ---------------------------------------------------------------------------
# 流式请求
# ---------------------------------------------------------------------------

def _accumulate_tool_call_delta(acc: dict, tc_delta) -> None:
    """将单个 streaming tool_call delta 累加到 acc[index] 中。"""
    idx = tc_delta.index
    if idx not in acc:
        acc[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
    if tc_delta.id:
        acc[idx]["id"] = tc_delta.id
    fn = tc_delta.function
    if fn:
        if fn.name:
            acc[idx]["function"]["name"] = fn.name
        if fn.arguments:
            acc[idx]["function"]["arguments"] += fn.arguments


def chat_stream(
    client: OpenAI,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    *,
    print_output: bool = True,
    **kwargs,
) -> tuple[dict, object]:
    """流式调用 MiniMax API，逐 token 输出文本，测量 TTFT，返回 (message_dict, usage)。"""
    _log_request(messages, model, kwargs)

    start = time.monotonic()
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        timeout=HTTP_TIMEOUT,
        **kwargs,
    )

    content_parts: list[str] = []
    tool_calls_acc: dict[int, dict] = {}
    usage = None
    ttft_logged = False

    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        if delta.content:
            if not ttft_logged:
                ttft = time.monotonic() - start
                get_dev_logger().info("TTFT: %.3fs", ttft)
                ttft_logged = True
            content_parts.append(delta.content)
            if print_output:
                print(delta.content, end="", flush=True)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                _accumulate_tool_call_delta(tool_calls_acc, tc_delta)

    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] if tool_calls_acc else []
    content = "".join(content_parts)
    message: dict = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls

    if usage:
        _log_cache_metrics(usage)

    return message, usage


# ---------------------------------------------------------------------------
# 非流式请求（供简单场景和测试使用）
# ---------------------------------------------------------------------------

def chat_raw(
    client: OpenAI, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs
) -> tuple[dict, dict]:
    """非流式调用 MiniMax API，返回 (message_dict, response_data)。"""
    _log_request(messages, model, kwargs)
    resp = client.chat.completions.create(
        model=model, messages=messages, timeout=HTTP_TIMEOUT, **kwargs,
    )
    msg = resp.choices[0].message
    msg_dict: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        msg_dict["tool_calls"] = [
            {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    if resp.usage:
        _log_cache_metrics(resp.usage)
    return msg_dict, resp.model_dump()


def chat(client: OpenAI, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> str:
    """非流式调用 MiniMax API，返回助手回复文本。"""
    msg, _ = chat_raw(client, messages, model=model, **kwargs)
    return (msg.get("content") or "").strip()


# ---------------------------------------------------------------------------
# Tool 执行
# ---------------------------------------------------------------------------

def _execute_tool_call(tc: dict, *, workspace_root: str = None) -> str:
    """解析单条 tool_call 并执行，返回结果字符串。"""
    fn = tc.get("function") or {}
    name = fn.get("name", "")
    args_str = fn.get("arguments", "{}")
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError:
        args = {}
    return execute_tool(name, args, workspace_root=workspace_root)


# ---------------------------------------------------------------------------
# 带 tool 的对话循环
# ---------------------------------------------------------------------------

def run_turn_with_tools(
    client: OpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict],
    *,
    print_reasoning: bool = True,
    workspace_root: str = None,
) -> tuple[str, list[dict]]:
    """带 tool 的对话循环：流式请求 → 若有 tool_calls 则执行并追加消息 → 再请求，直到无 tool_calls。"""
    while True:
        message, _ = chat_stream(
            client, messages, model=model,
            tools=tools, tool_choice="auto",
            print_output=True,
            extra_body={"reasoning_split": True},
        )

        tool_calls = message.get("tool_calls") or []
        messages.append(message)

        if not tool_calls:
            return (message.get("content") or "").strip(), messages

        if message.get("content"):
            print()

        for tc in tool_calls:
            tid = tc.get("id") or tc.get("tool_use_id")
            result = _execute_tool_call(tc, workspace_root=workspace_root)
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})
