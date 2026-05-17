---
name: CC-style compact timing
overview: 将 miniclaw 的 auto-summarize 从「整轮 turn 结束后再执行」改为 Claude Code 风格：在上一轮 API（及 tool 结果）之后、下一次 chat_stream 之前立即执行；并在压缩期间向终端输出明确状态，避免用户以为卡住。
todos:
  - id: manage-immediate-summarize
    content: 重构 manage.py：manage_messages 内立即 auto-summarize，抽取 _try_auto_summarize，移除 end_of_turn 自动路径
    status: completed
  - id: api-loop-wire
    content: 更新 api.py run_turn_with_tools：传 client/model/timeout/on_compact_progress，删除 end_of_turn 调用
    status: completed
  - id: ui-progress
    content: ui.py 增加 print_compact_progress；cli.py 与 manual_compact 接线
    status: completed
  - id: summarize-hardening
    content: summarize.py：解析前 strip thinking/analysis，无闭合 </summary> 时不回退 raw
    status: completed
  - id: tests
    content: 更新 test_summarize / test_api，覆盖循环内 compact 与 progress 回调
    status: completed
isProject: false
---

# Claude Code 风格 Compact 时机与进度提示

## 现状 vs 目标

```mermaid
sequenceDiagram
    participant User
    participant Loop as run_turn_with_tools
    participant Mgmt as manage_messages
    participant API as chat_stream
    participant Sum as summarize

    Note over Loop,Sum: 当前 miniclaw
    Loop->>Mgmt: 每轮前：micro_compact + 仅设 pending
    Loop->>API: 请求
    API-->>Loop: assistant + tools
    Loop->>Loop: 执行 tools，继续循环
    Loop->>Sum: turn 结束且无 tool 时才 summarize

    Note over Loop,Sum: 目标（Claude Code 对齐）
    Loop->>Mgmt: 每轮前：micro_compact
  alt tokens >= threshold
        Mgmt->>Sum: 立即 summarize（带 UI 提示）
        Sum-->>Mgmt: 新 messages
    end
    Loop->>API: 请求
```

Claude Code 的准确语义是：**在 `queryLoop` 每一轮迭代开头**（即上一轮 `chat_stream` + tool 结果已写入 messages 之后），若超阈值则 **同步** 跑 `compactConversation`，再发下一次主 API。不是「用户看到最终回复之后」才压。

你已确认：**tool 循环中间超阈值也要 compact**（与 CC 一致）。

---

## 核心改动

### 1. 合并「pending」为「立即执行」— [`miniclaw/context/manage.py`](miniclaw/context/manage.py)

- 在 `manage_messages()` 中，当满足 auto-summarize 条件时，**直接调用** `summarize_conversation()`（复用现有 `compacting` 防重入、`consecutive_summarize_failures` 熔断逻辑），不再只设置 `pending_summarize`。
- 抽取内部函数 `_try_auto_summarize(client, model, messages, cfg, context, *, timeout, on_progress)`，供 `manage_messages` 与 `manual_compact` 共用。
- **删除或废弃** `manage_messages_end_of_turn()` 在 auto 路径上的职责；[`miniclaw/api.py`](miniclaw/api.py) 中 `run_turn_with_tools` 在 `if not tool_calls` 分支里不再调用它。
- `manage_messages` 需要 `client` / `model` / `timeout`：扩展签名，由 `run_turn_with_tools` 传入（与 `manual_compact` 一致）。
- 从 `_ctx_mgmt` 移除 `pending_summarize`（或保留只读兼容一版 `/context` 文案，显示「N/A」）；更新 [`format_context_status`](miniclaw/context/manage.py) 为 `Last compact: …` 或 `Compacting: yes`。

### 2. 调整 API 循环 — [`miniclaw/api.py`](miniclaw/api.py)

当前循环（简化）：

```316:340:miniclaw/api.py
    while True:
        if cfg is not None:
            messages = manage_messages(messages, cfg, context)
        message, usage = chat_stream(...)
        ...
        if not tool_calls:
            messages = manage_messages_end_of_turn(...)  # 删除
            return ...
        ... execute tools ...
```

改为：

```python
while True:
    if cfg is not None:
        messages = manage_messages(
            client, model, messages, cfg, context, timeout=timeout,
            on_compact_progress=on_compact_progress,
        )
    message, usage = chat_stream(...)
    ...
    if not tool_calls:
        return (content, messages)
    ... execute tools ...
```

- `run_turn_with_tools` 增加可选参数 `on_compact_progress: Callable[[str], None] | None = None`，默认在 CLI 场景由上层注入打印函数。

### 3. 压缩进度 UI — [`miniclaw/ui.py`](miniclaw/ui.py) + 接线

新增轻量 API（基于已有 `rich`）：

- `print_compact_progress(phase: str)` — 例如：
  - `start`: `正在压缩对话上下文…`（可用 `rich.status` spinner，或 `print_status` + 单行提示）
  - `done`: `上下文已压缩，继续对话`
  - `failed`: `上下文压缩失败，将使用完整历史继续`

在 `_try_auto_summarize` / `manual_compact` 中：

1. `on_progress("start")` → 调用 summarize 前
2. `summarize_conversation` 执行（阻塞，无流式）
3. `on_progress("done"|"failed")` → 根据 `ok` 回调

**注意**：compact 期间应 `flush` 输出，且不要与 `_StreamPrinter` 的 `[思考中...]` 混在同一行；在 `print_compact_progress` 里先换行再打印（与 `print_tool_call` 一致）。

CLI 接线 — [`miniclaw/cli.py`](miniclaw/cli.py)：

- 将 `print_compact_progress` 传给 `run_turn_with_tools`。
- `/compact` 手动路径在 `manual_compact` 前同样打印 `start/done`。

### 4. Summarize 解析加固 — [`miniclaw/context/summarize.py`](miniclaw/context/summarize.py)

与 compact 时机同 PR 做（`194317` 日志：1024 顶满 + thinking 写在 `content` 里导致半截 summary）。

**配置（用户自行调整）**

- 将 `context.summarize.max_summary_output_tokens` 设为 **4096**（默认已是 4096；若 workspace 里曾改成 1024 需改回）。
- Summarize 的 `chat_raw` **仍不传** `reasoning_split`（与主对话区分）；`max_tokens` 限制的是整段 completion（含写在 content 里的 XML 块）。

**解析流水线（先 strip，再 parse）**

在 `summarize_conversation` 拿到 `raw` 后：

```text
raw (content)
  → _strip_non_summary_blocks(raw)   # 新增
  → _parse_summary(cleaned)          # 改行为
  → _is_valid_summary(summary)
```

`_strip_non_summary_blocks` 建议去掉（大小写不敏感、DOTALL）：

- `<think>...</think>`
- `<thinking>...</thinking>`（若模型换标签）
- `<analysis>...</analysis>`（对齐 Claude Code：analysis 为草稿，不进入 boundary）

**`_parse_summary` 新行为**

1. 若有完整 `<summary>...</summary>` → 取中间正文（与现逻辑相同）。
2. 若有 `<summary>` 但无 `</summary>`（截断）→ 取 `<summary>` 之后到文末作为弱解析结果（比整段 raw 安全）。
3. 若无 `<summary>` → 返回 `None`（**禁止** `return text.strip()` 回退整段 raw）。
4. `_is_valid_summary` 补充：若仍含 `redacted_thinking` / `<analysis>` 等标记 → 拒绝。

**`reasoning_details`**

- Summarize 请求当前不读 `msg["reasoning_details"]`；若未来 API 返回，可在 strip 前把 `reasoning_details[].text` 拼进待清洗文本，或显式忽略（不进 boundary）。本次以 **content strip** 为主即可。

不纳入本次：瘦 placeholder、summarize 开 `reasoning_split`。

---

## 行为变化说明（给用户）

| 场景 | 之前 | 之后 |
|------|------|------|
| 长 tool 循环中途超阈值 | 继续涨 context，turn 末尾才 summarize | **下一轮 API 前** summarize，终端有提示 |
| 用户看到最终回复前 | 可能先卡 10–30s summarize | 卡在 **tool 与下一条回复之间**，有「正在压缩…」 |
| `/compact` | 无提示 | 同样有 start/done |

---

## 测试更新

| 文件 | 改动 |
|------|------|
| [`tests/test_summarize.py`](tests/test_summarize.py) | `TestManagePending` 改为断言 **立即** summarize（mock `summarize_conversation`），不再断言 `pending_summarize` |
| [`tests/test_api.py`](tests/test_api.py) | 多轮 tool mock：超阈值时在第 2 次 `chat_stream` 前触发 summarize；验证 `manage_messages_end_of_turn` 不再被调用 |
| 新增或扩展 | `manage_messages` 在 `compacting=True` 时跳过；`on_compact_progress` 被调用顺序 |

运行：`/usr/bin/python3 -m unittest discover -s tests`

---

## 不在本次范围

- 异步/后台 compact（仍同步，与 CC 一致）
- Session Memory 路径（miniclaw 无）
- Reactive compact on 413（未实现）
- placeholder 瘦身、README 文档
