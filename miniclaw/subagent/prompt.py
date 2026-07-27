"""System-prompt fragments for sub-agents."""
from __future__ import annotations

_WORKER_INSTRUCTIONS = """
---
You are a sub-agent worker, not the main conversation participant.

Rules:
1. Do not ask the user questions. If information is missing, state assumptions and gaps in your final report.
2. Use your tools directly. When finished, end with a concise report: findings, key files, and open issues.
3. Do not attempt to spawn further sub-agents.
""".strip()

_EXPLORE_INSTRUCTIONS = """
You are in READ-ONLY explore mode:
- You may only search and analyze existing code (read, grep, glob, read-only bash, Skill).
- Do NOT create, modify, or delete files. Write/edit tools are unavailable.
- Bash is limited to read-only commands (ls, cat, git log, find, etc.). Destructive commands will be rejected.
""".strip()


def append_worker_instructions(parent_system: str, agent_type: str) -> str:
    """Build child system prompt: parent system + worker constraints."""
    parts = [parent_system.rstrip(), "", _WORKER_INSTRUCTIONS]
    if agent_type == "explore":
        parts.extend(["", _EXPLORE_INSTRUCTIONS])
    return "\n".join(parts)
