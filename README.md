# miniclaw

命令行 LLM 对话工具（harness 框架），支持 code-execution 工具、plan mode 与 .skills 技能目录。底层模型可替换，当前默认接入 MiniMax API。

## 安装

### 推荐方式：pipx

[pipx](https://pipx.pypa.io/) 会在隔离的虚拟环境中安装 miniclaw，不污染系统 Python 环境：

```bash
# 安装 pipx（如果还没有）
pip install pipx
pipx ensurepath    # 确保 ~/.local/bin 在 PATH 中，首次安装后需重开终端

# 安装 miniclaw
pipx install miniclaw
```

### 或者用 pip

```bash
pip install miniclaw
```

### 从源码安装（开发者）

```bash
git clone https://github.com/sundl123/miniclaw.git
cd miniclaw
pip install -e .
```

安装后即可在任意目录使用 `miniclaw` 命令。

> **提示**：如果安装后提示 `command not found: miniclaw`，说明安装目录不在 PATH 中。
> - pipx 用户：运行 `pipx ensurepath` 然后重开终端
> - pip 用户（macOS）：`echo 'export PATH="$HOME/Library/Python/3.9/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`

## 快速开始

```bash
# 设置 API Key
export LLM_API_KEY=your_api_key

# 在当前目录启动（当前目录即为 workspace）
cd ~/my-project
miniclaw

# 或指定 workspace
miniclaw -w /path/to/workspace
```

## 功能

- **Tool Call**：模型可调用 `read`、`write`、`edit`、`glob`、`grep`、`bash` 六个工具，在 workspace 内读写文件和执行命令。
- **Plan Mode**：面对复杂任务时，模型可主动进入规划模式——只读探索代码库，产出结构化 plan 文件，经用户确认后再执行。plan mode 下只读 bash 命令（ls、cat、git log 等）自动放行，写操作被拦截。
- **.skills**：启动时自动扫描 workspace 下 `.miniclaw/skills` 目录，将各技能的 name/description 注入 system prompt，模型按需读取 SKILL.md 使用技能。

## 对话内命令

| 命令 | 说明 |
|------|------|
| `/quit`、`/exit`、`/q` | 退出 |
| `/clear` | 清空对话历史 |
| `/model` | 显示当前模型 |
| `/plan` | 进入 plan mode |
| `/plan <描述>` | 进入 plan mode 并描述需求 |

快捷键：`Ctrl+J` 换行、`↑/↓` 历史记录、`Ctrl+C` 取消输入、`Ctrl+D` 退出。

## 文件存储

miniclaw 的文件分两级存放：

```
~/.miniclaw/                    用户级（所有 workspace 共用）
├── logs/                       运行日志
└── config.json                 全局配置（可选）

{workspace}/                    workspace 级（跟随项目）
└── .miniclaw/
    ├── config.json             workspace 配置（优先级高于全局）
    ├── plans/                  plan 文件
    └── skills/                 技能目录
```

## 配置文件

配置文件为 JSON 格式，支持全局（`~/.miniclaw/config.json`）和 workspace（`{workspace}/.miniclaw/config.json`）两级，workspace 配置优先。

首次运行 `miniclaw` 或执行 `miniclaw init` 会自动在 `~/.miniclaw/` 下创建默认配置文件。如需重置：`miniclaw init --force`。

当前支持的配置项：

```json
{
  "plan_mode": {
    "allowed_bash_patterns": [
      "^firecrawl\\b",
      "^curl\\s+-s"
    ]
  }
}
```

`plan_mode.allowed_bash_patterns`：plan mode 下额外允许的 bash 命令（正则表达式列表）。内置白名单已包含 ls、cat、git log 等常用只读命令，此处用于添加项目特有的命令。

## 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | LLM API Key（也可在 config.json 中设置 `api_key` 字段，环境变量优先） |
| `LLM_MODEL` | 模型名，默认 `MiniMax-M2.7` |
| `LLM_BASE_URL` | OpenAI 兼容 API 地址，可替换为其他供应商 |
| `MINICLAW_WORKSPACE` | 工作区目录，也可通过 `-w` 参数指定（CLI 参数优先）。未指定时默认为当前目录 |
| `MINICLAW_DEV_LOG_DIR` | 自定义日志目录，默认 `~/.miniclaw/logs/` |

## Skills 技能目录

在 workspace 下创建 `.miniclaw/skills/<技能名>/SKILL.md`，YAML frontmatter 含 `name`、`description`，正文写使用说明。模型会根据描述决定是否查阅该技能并执行其中步骤。

## 安全说明

- **工作区隔离**：所有文件与 bash 的工作目录限制在 workspace 内，路径禁止 `..` 逃逸。
- **Plan Mode**：规划阶段只允许只读操作和 plan 文件写入，写操作命令会被拦截。
- **bash**：agent mode 下未对 bash 命令做白名单限制。请勿在不可信环境下使用。

## 项目结构

```
miniclaw/
├── chat.py              # 开发便利入口（等同于 miniclaw 命令）
├── pyproject.toml       # 包配置与入口点
├── miniclaw/            # Python 包
│   ├── cli.py           # 命令行 REPL
│   ├── api.py           # LLM API 与 tool 循环
│   ├── tools.py         # 六个基础工具 + 分发
│   ├── plan_mode.py     # plan mode 权限控制 + bash 白名单
│   ├── config.py        # 路径安全 + API 常量
│   ├── dirs.py          # 目录解析（用户级 / workspace 级）
│   ├── settings.py      # 配置文件加载与合并
│   ├── skills.py        # 技能扫描与 system prompt
│   └── dev_logging.py   # 开发者日志
├── tests/               # 单元测试
└── docs/                # 设计文档
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```
