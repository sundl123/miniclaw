"""配置常量：工作区根、路径安全、MiniMax API 地址与默认模型。"""
import os

# 工作区根 = 包所在目录的上一级（项目根，即 chat.py 所在目录）
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(path: str, workspace_root: str = None) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    root = workspace_root or WORKSPACE_ROOT
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(root, path))
    if not abs_path.startswith(root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path

# 开发者文件日志目录（仅写入文件，不向终端输出；可用 MINICLAW_DEV_LOG_DIR 覆盖）
DEV_LOG_DIR = os.environ.get("MINICLAW_DEV_LOG_DIR", "").strip() or os.path.join(
    WORKSPACE_ROOT, ".miniclaw_logs"
)

BASE_URL = "https://api.minimaxi.com"
OPENAI_BASE_URL = os.environ.get("MINIMAX_OPENAI_BASE_URL", "").strip() or f"{BASE_URL}/v1"
DEFAULT_MODEL = "MiniMax-M2.7"

# MiniMax HTTP 请求超时（秒，含连接与读）。可用 MINIMAX_HTTP_TIMEOUT 覆盖。
_raw_http_timeout = os.environ.get("MINIMAX_HTTP_TIMEOUT", "").strip()
try:
    HTTP_TIMEOUT = int(_raw_http_timeout) if _raw_http_timeout else 300
    if HTTP_TIMEOUT <= 0:
        HTTP_TIMEOUT = 300
except ValueError:
    HTTP_TIMEOUT = 300
