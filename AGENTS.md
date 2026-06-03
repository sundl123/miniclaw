# miniclaw — 项目核心说明

本文档面向参与本仓库开发的开发者与 AI Agent，用于快速把握项目定位与代码规范。

---

## 1. 项目介绍

**miniclaw** 是命令行 LLM 对话工具（通用 harness 框架），可通过 `pip install miniclaw` 安装后在任意目录使用 `miniclaw` 命令启动。底层模型可替换，当前默认接入 MiniMax API。核心能力包括：

- **对话**：基于 OpenAI 兼容接口，支持多轮对话，默认模型 `MiniMax-M2.7`（可通过环境变量或 config.json 的 `llm` 配置切换模型和 API 地址）。
- **Tool Call**：模型可调用 `read`、`write`、`edit`、`glob`、`grep`、`bash`、`Skill` 七个工具，在 workspace 内读写文件和执行命令。
- **Plan Mode**：面对复杂任务时进入只读规划阶段，只读 bash 命令自动放行，写操作被拦截。可通过 `.miniclaw/config.json` 扩展允许的 bash 命令。
- **Skills 技能目录**：启动时扫描 `~/.miniclaw/skills/`（全局）与 `{workspace}/.miniclaw/skills/`（项目，同名覆盖全局），从各子目录的 `SKILL.md` 解析元数据拼入 system prompt；模型通过 `Skill` tool 加载 skill 正文（注入 Base directory 前缀）。已加载 skill 目录下的 reference 文件允许 `read` 访问（可超出 workspace）。

**主要入口与结构**：

- `miniclaw` 命令（pip 安装后可用）或 `python3 chat.py`：入口，调用 `miniclaw.cli.main()`。
- `miniclaw/` 包：`cli.py`（REPL）、`api.py`（LLM API 与 tool 循环）、`tools.py`（六个基础工具 + 分发）、`plan_mode.py`（plan mode 权限控制 + bash 白名单）、`config.py`（路径安全 + API 常量）、`dirs.py`（目录解析）、`settings.py`（配置加载与合并）、`skills.py`（技能扫描）、`dev_logging.py`（开发者日志）。
- `.miniclaw/skills/`：项目级技能目录；`~/.miniclaw/skills/`：全局技能目录。每个技能一个子目录，内含 `SKILL.md`（YAML frontmatter + 正文）。
- `tests/`：单元测试（`test_tools.py`、`test_api.py`、`test_cli.py`、`test_skills.py`、`test_dev_logging.py`）。
- 文件分两级存放：用户级（`~/.miniclaw/`，含 logs 和全局 config）和 workspace 级（`{cwd}/.miniclaw/`，含 plans 和 workspace config）。
- workspace 默认为当前目录，可通过 `-w` 参数或 `MINICLAW_WORKSPACE` 环境变量自定义（CLI 参数 > 环境变量 > CWD）；所有文件与 bash 的 cwd 均为 workspace，路径禁止 `..` 逃逸。

**运行方式**：`LLM_API_KEY=your_key miniclaw`（可附加 `-w /path/to/dir`）。详见 [README.md](README.md)。

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
