"""LLM API 调用：流式 chat、带 tool 的对话循环、TTFT 与缓存指标监控。"""
import json
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Optional

from openai import OpenAI

from miniclaw.config import DEFAULT_BASE_URL, DEFAULT_HTTP_TIMEOUT, DEFAULT_MODEL
from miniclaw.context import (
    manage_messages,
    record_usage,
    init_ctx_mgmt,
)
from miniclaw.context.config import ContextConfig
from miniclaw.tools import execute_tool
from miniclaw.dev_logging import get_dev_logger


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

def create_client(api_key: str, base_url: str = DEFAULT_BASE_URL) -> OpenAI:
    """创建 OpenAI 兼容客户端。"""
    return OpenAI(base_url=base_url, api_key=api_key)


# ---------------------------------------------------------------------------
# 日志辅助
# ---------------------------------------------------------------------------

def _log_request(messages: list[dict], model: str, kwargs: dict,
                  base_url: str = "") -> None:
    """记录请求参数到 dev log（含完整 messages 用于排查）。"""
    log_payload = {"base_url": base_url, "model": model, "messages": messages}
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
    cached = (getattr(details, "cached_tokens", 0) if details else 0) or 0
    ratio = (cached / prompt_tokens * 100) if prompt_tokens > 0 else 0.0
    get_dev_logger().info(
        "Cache metrics: prompt_tokens=%d, cached_tokens=%d, "
        "cache_hit_ratio=%.2f%%, completion_tokens=%d",
        prompt_tokens, cached, ratio, completion_tokens,
    )


# ---------------------------------------------------------------------------
# 流式请求
# ---------------------------------------------------------------------------

def _get_field(obj, key, default=None):
    """从 dict 或 SDK 对象中安全提取字段值。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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


def _accumulate_reasoning_delta(acc: dict, rd_list) -> None:
    """将 streaming reasoning_details chunk 逐条累加到 acc[index] 中。"""
    for item in rd_list:
        idx = _get_field(item, "index", 0) or 0
        if idx not in acc:
            acc[idx] = {
                "type": _get_field(item, "type") or "reasoning.text",
                "id": _get_field(item, "id") or "",
                "format": _get_field(item, "format") or "",
                "index": idx,
                "text": "",
            }
        text = _get_field(item, "text") or ""
        if text:
            acc[idx]["text"] += text


@dataclass
class _StreamResult:
    """流式响应的累积结果。"""
    content_parts: list[str] = field(default_factory=list)
    tool_calls_acc: dict[int, dict] = field(default_factory=dict)
    reasoning_acc: dict[int, dict] = field(default_factory=dict)
    usage: object = None
    ttft: Optional[float] = None
    ttfc: Optional[float] = None


class _StreamPrinter:
    """处理流式输出的终端打印逻辑（前导换行过滤、thinking 提示管理）。"""

    _THINKING_HINT = "[思考中...]"
    _HINT_CLEAR_WIDTH = 20

    def __init__(self, *, enabled: bool = True, show_reasoning: bool = False):
        self._enabled = enabled
        self._show_reasoning = show_reasoning
        self._thinking_shown = False
        self._content_started = False

    def on_reasoning(self) -> None:
        if self._enabled and self._show_reasoning and not self._thinking_shown:
            self._thinking_shown = True
            print(self._THINKING_HINT, end="", flush=True)

    def on_content(self, text: str) -> None:
        if not self._enabled:
            return
        display = text
        if not self._content_started:
            display = display.lstrip("\n")
            if display:
                self._content_started = True
                if self._thinking_shown:
                    self._clear_hint()
        if display:
            print(display, end="", flush=True)

    def finish(self) -> None:
        if self._thinking_shown and not self._content_started and self._enabled:
            self._clear_hint()

    def _clear_hint(self) -> None:
        print("\r" + " " * self._HINT_CLEAR_WIDTH + "\r", end="", flush=True)


def _consume_stream(
    stream, printer: _StreamPrinter, start_time: float,
) -> _StreamResult:
    """消费流式响应，累积内容 / tool_calls / reasoning 并通过 printer 输出。"""
    result = _StreamResult()

    for chunk in stream:
        if chunk.usage:
            result.usage = chunk.usage

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        has_reasoning = hasattr(delta, "reasoning_details") and delta.reasoning_details

        if result.ttft is None and (delta.content or has_reasoning or delta.tool_calls):
            result.ttft = time.monotonic() - start_time

        if has_reasoning:
            _accumulate_reasoning_delta(result.reasoning_acc, delta.reasoning_details)
            printer.on_reasoning()

        if delta.content:
            if result.ttfc is None:
                result.ttfc = time.monotonic() - start_time
            result.content_parts.append(delta.content)
            printer.on_content(delta.content)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                _accumulate_tool_call_delta(result.tool_calls_acc, tc_delta)

    printer.finish()
    return result


def _build_message(result: _StreamResult) -> dict:
    """从累积的流式数据构建 assistant message dict。"""
    content = "".join(result.content_parts)
    message: dict = {"role": "assistant", "content": content or ""}
    if result.reasoning_acc:
        message["reasoning_details"] = [
            result.reasoning_acc[i] for i in sorted(result.reasoning_acc)
        ]
    if result.tool_calls_acc:
        message["tool_calls"] = [
            result.tool_calls_acc[i] for i in sorted(result.tool_calls_acc)
        ]
    return message


def chat_stream(
    client: OpenAI,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    *,
    print_output: bool = True,
    print_reasoning: bool = False,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
    **kwargs,
) -> tuple[dict, object]:
    """流式调用 LLM API，逐 token 输出文本，测量 TTFT，返回 (message_dict, usage)。"""
    _log_request(messages, model, kwargs, base_url=getattr(client, '_base_url', ''))

    start = time.monotonic()
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        timeout=timeout,
        **kwargs,
    )

    printer = _StreamPrinter(enabled=print_output, show_reasoning=print_reasoning)
    result = _consume_stream(stream, printer, start)
    message = _build_message(result)

    if result.ttft is not None:
        get_dev_logger().info("TTFT: %.3fs", result.ttft)
    if result.ttfc is not None:
        get_dev_logger().info("TTFC: %.3fs", result.ttfc)
    if result.usage:
        _log_cache_metrics(result.usage)

    return message, result.usage


# ---------------------------------------------------------------------------
# 非流式请求（供简单场景和测试使用）
# ---------------------------------------------------------------------------

def chat_raw(
    client: OpenAI, messages: list[dict], model: str = DEFAULT_MODEL,
    *, timeout: int = DEFAULT_HTTP_TIMEOUT, **kwargs,
) -> tuple[dict, dict]:
    """非流式调用 LLM API，返回 (message_dict, response_data)。"""
    _log_request(messages, model, kwargs, base_url=getattr(client, '_base_url', ''))
    resp = client.chat.completions.create(
        model=model, messages=messages, timeout=timeout, **kwargs,
    )
    msg = resp.choices[0].message
    msg_dict: dict = {"role": "assistant", "content": msg.content or ""}
    rd = getattr(msg, "reasoning_details", None)
    if rd:
        msg_dict["reasoning_details"] = rd
    if msg.tool_calls:
        msg_dict["tool_calls"] = [
            {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    if resp.usage:
        _log_cache_metrics(resp.usage)
    return msg_dict, resp.model_dump()


def chat(client: OpenAI, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> str:
    """非流式调用 LLM API，返回助手回复文本。"""
    msg, _ = chat_raw(client, messages, model=model, **kwargs)
    return (msg.get("content") or "").strip()


# ---------------------------------------------------------------------------
# Tool 执行
# ---------------------------------------------------------------------------

def _execute_tool_call(tc: dict, *, workspace_root: str = None,
                       context: dict = None) -> str:
    """解析单条 tool_call 并执行，返回结果字符串。"""
    fn = tc.get("function") or {}
    name = fn.get("name", "")
    args_str = fn.get("arguments", "{}")
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError:
        args = {}
    return execute_tool(name, args, workspace_root=workspace_root, context=context)


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
    timeout: int = DEFAULT_HTTP_TIMEOUT,
    workspace_root: str = None,
    context: dict = None,
    context_config: Optional[ContextConfig] = None,
    on_compact_progress: Optional[Callable[[str], None]] = None,
) -> tuple[str, list[dict]]:
    """带 tool 的对话循环：流式请求 → 若有 tool_calls 则执行并追加消息 → 再请求，直到无 tool_calls。

    context 承载 plan mode 状态，由 REPL 层创建并透传给 execute_tool。
    context_config 控制 micro-compaction 与 summarization。
    """
    init_ctx_mgmt(context)
    cfg = context_config

    while True:
        if cfg is not None:
            messages = manage_messages(
                client, model, messages, cfg, context,
                timeout=timeout,
                on_compact_progress=on_compact_progress,
            )

        message, usage = chat_stream(
            client, messages, model=model,
            tools=tools, tool_choice="auto",
            print_output=True,
            print_reasoning=print_reasoning,
            timeout=timeout,
            extra_body={"reasoning_split": True},
        )

        if cfg is not None:
            record_usage(context, usage)

        tool_calls = message.get("tool_calls") or []
        messages.append(message)

        if not tool_calls:
            return (message.get("content") or "").strip(), messages

        if (message.get("content") or "").strip():
            print()

        for tc in tool_calls:
            tid = tc.get("id") or tc.get("tool_use_id")
            result = _execute_tool_call(tc, workspace_root=workspace_root,
                                        context=context)
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})
