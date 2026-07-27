"""Built-in sub-agent type definitions."""
from __future__ import annotations

from dataclasses import dataclass

AGENT_TOOL_NAME = "Agent"

# Always stripped from every sub-agent tool pool.
ALWAYS_DISALLOWED_TOOLS = frozenset({
    AGENT_TOOL_NAME,
    "memory",
    "session_search",
})

# Explore: read-only research agent.
EXPLORE_ALLOWED_TOOLS = frozenset({
    "read",
    "grep",
    "glob",
    "bash",
    "Skill",
})

VALID_AGENT_TYPES = frozenset({"general", "explore"})


@dataclass(frozen=True)
class AgentDefinition:
    agent_type: str
    readonly: bool = False


GENERAL = AgentDefinition(agent_type="general", readonly=False)
EXPLORE = AgentDefinition(agent_type="explore", readonly=True)

AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    GENERAL.agent_type: GENERAL,
    EXPLORE.agent_type: EXPLORE,
}


def resolve_agent_definition(subagent_type: str | None) -> AgentDefinition | None:
    """Return definition for type; None if unknown. Empty/None → general."""
    name = (subagent_type or "general").strip().lower() or "general"
    return AGENT_DEFINITIONS.get(name)
