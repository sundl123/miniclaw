"""Format memory status for CLI display."""
from __future__ import annotations

from miniclaw.memory.store import MemoryStore


def format_memory_status(store: MemoryStore) -> str:
    data = store.status()
    disk = data["disk_memory_md_usage"]
    frozen = data["frozen_snapshot_usage"]
    trunc = data["truncation"]
    lines = [
        f"目录: {data['memory_dir']}",
        f"磁盘 MEMORY.md: {disk['display']}",
        f"Frozen 注入快照: {frozen['display']}",
    ]
    if trunc["truncated"]:
        lines.append(
            f"快照已截断 (磁盘 {trunc['total_bytes']:,} bytes / {trunc['total_lines']} lines → "
            f"注入 {trunc['shown_bytes']:,} bytes / {trunc['shown_lines']} lines)"
        )
    else:
        lines.append("快照: 完整注入（未截断）")
    if data.get("warning"):
        lines.append(f"⚠ {data['warning']}")
    return "\n".join(lines)
