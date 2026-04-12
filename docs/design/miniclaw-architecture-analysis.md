# miniclaw 架构分析文档

> 本文档从 5 个维度深入分析 miniclaw 项目：Agent Loop、Skill 实现机制、Tool 设计、Prompt Cache 实现逻辑、Plan Mode 实现方式。

---

## 1. Agent Loop（智能体循环）

### 1.1 整体架构

miniclaw 的 Agent Loop 由两层循环构成：

```
User Input → REPL (cli.py) → LLM API (api.py) → Tools (tools.py)
                ↑                                        ↓
                └─────────── 循环直到无 tool_calls ←──────┘
```

### 1.2 REPL 循环（cli.py）

```
_repl_loop(session)
│
├─ prompt_session.prompt() 读取用户输入
├─ 处理内置命令 (/quit, /clear, /model, /plan)
│
├─ messages.append({"role": "user", "content": user_input})
├─ run_turn_with_tools(client, model, messages, tools, ...)
│   └─ 循环直到 LLM 不再调用工具
└─ 打印回复，继续等待下一轮输入
```

**关键代码路径**（cli.py:129-140）：
```python
reply, messages = run_turn_with_tools(
    client, model, messages, tools,
    print_reasoning=True, timeout=timeout,
    workspace_root=workspace, context=context,
)
```

### 1.3 Tool Call 循环（api.py:289-327）

`run_turn_with_tools` 是核心循环函数：

```python
def run_turn_with_tools(...) -> tuple[str, list[dict]]:
    while True:
        # 1. 发送流式请求到 LLM
        message, _ = chat_stream(
            client, messages, model=model,
            tools=tools, tool_choice="auto",
            extra_body={"reasoning_split": True},  # 启用思考分裂
        )

        # 2. 将 assistant message 加入历史
        messages.append(message)

        # 3. 无 tool_calls 时结束
        if not tool_calls:
            return (message.get("content") or "").strip(), messages

        # 4. 执行每个 tool_call
        for tc in tool_calls:
            result = _execute_tool_call(tc, workspace_root=workspace_root, context=context)
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})
        # 5. 继续循环，LLM 根据 tool 结果决定下一步
```

### 1.4 思考分裂（Reasoning Split）

miniclaw 通过 `extra_body={"reasoning_split": True}` 启用模型内置的思考分裂机制。思考内容通过 `delta.reasoning_details` 流式传输，并在终端显示 `[思考中...]` 提示。

**流式处理流程**（api.py:145-179）：
```python
def _consume_stream(stream, printer, start_time):
    for chunk in stream:
        # 处理 reasoning_details
        if has_reasoning:
            _accumulate_reasoning_delta(result.reasoning_acc, delta.reasoning_details)
            printer.on_reasoning()

        # 处理 content
        if delta.content:
            result.ttfc = time.monotonic() - start_time  # First Token to Content
            result.content_parts.append(delta.content)
            printer.on_content(delta.content)

        # 处理 tool_calls
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                _accumulate_tool_call_delta(result.tool_calls_acc, tc_delta)
```

---

## 2. Skill 实现机制

### 2.1 技能目录结构

```
{workspace}/.miniclaw/skills/
├── <skill_name>/
│   ├── SKILL.md          # 必需：YAML frontmatter + 使用说明
│   └── assets/           # 可选：模板、脚本等资源
```

### 2.2 SKILL.md 格式

```markdown
---
name: <技能名称>
description: <简短描述，供 system prompt 使用>
---
# 详细使用说明
正文描述技能的具体使用方式、参数规范等。
```

### 2.3 YAML Frontmatter 解析（skills.py:6-22）

```python
def parse_frontmatter(content: str) -> dict:
    """从 SKILL.md 内容中解析 YAML frontmatter"""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    # 解析 key: value 对，支持单引号和双引号转义
    for line in block.split("\n"):
        m = re.match(r"^(\w+):\s*(.*)$", line.strip())
        # 处理引号转义：\" -> ", \' -> '
```

### 2.4 技能扫描与 System Prompt 构建（skills.py:50-71）

```python
def build_system_prompt(skill_metadata_list: list[dict], *, workspace_root: str = None) -> str:
    """拼接完整的 system prompt"""
    lines = [
        "你是助手，可以使用提供的工具来完成任务。",
        workspace_line,  # "当前工作区目录：..."
        "",
        "## 技能（Skills）的访问方式",
        "技能存放在工作区的 .miniclaw/skills 目录中。",
        "每个技能对应一个子目录，例如 .miniclaw/skills/<skill_name>/。",
        "当你认为用户需求可能涉及某技能时，应先用 read 查看对应 SKILL.md...",
        "",
        "## 当前可用技能列表（自动从 .miniclaw/skills 扫描）",
    ]
    # 动态注入技能列表
    for s in skill_metadata_list:
        lines.append(f"- {s['name']}: {s['description']}")
```

### 2.5 技能加载时机

在 `cli.py` 的 `_init_session` 中初始化时扫描：

```python
def _init_session(args: argparse.Namespace) -> dict:
    skills_dir = os.path.join(workspace, ".miniclaw", "skills")
    skill_meta = scan_skills_metadata(skills_dir)
    system_prompt = build_system_prompt(skill_meta, workspace_root=workspace)
    # system_prompt 在整个会话期间保持不变
```

**特点**：技能元数据在会话初始化时一次性扫描并拼入 system prompt，实际技能内容由 LLM 按需通过 `read` 工具读取。

---

## 3. Tool 设计

### 3.1 工具列表

miniclaw 提供 6 个内置工具 + 2 个 Plan Mode 工具：

| 工具名 | 功能 | Plan Mode 状态 |
|--------|------|----------------|
| `read` | 读取文件（带行号） | ✅ 允许 |
| `write` | 写入文件（覆盖） | ❌ 阻止（plan 目录除外） |
| `edit` | 精确字符串替换 | ❌ 阻止（plan 目录除外） |
| `glob` | glob 模式匹配 | ✅ 允许 |
| `grep` | 正则搜索文件内容 | ✅ 允许 |
| `bash` | 执行 shell 命令 | ⚠️ 仅只读命令 |
| `enter_plan_mode` | 进入规划模式 | ✅ 允许 |
| `exit_plan_mode` | 退出规划模式 | ✅ 允许 |

### 3.2 工具分发机制（tools.py:129-192）

```python
TOOL_HANDLERS = {
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "glob": handle_glob,
    "grep": handle_grep,
    "bash": handle_bash,
}

def execute_tool(name: str, args: dict, workspace_root: str = None, context: dict = None) -> str:
    # 1. Plan Mode 权限检查
    blocked = check_plan_mode(name, args, ctx)
    if blocked:
        return blocked

    # 2. 分发到对应 handler
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"未知工具: {name}"})

    return handler(args, root)
```

### 3.3 Workspace 隔离（config.py:5-11）

所有文件操作强制在 workspace 内，通过 `resolve_path` 实现：

```python
def resolve_path(path: str, workspace_root: str) -> str:
    path = path.lstrip("/")  # 去除绝对路径前缀
    abs_path = os.path.normpath(os.path.join(workspace_root, path))
    if not abs_path.startswith(workspace_root):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path
```

### 3.4 工具 Schema 定义（tools.py:199-249）

每个工具都有 OpenAI function-calling 风格的 schema 定义：

```python
def get_tool_schemas() -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": "read",
            "description": "Read a file and return its content with line numbers...",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path under workspace"},
                "offset": {"type": "integer", "description": "Start line (0-based)"},
                "limit": {"type": "integer", "description": "Max number of lines"},
            }, "required": ["path"]},
        }},
        # ... 其他工具
    ] + get_plan_tool_schemas()
```

---

## 4. Prompt Cache 实现逻辑

### 4.1 缓存指标采集（api.py:39-50）

miniclaw 通过 `stream_options={"include_usage": True}` 获取详细的 token 使用统计：

```python
def _log_cache_metrics(usage) -> None:
    """从 usage 中提取缓存指标并记录到 dev log"""
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    ratio = (cached / prompt_tokens * 100) if prompt_tokens > 0 else 0.0

    get_dev_logger().info(
        "Cache metrics: prompt_tokens=%d, cached_tokens=%d, "
        "cache_hit_ratio=%.2f%%, completion_tokens=%d",
        prompt_tokens, cached, ratio, completion_tokens,
    )
```

### 4.2 缓存命中判断

缓存命中率 = `cached_tokens / prompt_tokens * 100%`

- `cached_tokens > 0` 表示存在缓存命中
- 100% 命中率表示整个 prompt 都在缓存中（首 token 延迟极低）

### 4.3 TTFT / TTFC 指标（api.py:96-142）

```python
@dataclass
class _StreamResult:
    ttft: Optional[float] = None  # Time To First Token（首个 token 延迟）
    ttfc: Optional[float] = None  # Time To First Content（首个内容 token 延迟）

# 在 _consume_stream 中记录
if result.ttft is None and (delta.content or has_reasoning or delta.tool_calls):
    result.ttft = time.monotonic() - start_time

if delta.content and result.ttfc is None:
    result.ttfc = time.monotonic() - start_time
```

### 4.4 开发者日志（dev_logging.py）

所有指标通过 `get_dev_logger()` 记录到 `~/.miniclaw/logs/` 目录：

```python
def setup_dev_logging():
    log_dir = get_log_dir()  # MINICLAW_DEV_LOG_DIR > ~/.miniclaw/logs/
    os.makedirs(log_dir, exist_ok=True)
    # 配置 logging 写入文件
```

---

## 5. Plan Mode 实现方式

### 5.1 模式切换

Plan Mode 通过 `enter_plan_mode` 和 `exit_plan_mode` 两个 tool 或 `/plan` 命令触发：

```python
context = {"mode": "agent", "plan_dir": plan_dir, "workspace_root": workspace}

# 进入 plan mode
context["mode"] = "plan"

# 退出 plan mode
context["mode"] = "agent"
```

### 5.2 权限控制核心（plan_mode.py:105-134）

```python
def check_plan_mode(name: str, args: dict, context: dict):
    """Plan mode 下拦截写操作，返回错误消息；通过时返回 None"""
    if not context or context.get("mode") != "plan":
        return None  # agent mode 放行

    # 1. 只读工具白名单
    if name in READONLY_TOOLS:  # read, glob, grep, enter/exit_plan_mode
        return None

    # 2. Plan 目录写入豁免
    if _is_plan_dir_write(name, args, context):
        return None

    # 3. Bash 只读检查
    if name == "bash":
        if is_readonly_bash(command, extra_patterns):
            return None
        return blocked_error_message

    # 4. 其他写操作全部拒绝
    return write_error_message
```

### 5.3 只读 Bash 判断（plan_mode.py:40-81）

```python
READONLY_BASH_COMMANDS = frozenset({
    "cat", "head", "tail", "less", "more", "wc", "file",
    "ls", "tree", "du", "df", "stat", "find", "which", "realpath",
    "grep", "rg", "sort", "uniq", "cut", "diff", "comm",
    "pwd", "whoami", "uname", "date", "echo", "printf",
    "node", "python3", "npm", "pip",
})

GIT_READONLY_SUBCOMMANDS = frozenset({
    "log", "status", "diff", "branch", "show", "tag", "remote", "ls-files", "blame",
})

def is_readonly_bash(command: str, extra_patterns: list[re.Pattern] = None) -> bool:
    """复合命令要求每段都是只读的"""
    parts = _COMPOUND_SPLIT_RE.split(command)  # 按 &&, ||, ;, | 分割
    return all(_is_single_command_readonly(p, extra_patterns) for p in parts)
```

**判断逻辑**：
1. 有重定向（`>`, `>>`）→ 非只读
2. base_cmd 在白名单 → 只读
3. git 子命令在只读列表 → 只读
4. 匹配用户配置的正则 → 只读
5. 否则 → 非只读

### 5.4 Plan 目录写入豁免（plan_mode.py:90-102）

```python
def _is_plan_dir_write(name: str, args: dict, context: dict) -> bool:
    """检查写操作目标是否在 plan 目录内"""
    if name not in ("write", "edit"):
        return False
    plan_dir = context.get("plan_dir", "")
    target_path = args.get("path", "")
    abs_target = resolve_path(target_path, context.get("workspace_root"))
    abs_plan_dir = os.path.normpath(plan_dir)
    return os.path.normpath(abs_target).startswith(abs_plan_dir + os.sep)
```

### 5.5 配置扩展（settings.py:102-127）

用户可通过 `config.json` 扩展允许的 bash 命令：

```json
{
  "plan_mode": {
    "allowed_bash_patterns": ["^firecrawl\\b", "^curl\\s+-s"]
  }
}
```

---

## 6. 配置文件系统

### 6.1 两级配置

```
~/.miniclaw/config.json                    # 全局配置
{workspace}/.miniclaw/config.json          # 工作区配置（优先）
```

### 6.2 配置合并规则（settings.py:34-49）

```python
def load_merged_config(workspace_root: str) -> dict:
    global_cfg = _load_json(~/.miniclaw/config.json)
    local_cfg = _load_json({workspace}/.miniclaw/config.json)

    merged = {**global_cfg}
    for key, val in local_cfg.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}  # shallow merge for dict
        else:
            merged[key] = val
```

### 6.3 LLM 配置优先级

```
环境变量 > config.llm.* > 硬编码默认值
LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_HTTP_TIMEOUT
```

---

## 7. 总结

miniclaw 是一个设计简洁但功能完整的 AI Coding Agent：

| 维度 | 实现方式 |
|------|----------|
| **Agent Loop** | REPL 层处理输入/命令，API 层处理流式对话和工具循环 |
| **Skills** | 目录扫描 + YAML frontmatter 解析 + system prompt 注入 |
| **Tools** |  Handler 分发 + workspace 隔离 + schema 注册 |
| **Prompt Cache** | 通过 `prompt_tokens_details.cached_tokens` 监控，TTFT/TTFC 指标 |
| **Plan Mode** | 模式状态机 + 只读白名单 + plan 目录写入豁免 + 配置化扩展 |
