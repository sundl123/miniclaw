"""配置常量：路径安全与 LLM 默认值。"""
import os
import re
from datetime import date

_GLOB_META_RE = re.compile(r"[*?\[]")


def _is_under_dir(abs_path: str, base_dir: str) -> bool:
    """判断 abs_path 是否在 base_dir 下（含 base_dir 本身）。"""
    norm_path = os.path.normpath(abs_path)
    norm_base = os.path.normpath(base_dir)
    return norm_path == norm_base or norm_path.startswith(norm_base + os.sep)


def is_allowed_read_path(
    abs_path: str,
    workspace_root: str,
    *,
    registered_skill_dirs: frozenset[str] = frozenset(),
) -> bool:
    """判断绝对路径是否在 workspace 或已注册 skill 目录下。"""
    if _is_under_dir(abs_path, workspace_root):
        return True
    return any(_is_under_dir(abs_path, skill_dir) for skill_dir in registered_skill_dirs)


def get_local_iso_date() -> str:
    """返回本地时区 ISO 日期 YYYY-MM-DD；测试可用 MINICLAW_OVERRIDE_DATE 覆盖。"""
    override = os.environ.get("MINICLAW_OVERRIDE_DATE")
    if override:
        return override
    return date.today().isoformat()


def resolve_path(path: str, workspace_root: str) -> str:
    """将 path 解析为工作区内的绝对路径（支持绝对/相对），禁止 .. 逃逸。"""
    workspace_root = os.path.normpath(workspace_root)
    if os.path.isabs(path):
        abs_path = os.path.normpath(path)
    else:
        abs_path = os.path.normpath(os.path.join(workspace_root, path))
    if not _is_under_dir(abs_path, workspace_root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


def resolve_read_path(
    path: str,
    workspace_root: str,
    *,
    registered_skill_dirs: frozenset[str] = frozenset(),
) -> str:
    """解析 read/grep 路径：workspace 内路径 + 已注册 skill 目录下的绝对路径。"""
    if os.path.isabs(path):
        abs_path = os.path.normpath(path)
        if is_allowed_read_path(
            abs_path, workspace_root, registered_skill_dirs=registered_skill_dirs,
        ):
            return abs_path
        raise PermissionError(f"路径不允许读取: {path}")
    return resolve_path(path, workspace_root)


def _glob_static_prefix(pattern: str) -> str:
    """提取 glob pattern 中首个元字符前的静态路径前缀。"""
    match = _GLOB_META_RE.search(pattern)
    static = pattern[: match.start()] if match else pattern
    static = static.rstrip("/")
    if not static:
        return os.path.abspath(os.sep)
    if os.path.isdir(static):
        return os.path.normpath(static)
    parent = os.path.dirname(static)
    return os.path.normpath(parent) if parent else os.path.normpath(static)


def resolve_glob_pattern(
    pattern: str,
    workspace_root: str,
    *,
    registered_skill_dirs: frozenset[str] = frozenset(),
) -> tuple[str, str]:
    """返回 (full_glob_pattern, result_base)。

    result_base 用于格式化输出：等于 workspace_root 时返回相对路径，否则返回绝对路径。
    """
    workspace_root = os.path.normpath(workspace_root)
    if os.path.isabs(pattern):
        prefix = _glob_static_prefix(pattern)
        resolve_read_path(prefix, workspace_root, registered_skill_dirs=registered_skill_dirs)
        return pattern, prefix
    full_pattern = os.path.join(workspace_root, pattern)
    return full_pattern, workspace_root


DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_HTTP_TIMEOUT = 300
