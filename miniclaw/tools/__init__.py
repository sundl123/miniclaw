"""工具集：read、write、edit、glob、grep、bash，均限制在 workspace 内。

公开 API 与拆包前 `miniclaw.tools` 模块兼容。config 可直接 import，
其余符号经 __getattr__ 懒加载，避免 settings ↔ tools 循环依赖。
"""
from __future__ import annotations

from miniclaw.tools.config import ReadToolConfig, ToolsConfig

__all__ = [
    "ReadToolConfig",
    "ToolsConfig",
    "TOOL_HANDLERS",
    "execute_tool",
    "get_tool_schemas",
    "handle_bash",
    "handle_edit",
    "handle_glob",
    "handle_grep",
    "handle_read",
    "handle_skill",
    "handle_write",
]

_LAZY = {
    "TOOL_HANDLERS": ("miniclaw.tools.dispatch", "TOOL_HANDLERS"),
    "execute_tool": ("miniclaw.tools.dispatch", "execute_tool"),
    "get_tool_schemas": ("miniclaw.tools.schemas", "get_tool_schemas"),
    "handle_bash": ("miniclaw.tools.bash", "handle_bash"),
    "handle_edit": ("miniclaw.tools.write", "handle_edit"),
    "handle_glob": ("miniclaw.tools.search", "handle_glob"),
    "handle_grep": ("miniclaw.tools.search", "handle_grep"),
    "handle_read": ("miniclaw.tools.read", "handle_read"),
    "handle_skill": ("miniclaw.tools.skill", "handle_skill"),
    "handle_write": ("miniclaw.tools.write", "handle_write"),
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = _LAZY[name]
    import importlib
    mod = importlib.import_module(module_name)
    value = getattr(mod, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
