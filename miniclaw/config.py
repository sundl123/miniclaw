"""配置常量：路径安全与 LLM 默认值。"""
import os


def resolve_path(path: str, workspace_root: str) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(workspace_root, path))
    if not abs_path.startswith(workspace_root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_HTTP_TIMEOUT = 300
