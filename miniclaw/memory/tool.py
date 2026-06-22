"""Memory tool handler and OpenAI function schema."""
from __future__ import annotations

import json

from miniclaw.memory.store import MemoryStore
from miniclaw.tools_config import ReadToolConfig, ToolsConfig

MEMORY_TOOL_DESCRIPTION = (
    "Read and write persistent memory under ~/.miniclaw/memory/.\n\n"
    "ONLY MEMORY.md is auto-loaded every session (frozen in system prompt); "
    "treat it as scarce — byte/line limits apply only to MEMORY.md. Put highest-signal "
    "facts there: user preferences, corrections, durable environment facts.\n\n"
    "Other files and subdirectories have NO size limit on disk — use them as an "
    "unlimited scratch pad for detail. When reading large topic files use offset/limit; "
    "without limit, oversized files are rejected (see error message).\n\n"
    "When MEMORY.md is full: shorten it, remove stale items, move detail to topic "
    "files, leave a short summary or relative link.\n\n"
    "Deleting MEMORY.md is NOT allowed; use edit to clear sections conservatively.\n\n"
    "Mutating actions and status return memory_md_usage (limits, usage, display). "
    "Budget failures include limits and would_be. A warning field appears when nearing "
    "capacity. Use action=status to compare disk vs frozen-injected snapshot.\n\n"
    "Do NOT save ephemeral task progress; save durable preferences and facts the user "
    "should not need to repeat."
)


def get_memory_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "memory",
            "description": MEMORY_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "edit", "list", "delete", "status"],
                        "description": "Operation to perform.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path under ~/.miniclaw/memory/ "
                            "(e.g. MEMORY.md, notes/foo.md). Required for read/write/edit/delete."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content. Required for write.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Substring to replace. Required for edit.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text. Required for edit.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": (
                            "0-based line offset for read. Large files require limit; "
                            "without limit, oversized files are rejected."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Max lines for read. Required for large files; output may be "
                            "truncated if still too large."
                        ),
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": (
                            "For list: include subdirectories. Results are capped (see "
                            "entries_truncated / total_entries when truncated)."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }


def handle_memory(
    args: dict,
    context: dict | None = None,
    tools_cfg: ToolsConfig | None = None,
) -> str:
    store: MemoryStore | None = (context or {}).get("memory_store")
    if store is None:
        return json.dumps(
            {"success": False, "error": "Memory is not enabled or store not initialized."},
            ensure_ascii=False,
        )

    cfg = tools_cfg or ToolsConfig(read=ReadToolConfig())
    action = (args.get("action") or "").strip().lower()
    path = args.get("path")

    try:
        if action == "status":
            result = store.status()
        elif action == "read":
            if not path:
                return json.dumps({"success": False, "error": "read requires path."}, ensure_ascii=False)
            offset = int(args.get("offset") or 0)
            limit = args.get("limit")
            limit_int = int(limit) if limit is not None else None
            if limit_int is not None and limit_int <= 0:
                limit_int = None
            result = store.read_file(
                path,
                offset=offset,
                limit=limit_int,
                read_cfg=cfg.read,
            )
        elif action == "write":
            if not path:
                return json.dumps({"success": False, "error": "write requires path."}, ensure_ascii=False)
            content = args.get("content")
            if content is None:
                return json.dumps({"success": False, "error": "write requires content."}, ensure_ascii=False)
            result = store.write_file(path, content)
        elif action == "edit":
            if not path:
                return json.dumps({"success": False, "error": "edit requires path."}, ensure_ascii=False)
            old_string = args.get("old_string")
            new_string = args.get("new_string")
            if old_string is None:
                return json.dumps({"success": False, "error": "edit requires old_string."}, ensure_ascii=False)
            if new_string is None:
                return json.dumps({"success": False, "error": "edit requires new_string."}, ensure_ascii=False)
            result = store.edit_file(path, old_string, new_string)
        elif action == "list":
            recursive = bool(args.get("recursive"))
            result = store.list_files(
                path or "",
                recursive=recursive,
                max_entries=cfg.max_glob_files,
            )
        elif action == "delete":
            if not path:
                return json.dumps({"success": False, "error": "delete requires path."}, ensure_ascii=False)
            result = store.delete_file(path)
        else:
            return json.dumps(
                {"success": False, "error": f"Unknown action {action!r}."},
                ensure_ascii=False,
            )
    except PermissionError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    return json.dumps(result, ensure_ascii=False)
