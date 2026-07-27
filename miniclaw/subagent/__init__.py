"""Synchronous Sub-Agent: isolated tool loops for delegated tasks."""

from miniclaw.subagent.config import SubagentConfig
from miniclaw.subagent.tool import get_agent_tool_schema, handle_agent

__all__ = [
    "SubagentConfig",
    "get_agent_tool_schema",
    "handle_agent",
]
