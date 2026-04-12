"""终端 UI：启动面板、彩色输出、工具调用格式化。基于 rich 库。"""
from rich.console import Console
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


def print_tool_call(name: str, detail: str) -> None:
    """打印工具调用摘要。"""
    console.print(f"  [bold cyan]◆ {name}[/bold cyan] [dim]{detail}[/dim]")


def print_error(label: str, message: str) -> None:
    """打印错误信息。"""
    console.print(f"\n  [bold red]✗ {label}[/bold red] {message}\n", highlight=False)


def print_status(message: str) -> None:
    """打印状态/操作反馈信息。"""
    console.print(f"  [dim]{message}[/dim]")
