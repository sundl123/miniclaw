# Sub-Agent 设计文档

> 本文记录 miniclaw **同步 Sub-Agent** 功能的设计结论，作为后续实现的参考。
> 调研材料见 Claude Code 仓库 `docs/subagent-implementation.md`。

**状态**：已实现（v1，默认关闭）
**创建日期**：2026-07-27
**最后更新**：2026-07-27

---

## 1. 背景与目标

### 1.1 问题

主 Agent 在做复杂 coding 任务时，经常需要：

- **大范围调研**（找文件、读实现、对比调用链）——中间过程会塞满上下文
- **相对独立的子任务**（例如「只查 auth 相关代码并汇报」）——父 Agent 并不需要每一步 tool 轨迹

若不做隔离，调研轨迹会长期占用主对话窗口，触发更早的 compact，也干扰后续推理。

### 1.2 目标

| 目标 | 含义 |
|------|------|
| **上下文隔离** | 子任务的中间 tool 轨迹不进入父 messages；父只收到最终报告 |
| **角色化** | 至少支持 general（可写）与 explore（只读调研） |
| **简洁** | 复用现有 `run_turn_with_tools`，不做 fork / async / teammate |
| **可插拔** | `subagent.enabled` feature flag，**默认关闭**；验证成熟后再默认开启 |
| **安全** | 禁止递归 spawn；Explore 不能写；继承 plan mode |

### 1.3 非目标（v1 明确不做）

- 异步后台 Agent / `<task-notification>`
- Fork（继承父对话全文 + prompt cache 对齐）
- 并行执行同一轮多个 Agent tool_call
- 自定义 agents 目录（`.miniclaw/agents/`）
- Teammate / Coordinator / git worktree 隔离
- Sub-agent resume、handoff 安全分类器、专属 MCP
- 子轨迹 sidechain 持久化（可后补；v1 以 UI + dev log 可见即可）

---

## 2. 参考：Claude Code 怎么做，以及为什么

Claude Code 的 Sub-Agent 本质是：**主 Agent 通过 `Agent` 工具，在同进程内再跑一轮独立的 `query()` 循环**。入口在 `src/tools/AgentTool/`，执行引擎是 `runAgent.ts`。

下面按能力拆解其做法与动机；miniclaw 的取舍见 §3。

### 2.1 入口是 Tool，不是新进程

**做法**：`AgentTool.call()` 接收 `description` / `prompt` / `subagent_type` / `run_in_background` 等参数，解析 Agent 定义后调用 `runAgent()`。

**为什么**：

- 模型已熟悉 tool-calling；把「委派」做成普通工具，编排成本最低
- 同进程共享权限框架、workspace、UI，不必维护 IPC
- 子循环与主循环共用同一套 `query()`，行为一致、可测

### 2.2 Sync vs Async

**做法**：

- Sync：父 turn 阻塞，结束后 `finalizeAgentTool()` 把最终文本当 tool_result 返回
- Async：注册 `LocalAgentTask`，后台跑完后 `enqueueAgentNotification`，父侧用 `<task-notification>` 感知

**为什么**：

- Sync 适合短、确定的子任务，语义简单（一次 tool_call ↔ 一次结果）
- Async 适合长任务与「先发出去再继续想」；但需要任务表、通知协议、权限提示规避（后台无法弹 UI）等一整套基础设施

### 2.3 多种 Agent 类型 + 工具过滤

**做法**：内置 General / Explore / Plan / Verification 等；`resolveAgentTools()` + `disallowedTools` 裁剪工具。Explore 去掉 Edit/Write/Agent，并可 `omitClaudeMd` 省 token。

**为什么**：

- **角色约束 > 仅靠 prompt**：只读调研若仍暴露 Write，模型仍可能误改
- Explore 高频（文档称千万级 spawn），省略 CLAUDE.md / git status 有显著 token 收益
- Plan 等专用 agent 绑定特定工作流，降低主 Agent 自行拼 prompt 的负担

### 2.4 Fork：省略 `subagent_type` 时继承全文

**做法**：`buildForkedMessages()` 克隆父 assistant（含 tool_use），为每个 tool_use 填**相同** placeholder `tool_result`，再追加各自 directive。配合 `useExactTools` 保持工具定义字节一致，以命中 prompt cache。用 boilerplate 标签 + `querySource` 防递归 fork。

**为什么**：

- 研究类任务若每次从零 brief，父要把大量上下文抄进 `prompt`，又慢又贵
- Fork 让子 Agent「已经在房间里」；并行多个 fork 时前缀相同 → cache 命中
- 这是 Anthropic API 计费/延迟结构下的**产品级优化**，实现成本高，且与协调者模式互斥

### 2.5 上下文与权限隔离

**做法**：`createSubagentContext()` 独立 `agentId`、消息列表、abortController；可覆盖 permission mode；async 默认避免权限弹窗；可选 worktree。

**为什么**：

- 防止子 Agent 污染父状态（todos、hooks、文件读缓存策略等）
- 异步无法交互时必须自动拒绝/规避权限提示
- Worktree 解决「并行改同一仓库」的冲突——属于多 agent 产品形态，不是最小委派所必需

### 2.6 结果回传

**做法**：`finalizeAgentTool()` 抽取最后一条（或最近一条有文本的）assistant 文本；父**不**把子中间轨迹并入主 transcript。

**为什么**：

- 委派的核心价值就是「父上下文只留摘要」
- 完整轨迹仍可写 sidechain，供 UI / resume / 审计使用

### 2.7 对 miniclaw 的启示（摘要）

| Claude Code 能力 | 对小 harness 的价值 | v1 是否采纳 |
|------------------|---------------------|-------------|
| Agent 作为 tool + 递归 query 循环 | **核心**，几乎零额外引擎 | ✅ |
| Sync 阻塞回传 | 语义清晰，无任务系统 | ✅ |
| Explore 只读角色 | coding 场景极有用，实现成本低 | ✅ |
| General 可写角色 | 覆盖「独立小改动」 | ✅ |
| Async / notification | 重；miniclaw 无任务 UI | ❌ |
| Fork + cache 对齐 | 重；且依赖特定 API cache 行为 | ❌ |
| 自定义 agents / MCP / teammate | 可后置 | ❌ |
| Sidechain 持久化 / resume | 可后置 | ❌（v1 后补） |

---

## 3. miniclaw 决策与动机

以下每条均为讨论结论；实现时以此为准。

### 3.1 Feature flag，默认关闭

**决策**：

```json
"subagent": {
  "enabled": false,
  "max_turns": 300
}
```

- `enabled: false`（默认）：不向模型暴露 `Agent` tool schema，行为与今日完全一致
- 验证成熟后，再把 `default_config.json` 改为 `true`（与早期 memory 的 opt-in 策略一致）

**动机**：Sub-Agent 会改变模型编排习惯与费用结构（一次用户 turn 可能触发多轮子循环）。默认关闭可本地/小流量验证，避免未成熟行为影响所有用户。

### 3.2 仅 Sync；同一轮多个 Agent 先串行

**决策**：

- 只实现同步：`Agent` tool_call 返回前子循环必须结束
- 父 `run_turn_with_tools` 对多个 tool_calls **保持现有串行 for 循环**；不在 v1 对 Agent 做线程/异步并行

**动机**：

- Claude 做 Async 是因为长任务 + 产品级任务面板；miniclaw 没有等价基础设施
- 串行已能验证「隔离上下文 + 回传摘要」这一核心价值
- 并行会引入 UI 交错、workspace 写冲突、共享 `context` 线程安全等问题，适合作为明确的 follow-up

### 3.3 不做 Fork；子 Agent 从零上下文启动

**决策**：

- 子 messages = `[system', user(prompt)]`
- 父对话历史**不**复制给子 Agent
- 主 Agent 必须在 `prompt` 里写完整 brief（像向刚进门的同事交代任务）

**动机**：

- Fork 的主要收益是 prompt cache；miniclaw 面向多模型/OpenAI 兼容接口，不能假设与 Claude 相同的 cache 前缀规则
- 从零启动实现简单、行为可预测，也强制主 Agent 写出可复查的任务说明
- 日后若某一 provider 证明 cache 收益极大，再单开「fork 实验」分支，不堵在 v1 路径上

### 3.4 Agent 类型：general + explore

**决策**：v1 内置两种（均由 `subagent_type` 选择；缺省 `general`）：

| Type | 工具 | 典型用途 |
|------|------|----------|
| `general` | 父可用工具 − `Agent`（见 §3.6） | 独立小任务、可读写 |
| `explore` | `read` / `grep` / `glob` / `bash`（只读约束）/ `Skill` | 代码库调研、定位文件与符号 |

Explore 的 bash 复用 plan mode 的只读判定（`is_readonly_bash` + 配置扩展 pattern），`write` / `edit` / `Agent` / `memory` / `session_search` / plan 进出工具均不可用。

**动机**：

- Explore 对 coding agent **几乎刚需**，且相对 general 只是工具裁剪 + 一小段只读 system 约束，复杂度低
- 工具层强制只读，比「prompt 里写不要改文件」更可靠（对齐 Claude Explore 的 `disallowedTools` 思路）
- Plan 专用 agent、Verification 等可后置；主 Agent 已有 plan mode

### 3.5 System prompt：复用父 system + worker 约束

**决策**：

- 子 Agent system = **父当前 system prompt 全文** + 追加一小段 worker 指令
- Explore 额外追加只读约束说明（与工具裁剪双保险）

Worker 指令要点（实现时可微调文案）：

1. 你是子任务 worker，不是主对话角色
2. 不要反问用户；信息不足则在报告中列出假设与缺口
3. 直接使用工具；结束后用简洁报告收尾（发现 / 关键文件 / 未解决问题）
4. 禁止尝试委派更多 sub-agent（工具层已禁用，prompt 再强调）

**动机**：

- 复用父 system 可继承 workspace、日期、skills 元数据列表等，避免子 Agent「失明」
- 单独维护第二套完整 system 成本高、易漂移
- 追加 worker 段纠正「继续跟用户聊天」的倾向，贴近 Claude fork boilerplate 的「报告一次就停」精神，但不做繁重 XML 模板

### 3.6 工具与深度限制

**决策**：

| 规则 | 说明 |
|------|------|
| 深度 | `agent_depth` 最大为 **1**（仅主 → 子）；子 schema **不含** `Agent` |
| general 工具 | 父当前 tools − `Agent`；**不含** `memory`、`session_search`（见下） |
| explore 工具 | `read` / `grep` / `glob` / `bash` / `Skill`；bash 走只读检查 |
| plan mode | 子 Agent **继承**父 `context["mode"]`；父在 plan 时子也受写拦截 |
| max_turns | 子循环 tool 迭代上限，默认 `subagent.max_turns`（建议 300） |

关于 **memory / session_search**：

- v1 **不提供**给子 Agent
- 长期记忆与跨会话检索由主 Agent 在委派前/后处理；子 Agent 专注单次 brief

**动机**：

- 禁 `Agent` + depth=1：防止递归爆炸与费用失控（Claude 对内置 agent 也普遍禁 Agent / 用 fork guard）
- 禁 memory 写入面：避免子任务把未经主 Agent 审视的内容写入 MEMORY.md
- 禁 session_search：减少子 Agent 偏离 brief、去「翻聊天记录」；实现面也更小
- 继承 plan mode：否则 plan 中 spawn general 会绕过只读规划阶段

### 3.7 与 Skill 的边界

| | Skill | Agent（Sub-Agent） |
|--|-------|-------------------|
| 作用 | 把流程/说明注入**当前**对话 | 开**隔离**循环，父只见摘要 |
| 上下文 | 占用父窗口 | 不占用父中间轨迹 |
| 何时用 | 「按某技能步骤做」 | 「调研/子任务别弄脏我的上下文」 |

二者并存：general/explore 仍可调用 `Skill` 加载技能正文。

### 3.8 UI 与可观测性

**决策（最小可用）**：

- 进入子循环时打印一行前缀，例如 `↳ Agent[explore]: <description>`
- 子循环内 tool 调用相对父缩进（或带 `agent` 标记）
- 结束时打印 `← Agent done (…s, N tools)` 及回传摘要长度等
- 详细请求可走现有 `dev_logging`

**动机**：没有缩进时，嵌套 tool 输出无法阅读；完整 sidechain 文件可后补。

### 3.9 结果契约

**决策**：`Agent` tool 返回 JSON 字符串（与其他工具一致），建议字段：

```json
{
  "status": "completed",
  "agent_type": "explore",
  "description": "…",
  "result": "<子 Agent 最终文本>",
  "tool_use_count": 4,
  "duration_ms": 12345
}
```

失败（超 max_turns、abort、API 错误）时 `status` 为 `failed` / `truncated`，并带 `error`；尽可能附带已收集的部分文本。

**动机**：结构化便于父模型引用，也便于测试断言；与 Claude `finalizeAgentTool` 抽取文本的思路一致，但用 JSON 更贴合 miniclaw 现有 tool 风格。

---

## 4. 架构与实现落点

### 4.1 调用链

```
用户 turn
  └─ run_turn_with_tools (父)
        └─ tool_calls 串行
              └─ Agent(description, prompt, subagent_type?)
                    ├─ 检查 subagent.enabled / agent_depth
                    ├─ 解析 AgentDefinition (general | explore)
                    ├─ 构建 child_system / child_tools / child_context
                    ├─ run_turn_with_tools (子, max_turns)
                    └─ 打包 JSON → 父 messages 的 tool role
```

### 4.2 建议模块

```
miniclaw/
  subagent/
    __init__.py
    config.py          # SubagentConfig + get_subagent_config()
    types.py           # AgentDefinition: general / explore
    prompt.py          # worker / explore 追加段
    runner.py          # 组装 child 并调用 run_turn_with_tools
    tool.py            # schema + handle_agent
  tools.py             # get_tool_schemas(include_agent=…)；execute_tool 分发
  api.py               # 可选：支持 max_turns；context 透传 llm 句柄
  cli.py               # context 注入 client/model/tools/system_prompt；读 flag
  settings.py          # 合并 subagent 配置
  default_config.json  # subagent.enabled: false
```

### 4.3 关键实现细节

1. **LLM 句柄透传**  
   今日 `execute_tool` 无 `client`/`model`。推荐在 REPL `context` 中放入：

   ```python
   context["llm"] = {
       "client": client,
       "model": model,
       "timeout": timeout,
       "tools": tools,              # 父完整 schema 列表
       "system_prompt": system_prompt,
       "context_config": context_config,
   }
   context["agent_depth"] = 0
   ```

   `handle_agent` 从 context 取用，避免 `api ↔ tools` 循环依赖。

2. **子 tools 计算**  
   - 从父 schema 列表按 name 过滤，而不是重新 `get_tool_schemas()` 后再减——以便与父当前 flag（memory/sessions 是否开启）一致，再额外去掉 `memory` / `session_search` / `Agent`。  
   - Explore：再白名单到只读集合。

3. **max_turns**  
   在 `run_turn_with_tools` 增加可选 `max_turns: int | None = None`；子调用传入配置值；达到上限时结束循环并返回已有内容 + truncated 状态。

4. **Explore bash**  
   在 `handle_bash` 或子 context 标记 `readonly_bash_only=True`，复用 `plan_mode.is_readonly_bash`（注意：父在 agent mode 时 Explore 仍要强制只读，不能仅依赖 `context["mode"]=="plan"`）。

5. **Schema 暴露**  
   `get_tool_schemas(..., include_agent=subagent_cfg.enabled and agent_depth == 0)`；子循环 `include_agent=False`。

### 4.4 Tool schema（草案）

```text
Agent
  description: string   # 3–10 词，UI / log 用
  prompt: string        # 完整任务 brief（子看不到父对话）
  subagent_type: "general" | "explore"   # 可选，默认 general
```

向主 Agent 说明（可写在 tool description 或 system 附言，仅当 flag 开启时注入）：

- 需要**大范围只读调研**时用 `explore`，避免污染主上下文
- 需要**隔离的可写子任务**时用 `general`，并在 prompt 中给足背景
- 子 Agent 看不到本对话；brief 必须自洽

---

## 5. 配置

`~/.miniclaw/config.json` 与 `{workspace}/.miniclaw/config.json` 合并（workspace 优先），新增：

```json
"subagent": {
  "enabled": false,
  "max_turns": 300
}
```

| 字段 | 默认 | 含义 |
|------|------|------|
| `enabled` | `false` | 是否向**主** Agent 暴露 `Agent` 工具 |
| `max_turns` | `300` | 子循环内「模型响应且含 tool_calls」的最大轮数 |

环境变量（可选，实现阶段再定是否需要）：`MINICLAW_SUBAGENT=1` 覆盖开启，便于测试而不改配置文件。

---

## 6. 测试计划（实现时）

| 用例 | 期望 |
|------|------|
| `enabled=false` | schema 无 `Agent`；模型无法调用 |
| `enabled=true`，general | 子可 read；最终 JSON `status=completed` 且含 `result` |
| explore 调用 write/edit | 工具不可用或明确错误；文件未改 |
| explore 危险 bash（如 `rm`） | 拒绝 |
| 子 Agent 再调 Agent | schema 无此工具；若强行 execute 则拒绝 |
| 父在 plan mode spawn general | 子写操作仍被 plan 拦截 |
| 达到 max_turns | `truncated`，不死循环 |
| 同一父响应两个 Agent tool_calls | 串行执行，两个 tool_result 皆返回 |

优先单测：`runner` 工具过滤、depth 守卫、explore bash、flag 开关；再补 1–2 个 mock LLM 的集成测试。

---

## 7. 后续可能（非 v1）

按优先级粗排：

1. **同一轮 Agent 并行**（仅 explore 或只读任务）——真正「分而治之」
2. **子轨迹 sidechain**（独立 jsonl / records 字段）——审计与 `/resume` 子任务
3. **自定义 agent 定义**（markdown frontmatter，类似 skills）
4. **Async + 通知**——仅当 REPL 有明确任务 UX 时再做
5. **Fork / cache 实验**——仅当默认模型的 cache 行为证明值得

---

## 8. 决策一览表

| 议题 | Claude Code | miniclaw v1 | 动机（我们） |
|------|-------------|-------------|--------------|
| 形态 | Agent tool + 同进程 query | 同左，复用 `run_turn_with_tools` | 最小引擎增量 |
| Sync / Async | 两者皆有 | **仅 Sync** | 无任务系统；先验证核心价值 |
| 并行 tool_calls | 产品侧大量并行 | **串行** | 先跑通；避免竞态 |
| Fork | 有（cache 优化） | **无** | 实现重；多模型 cache 假设弱 |
| 类型 | 多种内置 + 自定义 | **general + explore** | Explore 对 coding 价值高且便宜 |
| System | 各类型自建 / fork 继承 | **父 system + worker 段** | 少漂移、继承 workspace/skills |
| memory / session_search | 视 agent 定义 | **子 Agent 不提供** | 防污染、缩小 v1 面 |
| 递归 | 工具黑名单 + fork guard | **depth≤1，去掉 Agent** | 简单硬限制 |
| 持久化 | sidechain + metadata | **v1 不做** | UI/log 足够调试 |
| 开关 | 编译期 feature / GrowthBook | **`subagent.enabled` 默认 false** | 成熟后再默认开 |

---

## 9. 实现检查清单（供开工用）

- [x] `SubagentConfig` + `settings.get_subagent_config` + `default_config.json`
- [x] `miniclaw/subagent/`：types / prompt / runner / tool
- [x] `get_tool_schemas(include_agent=…)` + `execute_tool` 分发
- [x] `cli.py` context 注入 `llm` + `agent_depth`
- [x] `run_turn_with_tools(..., max_turns=)`
- [x] Explore 只读 bash 强制
- [x] UI 缩进 / 起止日志
- [x] 单元测试（上表）
- [ ] 手动：开启 flag 后用 explore 查一个真实小仓库并确认父上下文未被中间 grep 填满

---

以上为讨论冻结的设计结论。实现若需偏离，应先更新本文「决策与动机」再改代码。
