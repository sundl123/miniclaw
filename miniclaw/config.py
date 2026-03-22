"""配置常量：工作区根、技能目录、MiniMax API 地址与默认模型。"""
import os

# 工作区根 = 包所在目录的上一级（项目根，即 chat.py 所在目录）
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(WORKSPACE_ROOT, ".skills")

# 开发者文件日志目录（仅写入文件，不向终端输出；可用 MINICLAW_DEV_LOG_DIR 覆盖）
DEV_LOG_DIR = os.environ.get("MINICLAW_DEV_LOG_DIR", "").strip() or os.path.join(
    WORKSPACE_ROOT, ".miniclaw_logs"
)

BASE_URL = "https://api.minimaxi.com"
CHAT_URL = f"{BASE_URL}/v1/text/chatcompletion_v2"
CHAT_URL_OPENAI = f"{BASE_URL}/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.5"

# MiniMax HTTP 请求超时（秒，含连接与读）。可用 MINIMAX_HTTP_TIMEOUT 覆盖。
_raw_http_timeout = os.environ.get("MINIMAX_HTTP_TIMEOUT", "").strip()
try:
    HTTP_TIMEOUT = int(_raw_http_timeout) if _raw_http_timeout else 300
    if HTTP_TIMEOUT <= 0:
        HTTP_TIMEOUT = 300
except ValueError:
    HTTP_TIMEOUT = 300
