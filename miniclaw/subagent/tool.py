"""Agent tool schema and handler."""
from __future__ import annotations

import json

from miniclaw.subagent.runner import run_subagent
from miniclaw.subagent.types import AGENT_TOOL_NAME


def get_agent_tool_schema() -> dict:
    """OpenAI function-calling schema for the Agent tool."""
    return {
        "type": "function",
        "function": {
            "name": AGENT_TOOL_NAME,
            "description": (
                "Spawn a synchronous sub-agent with an isolated context. "
                "The sub-agent does not see this conversation — provide a complete briefing "
                "in `prompt`. Use subagent_type='explore' for read-only codebase research "
                "(avoids polluting the main context). Use 'general' for isolated tasks that "
                "may edit files. Returns only the sub-agent's final report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short (3-10 word) label for the task (UI / logs)",
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Full task briefing for the sub-agent. Include all context "
                            "it needs; it cannot see the parent conversation."
                        ),
                    },
                    "subagent_type": {
                        "type": "string",
                        "enum": ["general", "explore"],
                        "description": (
                            "Agent type. 'explore' is read-only research; "
                            "'general' may use write/edit. Defaults to general."
                        ),
                    },
                },
                "required": ["description", "prompt"],
            },
        },
    }


def handle_agent(
    args: dict,
    workspace_root: str,
    context: dict | None = None,
) -> str:
    """Dispatch Agent tool call to the sync sub-agent runner."""
    ctx = context or {}
    description = (args.get("description") or "").strip()
    prompt = args.get("prompt") or ""
    if not description:
        return json.dumps({"error": "Agent 需要 description 参数"}, ensure_ascii=False)
    if not str(prompt).strip():
        return json.dumps({"error": "Agent 需要 prompt 参数"}, ensure_ascii=False)

    return run_subagent(
        description=description,
        prompt=str(prompt),
        subagent_type=args.get("subagent_type"),
        workspace_root=workspace_root,
        context=ctx,
    )
