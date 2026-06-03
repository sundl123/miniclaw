"""配置常量：路径安全与 LLM 默认值。"""
import os


def _is_under_dir(abs_path: str, base_dir: str) -> bool:
    """判断 abs_path 是否在 base_dir 下（含 base_dir 本身）。"""
    norm_path = os.path.normpath(abs_path)
    norm_base = os.path.normpath(base_dir)
    return norm_path == norm_base or norm_path.startswith(norm_base + os.sep)


def resolve_path(path: str, workspace_root: str) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(workspace_root, path))
    if not _is_under_dir(abs_path, workspace_root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


def resolve_read_path(
    path: str,
    workspace_root: str,
    *,
    allowed_skill_dirs: set[str] | frozenset[str] = frozenset(),
) -> str:
    """解析 read 工具路径：workspace 内路径 + 已加载 skill 目录下的绝对路径。"""
    if os.path.isabs(path):
        abs_path = os.path.normpath(path)
        if _is_under_dir(abs_path, workspace_root):
            return abs_path
        for skill_dir in allowed_skill_dirs:
            if _is_under_dir(abs_path, skill_dir):
                return abs_path
        raise PermissionError(f"路径不允许读取: {path}")
    return resolve_path(path, workspace_root)


DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_HTTP_TIMEOUT = 300
