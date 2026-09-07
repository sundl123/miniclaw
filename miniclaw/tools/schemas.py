"""Tool schema 组装：核心工具 + 可选 memory/session_search/Agent + plan mode。"""
from __future__ import annotations

from miniclaw.memory.tool import get_memory_tool_schema
from miniclaw.plan_mode import get_plan_tool_schemas
from miniclaw.sessions.search import get_session_search_schema
from miniclaw.subagent.tool import get_agent_tool_schema


def get_tool_schemas(
    *,
    include_memory: bool = False,
    include_session_search: bool = False,
    include_agent: bool = False,
) -> list[dict]:
    """返回所有工具的 OpenAI function-calling 风格定义（含 plan mode 工具）。"""
    schemas = [
        {"type": "function", "function": {
            "name": "read",
            "description": (
                "Read a file and return its content with line numbers (0-based offset). "
                "For large files you MUST use limit; without limit, files over 256KB are rejected. "
                "If output is still too large with limit, results may be truncated."
            ),
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to read (must be absolute, not relative)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Start line, 0-based (default 0)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read (required for large files)",
                },
            }, "required": ["path"]},
        }},
        {"type": "function", "function": {
            "name": "write",
            "description": "Write content to a file (overwrites if exists, creates parent directories as needed).",
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to write (must be absolute, not relative)",
                },
                "content": {"type": "string", "description": "File content to write"},
            }, "required": ["path", "content"]},
        }},
        {"type": "function", "function": {
            "name": "edit",
            "description": "Replace a unique string in a file. old_string must appear exactly once.",
            "parameters": {"type": "object", "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file to modify (must be absolute, not relative)",
                },
                "old_string": {"type": "string", "description": "The exact string to find (must appear once)"},
                "new_string": {"type": "string", "description": "The replacement string"},
            }, "required": ["path", "old_string", "new_string"]},
        }},
        {"type": "function", "function": {
            "name": "glob",
            "description": (
                "Find files matching a glob pattern within the workspace or a registered "
                "skill directory. Use absolute patterns (e.g. /path/to/ws/**/*.py). "
                "Use ** for recursive matching. Results are capped (newest first)."
            ),
            "parameters": {"type": "object", "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Absolute glob pattern (e.g. '/path/to/ws/**/*.py')",
                },
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "grep",
            "description": (
                "Search file contents for a pattern (regex) within the workspace or a "
                "registered skill directory (absolute path)."
            ),
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {
                    "type": "string",
                    "description": "Absolute path to search in (default: workspace root as absolute path)",
                },
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "bash",
            "description": "Run a shell command in the workspace directory.",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
            }, "required": ["command"]},
        }},
        {"type": "function", "function": {
            "name": "Skill",
            "description": (
                "Load and activate a skill by name. Call this BEFORE executing "
                "task-specific workflows when a skill matches the user's request. "
                "Available skills are listed in the system prompt."
            ),
            "parameters": {"type": "object", "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name (without leading slash, e.g. code-review)",
                },
            }, "required": ["skill"]},
        }},
        {"type": "function", "function": {
            "name": "todo_write",
            "description": (
                "Create and manage a task list for your current coding session. "
                "Use this to track progress on complex multi-step tasks. "
                "Tasks have status: pending, in_progress, completed, cancelled. "
                "Set merge=true to update existing tasks by id; merge=false replaces all."
            ),
            "parameters": {"type": "object", "properties": {
                "todos": {
                    "type": "array",
                    "description": "Task list. Each item: {content (text), status (pending|in_progress|completed|cancelled), id? (string for merge)}",
                    "items": {"type": "object", "properties": {
                        "content": {"type": "string", "description": "Task description"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "Task status",
                        },
                        "id": {"type": "string", "description": "Optional stable ID for merge mode"},
                    }, "required": ["content", "status"]},
                },
                "merge": {
                    "type": "boolean",
                    "description": "If true, merge with existing tasks by id; if false, replace all tasks",
                },
            }, "required": ["todos", "merge"]},
        }},
        {"type": "function", "function": {
            "name": "ask_followup_question",
            "description": (
                "Ask the user a clarifying question when requirements are ambiguous "
                "or you need to confirm a decision. Supports multiple-choice options "
                "and free-text answers."
            ),
            "parameters": {"type": "object", "properties": {
                "question": {
                    "type": "string",
                    "description": "The question text to ask the user",
                },
                "header": {
                    "type": "string",
                    "description": "Optional short title",
                },
                "options": {
                    "type": "array",
                    "description": "Optional list of options. Each can be a string or {label, description}",
                    "items": {},
                },
                "multi_select": {
                    "type": "boolean",
                    "description": "Whether multiple options can be selected",
                },
            }, "required": ["question"]},
        }},
    ]
    if include_memory:
        schemas.append(get_memory_tool_schema())
    if include_session_search:
        schemas.append(get_session_search_schema())
    if include_agent:
        schemas.append(get_agent_tool_schema())
    return schemas + get_plan_tool_schemas()
