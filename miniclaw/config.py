"""配置常量：路径安全、API 地址与默认模型。"""
import os


def resolve_path(path: str, workspace_root: str) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(workspace_root, path))
    if not abs_path.startswith(workspace_root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


BASE_URL = "https://api.minimaxi.com"
OPENAI_BASE_URL = os.environ.get("LLM_BASE_URL", "").strip() or f"{BASE_URL}/v1"
DEFAULT_MODEL = "MiniMax-M2.7"

_raw_http_timeout = os.environ.get("LLM_HTTP_TIMEOUT", "").strip()
try:
    HTTP_TIMEOUT = int(_raw_http_timeout) if _raw_http_timeout else 300
    if HTTP_TIMEOUT <= 0:
        HTTP_TIMEOUT = 300
except ValueError:
    HTTP_TIMEOUT = 300
