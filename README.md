# miniclaw

基于 MiniMax API 的小工具与命令行对话。

## 命令行 LLM 对话 (chat.py)

使用 MiniMax 文本对话 API 的交互式命令行聊天。

### 准备

1. 在 [MiniMax 开放平台](https://platform.minimax.io) 注册并创建 API Key。
2. 安装依赖：`pip install -r requirements.txt`

### 使用

```bash
# 设置 API Key 后运行
export MINIMAX_API_KEY=your_api_key
python chat.py
```

可选环境变量：

- `MINIMAX_API_KEY`（必填）：MiniMax API Key
- `MINIMAX_MODEL`：模型名，默认 `MiniMax-M2.5`（若报错可试 `M2-her`）
- `MINIMAX_SYSTEM`：可选 system 角色设定（如人设、规则）

### 对话内命令

- `/quit` 或 `/exit` 或 `/q`：退出
- `/clear`：清空当前对话历史
- `/model`：显示当前使用的模型
