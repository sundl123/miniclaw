# miniclaw — 项目核心说明

本文档面向参与本仓库开发的开发者与 AI Agent，用于快速把握项目定位与代码规范。

---

## 1. 项目介绍

**miniclaw** 是基于 **MiniMax API** 的命令行 LLM 对话工具，核心能力包括：

- **对话**：使用 MiniMax 文本对话 API（`api.minimaxi.com`），支持多轮对话，默认模型 `MiniMax-M2.7`。
- **Tool Call**：模型可调用 `code_execution` 工具，在工作区（项目根）内执行 bash、查看/创建/编辑文件。
- **.skills 技能目录**：启动时自动扫描项目根下 `.skills` 目录，从各子目录的 `SKILL.md` 解析 `name`、`description`，拼入 system prompt；模型按需通过 `view_file` 读取 `.skills/<name>/SKILL.md` 使用技能。

**主要入口与结构**：

- `chat.py`：入口脚本，仅调用 `miniclaw.cli.main()`。
- `miniclaw/` 包：`config.py`（常量）、`skills.py`（技能扫描与 system 文案）、`code_execution.py`（工具实现）、`api.py`（MiniMax 请求与 tool 循环）、`cli.py`（REPL 主流程）。
- `.skills/`：技能目录，每个技能一个子目录，内含 `SKILL.md`（YAML frontmatter + 正文）。示例：`.skills/example-skill/`。
- `tests/`：单元测试（`test_skills.py`、`test_code_execution.py`、`test_api.py`、`test_cli.py`）。
- 工作区根默认为项目根（即 `chat.py` 所在目录），可通过 `--workspace`（`-w`）参数或 `MINICLAW_WORKSPACE` 环境变量自定义（CLI 参数 > 环境变量 > 项目根）；所有文件与 bash 的 cwd 均为工作区根目录，路径禁止 `..` 逃逸。

**运行方式**：`MINIMAX_API_KEY=your_key python3 chat.py`（可附加 `--workspace /path/to/dir`）。详见 [README.md](README.md)。

---

## 2. 代码规范

### 2.1 函数长度与可读性

- **函数不宜过长**，过长会降低可读性与可测试性。
- 若单个函数逻辑较多或超过约 40–50 行，应拆分为多个小函数，或抽离到独立模块/文件。
- 拆分时注意：每个函数职责单一，命名清晰，便于单独编写单元测试。

### 2.2 测试与验证

- **新增功能应尽量编写单元测试**，并在合入前自行验证新功能正确。
- 测试文件建议放在项目根或 `tests/` 目录，命名如 `test_<模块名>.py`，使用 pytest 或标准库 `unittest` 均可。
- 新增或修改逻辑后，应运行相关测试并确认通过；如有脚本或 CLI 行为变更，建议在本地执行一次典型流程做人工验证。

---

以上为项目核心信息与代码规范，开发与评审时请遵循。
