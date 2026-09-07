"""终端 UI：启动面板、彩色输出、工具调用格式化。基于 rich 库。"""
from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

_VERSION = "0.1.0"

_CRAB_ART = r"""
       __       __
      / <`     '> \
     (  / @   @ \  )
      \(_ _\_/_ _)/
    (\ `-/     \-' /)
     "===\     /==="
      .==')___(`==.
     ' .='     `=."""

_TAGLINE = "your tiny coding claw"


def print_banner(model: str, workspace: str) -> None:
    """打印启动面板：螃蟹 logo + 项目信息 + 快捷命令/快捷键。"""
    crab = Text(_CRAB_ART.lstrip("\n"), style="bold red")
    crab.append(f"\n\n  MiniClaw ", style="bold cyan")
    crab.append(f"v{_VERSION}", style="dim")
    crab.append(f"\n  {_TAGLINE}", style="italic dim")
    crab.append(f"\n\n  Model  ", style="dim")
    crab.append(model, style="bold")
    crab.append(f"\n  工作区 ", style="dim")
    workspace_display = workspace.replace("/Users/" + workspace.split("/Users/")[-1].split("/")[0], "~") if "/Users/" in workspace else workspace
    crab.append(workspace_display, style="bold")

    right_lines = Text()
    right_lines.append("快捷命令\n", style="bold")
    commands = [
        ("/plan ", "进入规划模式"),
        ("/todo ", "查看任务清单"),
        ("/clear", "清空对话历史"),
        ("/model", "查看当前模型"),
        ("/quit ", "退出"),
    ]
    for cmd, desc in commands:
        right_lines.append(f"  {cmd}", style="green")
        right_lines.append(f"  {desc}\n", style="dim")
    right_lines.append("\n快捷键\n", style="bold")
    keys = [
        ("Ctrl+J", "换行"),
        ("↑ / ↓ ", "历史记录"),
        ("Ctrl+C", "取消输入"),
        ("Ctrl+D", "退出"),
    ]
    for key, desc in keys:
        right_lines.append(f"  {key}", style="yellow")
        right_lines.append(f"  {desc}\n", style="dim")

    grid = Table.grid(padding=(0, 4))
    grid.add_column(justify="center", min_width=30)
    grid.add_column(justify="left")
    grid.add_row(crab, right_lines)

    panel = Panel(
        grid,
        title=f"[bold cyan]MiniClaw[/bold cyan] v{_VERSION}",
        border_style="cyan",
        expand=False,
        padding=(1, 2),
    )
    console.print(panel)


def print_tool_call(name: str, detail: str, *, indent: int = 0) -> None:
    """打印工具调用摘要。indent>0 时用于嵌套 sub-agent 输出。"""
    pad = "  " * (1 + max(indent, 0))
    console.print(f"{pad}[bold cyan]◆ {name}[/bold cyan] [dim]{detail}[/dim]")


_TODO_STYLES = {
    "pending": "white",
    "in_progress": "bold yellow",
    "completed": "dim green",
    "cancelled": "dim strike",
}


def print_todos(todos: list[dict], *, indent: int = 0) -> None:
    """打印任务列表面板，让用户看到 AI 当前的计划与进度。

    indent>0 表示这是 sub-agent 自己的清单（与主 agent 相互隔离），
    缩进并改标题以免与主 agent 的清单混淆。
    """
    from miniclaw.tools.todo_write import status_icon

    level = max(indent, 0)
    pad_width = 2 * (1 + level)
    if not todos:
        console.print(f"{' ' * pad_width}[dim]（任务列表已清空）[/dim]")
        return

    body = Text()
    done = 0
    for i, t in enumerate(todos):
        status = str(t.get("status", "pending"))
        if status in ("completed", "cancelled"):
            done += 1
        if i:
            body.append("\n")
        style = _TODO_STYLES.get(status, "white")
        body.append(f"{status_icon(status)} ", style=style)
        body.append(str(t.get("content", f"任务 {i + 1}")), style=style)

    label = "子任务清单" if level else "任务清单"
    color = "magenta" if level else "cyan"
    panel = Panel(
        body,
        title=f"[bold {color}]{label}[/bold {color}] [dim]{done}/{len(todos)}[/dim]",
        border_style=color,
        expand=False,
        padding=(0, 1),
    )
    console.print(Padding(panel, (0, 0, 0, pad_width)))


def print_agent_start(agent_type: str, description: str, *, depth: int = 1) -> None:
    """打印 sub-agent 开始行。"""
    pad = "  " * max(depth, 1)
    console.print(
        f"{pad}[bold magenta]↳ Agent[{agent_type}][/bold magenta] [dim]{description}[/dim]"
    )


def print_agent_done(
    agent_type: str,
    *,
    status: str,
    duration_ms: int,
    tool_use_count: int,
    depth: int = 1,
) -> None:
    """打印 sub-agent 结束行。"""
    pad = "  " * max(depth, 1)
    secs = duration_ms / 1000.0
    console.print(
        f"{pad}[bold magenta]← Agent[{agent_type}] {status}[/bold magenta] "
        f"[dim]({secs:.1f}s, {tool_use_count} tools)[/dim]"
    )


def print_error(label: str, message: str) -> None:
    """打印错误信息。"""
    console.print(f"\n  [bold red]✗ {label}[/bold red] {message}\n", highlight=False)


def print_status(message: str) -> None:
    """打印状态/操作反馈信息。"""
    console.print(f"  [dim]{message}[/dim]")


def print_compact_progress(phase: str) -> None:
    """Print context compaction progress (start / done / failed)."""
    console.print()
    if phase == "start":
        console.print("  [dim]正在压缩对话上下文…[/dim]")
    elif phase == "done":
        console.print("  [dim]上下文已压缩，继续对话[/dim]")
    elif phase == "failed":
        console.print("  [dim]上下文压缩失败，将使用完整历史继续[/dim]")
    console.print()
