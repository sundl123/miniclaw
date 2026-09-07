"""todo_write tool: 创建/更新任务列表，支持 merge 模式追踪进度。

任务列表存活于会话 context（内存），与对话生命周期对齐：`/clear` 会一并清空，
进程退出即消失。历史留痕由 session records 负责，这里不再维护平行的落盘真值。
"""
from __future__ import annotations

import json

TODOS_CONTEXT_KEY = "todos"

VALID_STATUSES = ("pending", "in_progress", "completed", "cancelled")

_STATUS_ICONS = {
    "pending": "○",
    "in_progress": "◐",
    "completed": "●",
    "cancelled": "✕",
}


def get_todos(context: dict | None) -> list[dict]:
    """读取当前任务列表；context 缺失或数据异常时返回空列表。"""
    if not isinstance(context, dict):
        return []
    todos = context.get(TODOS_CONTEXT_KEY)
    if isinstance(todos, list):
        return todos
    return []


def _set_todos(context: dict | None, todos: list[dict]) -> None:
    """写回任务列表。"""
    if isinstance(context, dict):
        context[TODOS_CONTEXT_KEY] = todos


def status_icon(status: str) -> str:
    """状态图标，供 UI 层复用。"""
    return _STATUS_ICONS.get(status, "?")


def _normalize(todos_input: list) -> list[dict]:
    """校验并标准化输入条目，丢弃无 content 的项。"""
    normalized: list[dict] = []
    for i, t in enumerate(todos_input):
        if not isinstance(t, dict):
            continue
        content = str(t.get("content", "")).strip()
        if not content:
            continue
        status = t.get("status", "pending")
        if status not in VALID_STATUSES:
            status = "pending"
        entry: dict = {"content": content, "status": status}
        tid = t.get("id")
        if tid is not None:
            entry["id"] = tid
        normalized.append(entry)
    return normalized


def _merge_todos(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """以 existing 的顺序为基准原地更新，未命中的新项追加到末尾。

    匹配优先用 id，其次退化为 content 相同（模型常常省略 id），
    避免同一任务被反复追加成重复条目。
    """
    merged: list[dict] = [dict(e) for e in existing]
    idx_by_id: dict = {}
    idx_by_content: dict = {}
    for i, e in enumerate(merged):
        tid = e.get("id")
        if tid is not None:
            idx_by_id.setdefault(tid, i)
        idx_by_content.setdefault(e.get("content"), i)

    for item in incoming:
        tid = item.get("id")
        target = idx_by_id.get(tid) if tid is not None else None
        if target is None:
            target = idx_by_content.get(item.get("content"))
        if target is not None:
            merged[target].update(item)
            continue
        merged.append(item)
        pos = len(merged) - 1
        if tid is not None:
            idx_by_id.setdefault(tid, pos)
        idx_by_content.setdefault(item.get("content"), pos)

    return merged


def format_todos(todos: list[dict]) -> str:
    """将任务列表格式化为可读文本（模型侧结果与测试断言共用）。"""
    if not todos:
        return "（暂无任务）"
    lines = []
    for i, t in enumerate(todos):
        status = t.get("status", "pending")
        content = t.get("content", f"任务 {i + 1}")
        lines.append(f"{status_icon(status)} [{status}] {content}")
    return "\n".join(lines)


# 兼容旧的私有名
_format_todos = format_todos


def handle_todo_write(
    args: dict,
    workspace_root: str = "",
    tools_cfg=None,
    context: dict | None = None,
) -> str:
    """创建/更新任务列表。

    args:
        todos: list of {content, status, id?}  — 任务列表
        merge: bool — 是否合并到现有任务（默认 false=替换）

    status 取值: pending, in_progress, completed, cancelled

    context 为会话状态字典，任务列表存放于 context["todos"]。未提供 context 时
    本次调用是无状态的（merge 视作空基准），仅用于单次调用场景。
    """
    todos_input = args.get("todos", [])
    merge = bool(args.get("merge", False))

    if not isinstance(todos_input, list):
        return json.dumps({"error": "todos 必须是数组"}, ensure_ascii=False)

    normalized = _normalize(todos_input)

    if merge:
        result = _merge_todos(get_todos(context), normalized)
        prefix = "任务列表已合并更新"
    else:
        result = normalized
        prefix = "任务列表已更新"

    _set_todos(context, result)
    return f"{prefix}（共 {len(result)} 条）：\n{format_todos(result)}"
