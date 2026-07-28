"""bash tool handler."""
from __future__ import annotations

import json
import subprocess

from miniclaw.tools.config import ToolsConfig


def handle_bash(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """在工作区内执行 bash 命令。"""
    cmd = args.get("command") or ""
    if not cmd:
        return json.dumps({"error": "bash 需要 command 参数"}, ensure_ascii=False)
    r = subprocess.run(
        ["bash", "-c", cmd],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        return f"exit code: {r.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    return out or "(无输出)"
