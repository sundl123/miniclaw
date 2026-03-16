# miniclaw

基于 MiniMax API 的小工具与命令行对话，支持 **code-execution** 工具与 **.skills** 技能目录。

## 命令行 LLM 对话 (chat.py)

使用 MiniMax 文本对话 API 的交互式聊天，具备：

- **Tool Call**：模型可调用 `code_execution` 工具（执行 bash、查看/创建/编辑工作区文件）。
- **.skills**：启动时自动扫描项目根下 `.skills` 目录，将各技能的 name/description 注入 system prompt，模型按需通过 `view_file` 读取 `.skills/<name>/SKILL.md` 使用技能。

### 准备

1. 在 [MiniMax 开放平台](https://platform.minimaxi.com) 注册并创建 API Key。
2. 安装依赖：`pip install -r requirements.txt`

### 使用

```bash
export MINIMAX_API_KEY=your_api_key
python3 chat.py
```

可选环境变量：

- `MINIMAX_API_KEY`（必填）：MiniMax API Key
- `MINIMAX_MODEL`：模型名，默认 `MiniMax-M2.5`
- `MINIMAX_SYSTEM`：可选，追加到 system 的额外说明（如人设、规则）

### 对话内命令

- `/quit` 或 `/exit` 或 `/q`：退出
- `/clear`：清空对话历史
- `/model`：显示当前模型

### .skills 目录

在项目根下创建 `.skills/<技能名>/SKILL.md`，YAML frontmatter 含 `name`、`description`，正文写使用说明。模型会根据描述决定是否查阅该技能并执行其中步骤。示例见 `.skills/example-skill/`。

### 安全说明

- **工作区**：所有文件与 bash 的工作目录为 chat.py 所在项目根，路径禁止 `..` 逃逸。
- **run_bash**：当前未对命令做白名单限制，模型可执行任意 bash。请勿在生产环境或不可信输入下开放使用，避免执行有害命令。
