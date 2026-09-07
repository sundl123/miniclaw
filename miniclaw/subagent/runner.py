"""Run an isolated sub-agent tool loop and package the result."""
from __future__ import annotations

import json
import time
from typing import Any

from miniclaw.subagent.config import SubagentConfig
from miniclaw.subagent.prompt import append_worker_instructions
from miniclaw.subagent.types import (
    ALWAYS_DISALLOWED_TOOLS,
    EXPLORE_ALLOWED_TOOLS,
    AgentDefinition,
    resolve_agent_definition,
)
from miniclaw.tools.todo_write import TODOS_CONTEXT_KEY
from miniclaw.ui import print_agent_done, print_agent_start


def _tool_name(schema: dict) -> str:
    return ((schema.get("function") or {}).get("name") or "")


def filter_tools_for_agent(
    parent_tools: list[dict],
    definition: AgentDefinition,
) -> list[dict]:
    """Filter parent tool schemas for a sub-agent."""
    out: list[dict] = []
    for schema in parent_tools:
        name = _tool_name(schema)
        if not name or name in ALWAYS_DISALLOWED_TOOLS:
            continue
        if definition.readonly and name not in EXPLORE_ALLOWED_TOOLS:
            continue
        out.append(schema)
    return out


def build_child_context(
    parent_context: dict,
    *,
    definition: AgentDefinition,
) -> dict:
    """Shallow-copy parent context for the child loop; drop session writer."""
    child = dict(parent_context)
    child["agent_depth"] = int(parent_context.get("agent_depth") or 0) + 1
    child["readonly_bash_only"] = bool(definition.readonly)
    # Do not write child transcript into the parent session records.
    child.pop("records_writer", None)
    # Sub-agents track their own task list; never inherit or clobber the parent plan.
    child.pop(TODOS_CONTEXT_KEY, None)
    return child


def _count_tool_results(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("role") == "tool")


def run_subagent(
    *,
    description: str,
    prompt: str,
    subagent_type: str | None,
    workspace_root: str,
    context: dict,
) -> str:
    """Execute a sync sub-agent and return a JSON result string."""
    depth = int(context.get("agent_depth") or 0)
    if depth >= 1:
        return json.dumps({
            "error": "Sub-agents cannot spawn further agents (depth limit).",
        }, ensure_ascii=False)

    llm = context.get("llm")
    if not isinstance(llm, dict):
        return json.dumps({
            "error": "Agent tool requires context['llm'] (client/model/tools).",
        }, ensure_ascii=False)

    cfg: SubagentConfig = context.get("subagent_config") or SubagentConfig()
    if not cfg.enabled:
        return json.dumps({
            "error": "Sub-agent feature is disabled (subagent.enabled=false).",
        }, ensure_ascii=False)

    definition = resolve_agent_definition(subagent_type)
    if definition is None:
        return json.dumps({
            "error": (
                f"Unknown subagent_type '{subagent_type}'. "
                "Use 'general' or 'explore'."
            ),
        }, ensure_ascii=False)

    parent_tools = llm.get("tools") or []
    child_tools = filter_tools_for_agent(parent_tools, definition)
    child_system = append_worker_instructions(
        llm.get("system_prompt") or "",
        definition.agent_type,
    )
    child_context = build_child_context(context, definition=definition)
    child_messages: list[dict] = [
        {"role": "system", "content": child_system},
        {"role": "user", "content": prompt},
    ]

    print_agent_start(definition.agent_type, description, depth=depth + 1)
    started = time.monotonic()
    truncated = False
    result_text = ""
    tool_use_count = 0

    try:
        # Import here to avoid circular import at module load (api → tools → subagent).
        from miniclaw.api import run_turn_with_tools

        result_text, child_messages = run_turn_with_tools(
            llm["client"],
            llm["model"],
            child_messages,
            child_tools,
            print_reasoning=True,
            timeout=int(llm.get("timeout") or 300),
            workspace_root=workspace_root,
            context=child_context,
            context_config=llm.get("context_config"),
            max_turns=cfg.max_turns,
        )
        tool_use_count = _count_tool_results(child_messages)
        truncated = bool(child_context.get("_subagent_truncated"))
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        print_agent_done(
            definition.agent_type,
            status="failed",
            duration_ms=duration_ms,
            tool_use_count=tool_use_count,
            depth=depth + 1,
        )
        return json.dumps({
            "status": "failed",
            "agent_type": definition.agent_type,
            "description": description,
            "error": str(e),
            "result": result_text,
            "tool_use_count": tool_use_count,
            "duration_ms": duration_ms,
        }, ensure_ascii=False)

    duration_ms = int((time.monotonic() - started) * 1000)
    status = "truncated" if truncated else "completed"
    print_agent_done(
        definition.agent_type,
        status=status,
        duration_ms=duration_ms,
        tool_use_count=tool_use_count,
        depth=depth + 1,
    )

    payload: dict[str, Any] = {
        "status": status,
        "agent_type": definition.agent_type,
        "description": description,
        "result": result_text,
        "tool_use_count": tool_use_count,
        "duration_ms": duration_ms,
    }
    if truncated:
        payload["error"] = f"Reached max_turns={cfg.max_turns}"
    return json.dumps(payload, ensure_ascii=False)
