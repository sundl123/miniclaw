"""ask_followup_question tool: 模型向用户提问澄清需求。"""
from __future__ import annotations

import json

from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML
from rich.panel import Panel
from rich.text import Text

from miniclaw.ui import console

_PROMPT_MARKER = HTML(" <style fg='ansigreen'>❯</style> ")


def _option_label(opt: dict | str, idx: int) -> str:
    """取选项标题。"""
    if isinstance(opt, dict):
        return str(opt.get("label", f"选项 {idx + 1}"))
    return str(opt)


def _option_desc(opt: dict | str) -> str:
    """取选项说明（仅 dict 形式有）。"""
    if isinstance(opt, dict):
        return str(opt.get("description", ""))
    return ""


def _render_question(
    header: str,
    question: str,
    options: list | None,
    multi_select: bool,
) -> None:
    """把问题与选项渲染到终端。

    用 rich.Text 逐段追加而非 markup 字符串，避免 question/label 中的
    `[`、`<` 被当作标记解析。
    """
    body = Text()
    body.append(question, style="bold cyan")

    if options:
        for i, opt in enumerate(options):
            body.append(f"\n  {i + 1}. ", style="bold green")
            body.append(_option_label(opt, i))
            desc = _option_desc(opt)
            if desc:
                body.append(f" — {desc}", style="dim")
        hint = (
            "输入序号（多选，逗号分隔，如 1,3）"
            if multi_select
            else "输入序号"
        )
        body.append(f"\n\n{hint}，也可直接输入自由文本", style="dim")
    else:
        body.append("\n\n请直接输入你的回答", style="dim")

    console.print()
    console.print(
        Panel(
            body,
            title=f"[bold yellow]{header}[/bold yellow]" if header else "[bold yellow]需要你确认[/bold yellow]",
            border_style="yellow",
            expand=False,
            padding=(0, 1),
        )
    )


def _resolve_selection(
    user_input: str,
    options: list,
    multi_select: bool,
) -> list[str]:
    """把用户输入的序号解析为选项标题；无法解析时返回空列表。"""
    raw = user_input.strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")] if multi_select else [raw]
    labels: list[str] = []
    for part in parts:
        if not part.isdigit():
            return []
        idx = int(part) - 1
        if idx < 0 or idx >= len(options):
            return []
        labels.append(_option_label(options[idx], idx))
    return labels


def handle_ask(
    args: dict,
    workspace_root: str,
    tools_cfg=None,
) -> str:
    """向用户展示问题并收集回答。

    args:
        question: str — 问题文本（必填）
        header: str — 可选标题
        options: list — 可选选项列表（每项可以是 string 或 {label, description}）
        multi_select: bool — 是否允许多选（默认 false）
    """
    question = str(args.get("question", "")).strip()
    if not question:
        return json.dumps({"error": "ask_followup_question 需要 question 参数"}, ensure_ascii=False)

    header = str(args.get("header", "")).strip()
    options = args.get("options")
    if options is not None and not isinstance(options, list):
        return json.dumps({"error": "options 必须是数组"}, ensure_ascii=False)
    multi_select = bool(args.get("multi_select", False))

    _render_question(header, question, options, multi_select)

    try:
        user_input = prompt(_PROMPT_MARKER, multiline=False)
    except (EOFError, KeyboardInterrupt):
        return json.dumps(
            {"error": "用户取消了本次提问", "question": question},
            ensure_ascii=False,
        )

    answer = user_input.strip()
    payload: dict = {"answer": answer, "question": question}
    if options:
        selected = _resolve_selection(answer, options, multi_select)
        if selected:
            payload["selected"] = selected
    return json.dumps(payload, ensure_ascii=False)
