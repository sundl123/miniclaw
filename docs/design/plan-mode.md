# Plan Mode 设计文档

本文档记录 miniclaw plan mode 的设计背景、参考分析与实现方案。

---

## 1. 背景

miniclaw 是一个教育导向的命令行 LLM 对话工具，核心能力是让模型通过 tool call 读写文件、执行命令。但在面对复杂任务时，模型容易"边想边做"，缺乏整体规划，导致修改零散、遗漏边界场景。

Plan mode 的目标是：让模型在动手之前先进入一个**只读探索 + 结构化规划**的阶段，产出一份可追踪的计划文档，然后再切换到执行阶段逐步实施。

---

## 2. 参考：Claude Code 的 Plan Mode 实现

以下分析基于 Claude Code 源码（约 512K 行 TypeScript）。

### 2.1 核心架构

Claude Code 的 plan mode **不是一个独立的执行引擎**，而是在现有 agent 循环上叠加两层约束：

1. **权限模式切换** — 将 `toolPermissionContext.mode` 设为 `'plan'`，改变工具调用的权限判定逻辑
2. **注入式指令** — 在用户消息中附加合成的 `plan_mode` 指令块，告诉模型"你现在只能读和规划，不能动手"

关键设计：**工具列表完全不变**。模型在 plan mode 下看到的工具和 agent mode 一模一样，控制完全靠权限层和 prompt 指令。

### 2.2 进入/退出机制

Claude Code 提供三条进入 plan mode 的路径：

| 路径 | 触发方式 | 入口 |
|------|---------|------|
| Shift+Tab 循环 | 用户按键 | `PromptInput.tsx` |
| `/plan` 命令 | 用户输入 | `commands/plan/plan.tsx` |
| 模型自主调用 | `EnterPlanModeTool` | `tools/EnterPlanModeTool/` |

三条路径最终都执行相同的核心逻辑：

```
handlePlanModeTransition(oldMode, 'plan')
prepareContextForPlanMode(context)    // 把旧 mode 存到 prePlanMode
setAppState: mode = 'plan'
```

退出由 `ExitPlanModeV2Tool` 控制，恢复 `prePlanMode` 保存的旧模式。

### 2.3 三层工具权限控制

Plan mode 没有集中白名单，而是通过三层机制共同决定：

**第 1 层：`isReadOnly` 标记**

所有标记了 `isReadOnly: true` 的工具无条件可用（约 19 个，如 FileReadTool、GlobTool、GrepTool 等）。

**第 2 层：写文件走权限判定链**

```
deny rules?                           → 拒绝
isSessionPlanFile(path)?              → 自动允许（plan 文件例外）
.claude/** session rule?              → 允许
安全路径检查（.git、config 等）       → 拒绝危险路径
ask rules?                            → 弹框询问用户
allow rules?                          → 允许
默认                                  → 弹框询问用户
```

关键是 `isSessionPlanFile()` — plan 文件是 plan mode 下**唯一自动放行**的可写文件。

**第 3 层：Bash 命令级验证**

Plan mode 下 BashTool 没有特殊分支，走主权限流程，最终弹框询问。

### 2.4 Prompt 注入机制

Claude Code 不修改 system prompt，而是通过 attachment 系统在用户消息中注入指令块：

- `plan_mode` attachment — 包含完整的 5 阶段工作流指引
- `plan_mode_reentry` — 用户拒绝计划后重新进入时注入
- `plan_mode_exit` — 退出后告诉模型"你现在可以动手了"

### 2.5 Task 系统与 Plan Mode 的关系

这是一个重要发现：**Plan mode 和 Task 系统在代码层面是完全正交的**。

| 维度 | Plan Mode | Task 系统（V2） |
|------|-----------|----------------|
| 存储 | Markdown 文件 `~/.claude/plans/` | JSON 文件 `~/.claude/tasks/` |
| 用途 | 规划阶段的只读约束 + 计划文档 | 执行阶段的任务跟踪 |
| 数据结构 | 自由格式 Markdown | 结构化 JSON（id, status, blocks, owner） |

两者的"联动"完全靠自然语言提示，没有自动化的"plan → tasks"转换：

- `ExitPlanMode` 的返回文本提示 "Start with updating your todo list if applicable"
- `TaskCreateTool` 的 prompt 建议 "Plan mode - When using plan mode, create a task list to track the work"

Claude Code 有两代任务工具（V1 `TodoWriteTool` 是内存存储的简单列表替换，V2 `TaskCreate/Update/List` 是文件存储的带依赖关系的 CRUD），但都与 plan mode 无直接代码关联。

---

## 3. miniclaw 的设计决策

基于对 Claude Code 的分析和 miniclaw 的教育定位，我们做了以下选择：

### 3.1 进入方式：仅靠 tool call，模型主动进入

不加 `/plan` 斜杠命令，`enter_plan_mode` / `exit_plan_mode` 是进出的唯一方式。通过 tool description 中的 prompt 引导，模型遇到复杂任务时应**主动**进入 plan mode，不必等用户提醒。

### 3.2 工具限制：软约束

工具列表不变（模型始终看到全部 8 个工具），但 `execute_tool` 在 plan mode 下拦截写操作并返回拒绝消息。这与 Claude Code 的设计一致 — 不隐藏工具，靠权限层控制。

### 3.3 Plan 目录：多文件、模型自主命名

- Plan 文件存放在 `.miniclaw/plans/` 目录下，整个目录在 plan mode 下写入豁免
- 模型可以自由创建多个 plan 文件并自主命名（如 `refactor-api.md`、`add-auth.md`）
- 每个 plan 文件要求包含 Context / Steps / Verification 三个部分
- Steps 部分必须使用 `- [ ]` / `- [x]` 格式的 todo list
- 退出 plan mode 后，提示模型在执行过程中逐步更新 todo 状态

这样 plan 文件同时充当**规划文档**和**轻量任务跟踪器**，不需要单独的 Task 工具。

### 3.4 退出审批：prompt 驱动的自然对话

模型在完成 plan 后，不通过代码强制弹窗要求用户输入 y/n，而是通过 `exit_plan_mode` 的 tool description 引导模型在调用退出前**主动向用户展示计划并询问是否可以开始执行**。用户在对话中自然确认或提出修改意见，模型据此决定是否调用 exit_plan_mode。

这种"prompt 驱动"的软性方式比 `input()` 强制审批体验更自然、更智能。

### 3.5 不做的事情

| 不做 | 原因 |
|------|------|
| `/plan` 斜杠命令 | 仅靠 tool call 进出，更简洁 |
| `input()` 强制审批 | 改用 prompt 引导模型自然对话确认，体验更好 |
| `prePlanMode` 模式快照 | 只有 agent/plan 两个模式，无需复杂恢复 |
| 独立的 Task 工具 | plan 文件的 todo list 已足够，且 Claude Code 中 task 与 plan 也是正交的 |
| 修改 system prompt | 指令通过 tool result 和 tool description 注入，更简洁且更容易理解原理 |

---

## 4. 实现方案

### 4.1 架构总览

```
用户输入
  │
  ▼
_repl_loop (cli.py)
  │  创建 context = {"mode": "agent", "plan_dir": "...", "workspace_root": "..."}
  │
  ▼
run_turn_with_tools (api.py)  ← 透传 context
  │
  ▼
MiniMax API (LLM)
  │  返回 tool_calls
  ▼
execute_tool (tools.py)  ← 透传 context
  │
  ├── tool == enter_plan_mode?
  │     ├── mode 已是 plan? → 拒绝（嵌套守卫）
  │     └── 设置 mode='plan'，返回规划指令
  │
  ├── tool == exit_plan_mode?
  │     ├── mode 不是 plan? → 拒绝
  │     └── 设置 mode='agent'，返回执行指令 + todo 更新提醒
  │
  ├── tool ∈ {read, glob, grep}?
  │     └── 正常执行（任何 mode 都允许）
  │
  └── tool ∈ {write, edit, bash}?
        ├── mode != plan → 正常执行
        └── mode == plan
              ├── 写入目标在 plans/ 目录内? → 允许（豁免）
              └── 否 → 返回拒绝消息
```

### 4.2 代码结构

```
miniclaw/
├── config.py          # 常量 + resolve_path（tools 和 plan_mode 共享）
├── tools.py           # 6 个基础工具 handler + execute_tool 分发 + schema
├── plan_mode.py       # plan mode 逻辑：权限检查、enter/exit handler、schema
├── api.py             # API 调用 + tool-call 循环（透传 context）
└── cli.py             # REPL 主循环（创建 context、显示 mode）
```

### 4.3 状态管理

REPL 层创建一个 `context` dict，通过函数签名链透传：

```python
# cli.py
plan_dir = os.path.join(workspace, ".miniclaw", "plans")
context = {"mode": "agent", "plan_dir": plan_dir, "workspace_root": workspace}
```

```
cli._repl_loop
  └─→ api.run_turn_with_tools(..., context=context)
        └─→ api._execute_tool_call(..., context=context)
              └─→ tools.execute_tool(..., context=context)
```

### 4.4 两个 Plan Mode 工具

#### enter_plan_mode

- 参数：无
- 嵌套守卫：`mode == "plan"` 时拒绝，返回 JSON error
- 行为：`context["mode"] = "plan"`
- 返回 tool result 包含：规则说明、工作流程、plan 文件格式示例
- **tool description 引导**：模型遇到复杂/多步骤任务应主动进入，不必等用户要求

#### exit_plan_mode

- 参数：无
- 守卫：`mode != "plan"` 时拒绝
- 行为：`context["mode"] = "agent"`
- 返回 tool result 包含：执行规范、todo 更新提醒（每完成一步用 edit 将 `- [ ]` 改为 `- [x]`）
- **tool description 引导**：调用前必须先向用户展示计划并获得明确同意

### 4.5 写操作拦截

`execute_tool` 中在分发到具体 handler 之前，先过 `check_plan_mode` 检查：

```python
READONLY_TOOLS = frozenset({"read", "glob", "grep", "enter_plan_mode", "exit_plan_mode"})
```

判定链：
1. `mode != "plan"` → 通过（agent mode 无限制）
2. `name ∈ READONLY_TOOLS` → 通过
3. `_is_plan_dir_write(name, args, context)` → 通过（plans 目录豁免）
4. 其他 → 返回拒绝消息

### 4.6 Plan 目录豁免

`_is_plan_dir_write` 检查写入目标路径是否在 `context["plan_dir"]` 目录内（前缀匹配）：

```python
def _is_plan_dir_write(name, args, context):
    # 仅对 write/edit 检查
    # resolve_path 后判断 abs_target.startswith(abs_plan_dir + os.sep)
```

plans 目录在 agent mode 下也正常可写，因为模型在执行阶段需要更新 todo list。

### 4.7 REPL 模式显示

```python
mode_label = " [plan]" if context["mode"] == "plan" else ""
user_input = input(f"你{mode_label}: ").strip()
```

`/clear` 时同步重置 `context["mode"] = "agent"`。

### 4.8 plan 文件格式

```markdown
# Plan: [标题]

## Context
[简述背景和目标]

## Steps
- [ ] 步骤 1: ...
- [ ] 步骤 2: ...
- [ ] 步骤 3: ...

## Verification
[如何验证变更是正确的]
```

模型可在 `.miniclaw/plans/` 下创建任意数量的 plan 文件，文件名自定。执行过程中，模型逐步将 `- [ ]` 改为 `- [x]`，plan 文件成为一个**活文档**。

---

## 5. 与 Claude Code 的对应关系

| miniclaw | Claude Code | 说明 |
|----------|-------------|------|
| `enter_plan_mode` tool | `EnterPlanModeTool` | 进入 plan mode |
| `exit_plan_mode` tool | `ExitPlanModeV2Tool` | 退出 plan mode |
| `_is_plan_dir_write()` | `isSessionPlanFile()` | plan 写入豁免（目录级 vs 文件级） |
| `check_plan_mode()` | `checkWritePermissionForTool()` | 写操作拦截 |
| tool result + tool description | `plan_mode` / `plan_mode_exit` attachment | Prompt 注入 |
| `context["mode"]` | `toolPermissionContext.mode` | 模式状态 |
| plan 文件的 todo list | Task 系统（正交，prompt 桥接） | 任务跟踪 |
| tool description 引导确认 | `input()` 弹框 / UI 审批 | 退出审批 |

miniclaw 用约 150 行 Python（`plan_mode.py`）实现了 Claude Code 约 500 行 TypeScript 的 plan mode 核心逻辑，保留了关键设计思想：

- 模型自主进出（tool call 控制，prompt 引导主动进入）
- 软约束（不隐藏工具，权限层拦截）
- Prompt 注入（通过 tool result 和 tool description 引导行为）
- Plan 目录豁免（唯一可写区域）
- 对话式审批（prompt 驱动，非强制 input）

---

## 6. 涉及文件

| 文件 | 职责 |
|------|------|
| `miniclaw/plan_mode.py` | plan mode 全部逻辑：权限检查、enter/exit handler、tool schema |
| `miniclaw/tools.py` | 基础工具 handler + execute_tool 分发（从 plan_mode 导入） |
| `miniclaw/config.py` | 常量 + `resolve_path`（tools 和 plan_mode 共享） |
| `miniclaw/api.py` | context 参数透传 |
| `miniclaw/cli.py` | context 初始化（含 plan_dir）、REPL 模式显示 |
| `tests/test_tools.py` | plan mode 单元测试 |

---

## 7. 测试覆盖

| 测试类 | 覆盖场景 |
|--------|---------|
| `TestEnterPlanMode` | 正常进入、嵌套拒绝 |
| `TestExitPlanMode` | 正常退出、非 plan 模式拒绝 |
| `TestIsPlanDirWrite` | write/edit 到 plans 目录识别、嵌套子目录、非 plans 的 .miniclaw 路径拒绝、其他文件不匹配、bash 不匹配 |
| `TestCheckPlanMode` | agent 模式全放行、plan 模式只读放行、plans 目录豁免（多文件）、写/bash/edit 拦截 |
| `TestExecuteToolPlanMode` | 集成测试：拦截、豁免（含多文件写入）、进出 roundtrip、嵌套拒绝 |
