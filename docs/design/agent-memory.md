# Agent 记忆系统设计文档

> 本文记录 miniclaw **跨会话持久记忆**功能的设计结论，作为后续实现的参考。

**状态**：Phase 1 已实现
**创建日期**：2026-06-05
**最后更新**：2026-06-22

---

## Phase 1 实现（当前）

全局 auto memory，目录 `~/.miniclaw/memory/`。

| 组件 | 行为 |
|------|------|
| **MEMORY.md** | 唯一大小受限（默认 25KB + 200 行）；启动时 **frozen** 注入 system prompt |
| **其他文件 / 子目录** | 不限大小；模型自管；仅经 `memory` tool 读写 |
| **memory tool** | `read` / `write` / `edit` / `list` / `delete` / `status` |
| **预算反馈** | 写 MEMORY.md 前 preflight；成功/失败均返回 `memory_md_usage`；≥80% 软 warning |

`memory_md_usage` 字段：`used_bytes` / `limit_bytes` / `used_lines` / `limit_lines`、
`bytes_percent` / `lines_percent`（0–100）、`display`（人类可读摘要，如 `42% — 8.5/25.0 KB, 120/200 lines`）。
| **防御** | 磁盘超限 → 启动截断注入；禁止 delete MEMORY.md |
| **CLI** | `memory.enabled` 开关；`/memory` 或 `/memory-status` |

配置（`config.json`）：

```json
"memory": {
  "enabled": false,
  "memory_md_max_bytes": 25600,
  "memory_md_max_lines": 200,
  "warn_threshold_pct": 80
}
```

代码：`miniclaw/memory/`（`store.py`, `budget.py`, `tool.py`, …）

Phase 1 **未做**：records、/reflect、AGENTS.md 加载、auto-skill。

---

## 1. 背景

当前 miniclaw 每次启动都是"白板"：用户必须重新介绍项目、风格、偏好，反复重新解释同样的信息。这让 agent 更像一个"短期外包助理"，而不是一个**长期共事的搭档**。

我们希望 miniclaw 能：
- 越用越"懂"用户
- 不再需要重复解释相同内容
- 成为真正有记忆的工作伙伴

但**模型本身没有长期记忆**。所有"记忆"都是应用层在外部维护，并按需重新注入到 context window。本文档设计的就是这个**外部记忆层**。

---

## 2. 设计目标

| 目标 | 含义 |
|---|---|
| **零负担** | 用户不需要主动管理记忆，全由 agent 自主维护 |
| **跨会话** | 重启后能接上次的进度、风格、上下文 |
| **可插拔** | 一个 config 开关，能用就开、不好用就关（实验性 feature） |
| **自我迭代** | agent 能从经验中沉淀 skill，避免重复踩坑 |
| **简单** | 符合 miniclaw "minimal & hackable" 的精神，不过度抽象 |

---

## 3. 核心架构：三层脑启发模型

记忆系统分为**三个层次**，模仿人脑的记忆类型：

```
┌──────────────────────────────────────────────────────┐
│  Layer 3: SKILLS（程序性记忆）                         │
│  "坑→方案" 的可复用结晶                                │
├──────────────────────────────────────────────────────┤
│  Layer 2: MEMORY（语义性记忆 + 自我反思）                │
│  对 Layer 1 的消化产物，会随时间演化                     │
│  "我观察到"、"我反思到"、"我现在认为…"                    │
├──────────────────────────────────────────────────────┤
│  Layer 1: RECORDS（事件性记忆 / 原始 log）              │
│  对话原文、操作、决策 — append-only，原始可信            │
└──────────────────────────────────────────────────────┘
   ↑ 触发条件：心跳（默认每天 1 次）
   ↑ 抽取方向：Record → Memory → Skill（自下而上凝聚）
```

### 3.1 三层映射

| 层级 | 人脑对应 | 物理位置 | 写入频率 |
|---|---|---|---|
| Records | 海马体 / 情景记忆 | `~/.miniclaw/records/*.jsonl` | 实时（每条消息） |
| Memory | 皮层 / 语义记忆 | `~/.miniclaw/memory/*.md` | 心跳时 |
| Skills | 小脑 / 程序性记忆 | `~/.miniclaw/skills/auto/*.md` | 心跳时（按需） |

### 3.2 关键设计原则

#### 原则 1：Records vs Memory 严格分离

| 维度 | Records | Memory |
|---|---|---|
| 本质 | 事件的原始 log | 从 log 中提炼的理解 |
| 可变性 | **不可变**，append-only | **可变**，持续演化 |
| 粒度 | 细：每条消息、每次操作 | 粗：模式、偏好、洞察 |
| 时间观 | 锚定"那一刻" | "现在我认为…" |
| 出错时 | 永远可信，可回溯 | 可能失真，需要修正 |

> **Records 是 source of truth，Memory 是 derived state。**

#### 原则 2：模型主导组织

- ❌ **不预设**数据 schema
- ❌ **不预设**分类体系
- ❌ **不预设**反思模板
- ✅ 模型自己决定如何组织、何时遗忘、如何提炼

人类的角色是**提供舞台**（机制、存储、心跳），演员（模型）自己决定怎么演。

#### 原则 3：无 gate

- 任何环节都不强制用户审视或确认
- 用户"如果感兴趣的话"可以查看，但默认不打扰
- 需要时再加（YAGNI 原则）

---

## 4. 心跳机制：每天一次"睡眠式整理"

### 4.1 设计要点

| 维度 | 决定 |
|---|---|
| 频率 | **每天 1 次**（默认 24h 一次） |
| 触发 | 定时任务 + CLI 手动触发（如 `/reflect`） |
| 时机 | 模拟"人脑睡眠巩固"——离线、低频、不打扰 |
| Prompt | 极简，**只给目标不给路径** |

### 4.2 心跳 Prompt（设计原则）

```
你现在有机会整理自己的 memory 和 skills。
目的是成为一个最好的助手。
memory 和 skill 具体怎么整理，你自己决定。
```

—— 这就是完整的 prompt。**给目标，不给路径**。

### 4.3 心跳可做的事（不强制）

| 职责 | 含义 | 频率/成本 |
|---|---|---|
| 📥 消化 | 把新 record 转成 memory | 每次必做 |
| 🔄 整合 | 检查已有 memory 是否过时/冲突，更新 | 每次必做 |
| 🌱 提 skill | 看是否有"坑→方案"的稳定模式，写成 skill | 偶尔 |
| 🧹 遗忘 | 长期未用、价值低的 memory 主动降权/删除 | 偶尔 |
| 🤔 反思元层 | 反思自己的反思方式、记忆组织是否合理 | 极少 |

> 模型自己决定哪些做、哪些不做。

---

## 5. 物理存储结构

```
~/.miniclaw/                          (per-user, machine-local)
├── config.json
│   └── memory.enabled = false        ← 默认关闭，opt-in
│
├── records/                          ← Layer 1: 原始 log
│   ├── 2026-06-05_session_01.jsonl
│   ├── 2026-06-05_session_02.jsonl
│   └── ...
│
├── memory/                           ← Layer 2: 消化后的记忆
│   ├── MEMORY.md                     ← 索引（启动时加载，限 N 字节）
│   ├── project-miniclaw.md           ← 主题参考文件（按需加载）
│   ├── user-style.md
│   ├── decision-patterns.md
│   └── ...                           ← 模型自创
│
└── skills/                           ← Layer 3: 程序性技能
    ├── (user-installed)/             ← 用户装的，原样不动
    └── auto/                         ← 模型自己生成的
        ├── debug-flaky-tests.md
        └── ...
```

### 5.1 关键设计要点

1. **完全 per-user**（`~/.miniclaw/memory/`）
   - 不区分 workspace，"懂你"是关于这个人，不是这个项目
   - 跨 workspace 共享知识
   - 简单清晰，不引入双层复杂度

2. **MEMORY.md 作为索引入口**
   - 每次启动加载到 system prompt
   - 限定 N 字节（参考 Claude Code auto-memory：200 行 / 25KB）
   - 内含参考文件的索引/链接，模型可按需加载

3. **auto-skill 物理隔离**
   - 模型生成的 skill 单独放在 `skills/auto/`
   - 不污染用户安装的 skill
   - 信任边界清楚

---

## 6. Records 详细设计

### 6.1 内容策略：**全量 + 摘要**

| 方案 | 优 | 劣 |
|---|---|---|
| 全量 raw log | 简单、完整 | 有冗余、占空间 |
| 关键事件流 | 精炼 | 容易漏 |
| **全量 + 摘要** ✅ | 完整、可压缩 | 贵一点 |

> 先全量存，再做摘要。**后面再优化**。

### 6.2 写入时机：**实时**

- 每条消息 / 每个 tool call 写一次
- 简单、crash-safe
- **IO 频率问题后面再优化**（可考虑 batch / append buffer）

### 6.3 存储格式：**JSONL**

```jsonl
{"ts": "2026-06-05T10:00:00", "role": "user", "content": "..."}
{"ts": "2026-06-05T10:00:05", "role": "assistant", "content": "...", "tool_calls": [...]}
{"ts": "2026-06-05T10:00:10", "role": "tool", "tool_call_id": "...", "content": "..."}
{"ts": "2026-06-05T10:00:15", "role": "assistant", "content": "..."}
{"ts": "2026-06-05T23:55:00", "type": "session_summary", "summary": "..."}
```

每行一条事件，结构化、可追加、可解析。

---

## 7. Memory 详细设计

### 7.1 MEMORY.md 模板（由模型自维护，初始为空）

```markdown
# Memory Index

<!-- 这是一个索引文件，agent 启动时自动加载。 -->
<!-- 详细内容放在同目录下其他文件中，按需加载。 -->

## 关于用户
- 偏好简洁回复（@user-style.md）
- 决策倾向：先简单后完整（@decision-patterns.md）

## 当前项目
- miniclaw（@project-miniclaw.md）：Python 命令行 agent

## 常用约定
- ...（@conventions.md）

## 最近的心得
- ...（@insights-2026-06.md）
```

### 7.2 加载机制

- **MEMORY.md** — 启动时注入到 system prompt
- **参考文件**（如 `user-style.md`）— 模型用 `read` 工具按需加载
- **大小约束** — MEMORY.md 启动时控制在 N 字节 / N 行内

---

## 8. Skills 详细设计

### 8.1 auto-skill 生成流程

心跳时，模型可以：
1. 反思最近 N 天遇到的问题及解决方案
2. 发现"稳定模式"（多次重复 + 通用解法）
3. 写入 `~/.miniclaw/skills/auto/<name>/SKILL.md`

### 8.2 SKILL.md 格式

与现有 skill 格式一致（YAML frontmatter + 正文）：

```markdown
---
name: debug-flaky-tests
description: 排查 Go 集成测试中偶发失败的步骤
---

# Debug Flaky Tests

## 触发场景
测试偶发失败，重试后通过

## 排查步骤
1. ...
2. ...
```

### 8.3 加载策略

- 当前 Miniclaw 的 skill 机制：扫描 `~/.miniclaw/skills/` 所有 SKILL.md，提取元数据注入 system prompt
- auto-skill 复用同一机制，模型生成后**下次启动即生效**
- **未来需考虑**：auto-skill 数量膨胀时的治理（暂不做）

---

## 9. 配置

### 9.1 config.json 字段

```json
{
  "memory": {
    "enabled": false,
    "heartbeat_interval_hours": 24,
    "memory_md_size_limit_kb": 25,
    "memory_md_line_limit": 200,
    "records_retention_days": null,
    "auto_skill_enabled": true
  }
}
```

| 字段 | 默认 | 含义 |
|---|---|---|
| `enabled` | `false` | **总开关**，关掉则完全回到无记忆的 miniclaw |
| `heartbeat_interval_hours` | `24` | 心跳间隔 |
| `memory_md_size_limit_kb` | `25` | MEMORY.md 启动加载大小上限 |
| `memory_md_line_limit` | `200` | MEMORY.md 启动加载行数上限 |
| `records_retention_days` | `null` | records 保留天数（null=永久） |
| `auto_skill_enabled` | `true` | 是否允许自动生成 skill |

### 9.2 CLI 命令

```bash
miniclaw --memory-status        # 查看记忆系统状态
miniclaw --reflect              # 手动触发一次心跳
miniclaw --memory-list          # 列出所有记忆文件
miniclaw --memory-view <name>   # 查看某个记忆文件
```

---

## 10. 实现要点

### 10.1 模块划分

建议新增模块（参考现有 `miniclaw/context/` 结构）：

```
miniclaw/
└── memory/                       ← 新增
    ├── __init__.py
    ├── config.py                 # 记忆系统配置加载
    ├── records.py                # records 写入、读取、归档
    ├── store.py                  # memory/ 目录操作
    ├── heartbeat.py              # 心跳调度与执行
    ├── prompt.py                 # 心跳 prompt 构造
    └── cli.py                    # CLI 命令入口
```

### 10.2 接入点

1. **chat.py 启动时**
   - 读 `config.json` 的 `memory.enabled`
   - 启用时把 `MEMORY.md` 注入 system prompt
   - 启动后台 heartbeat 调度器

2. **api.py 处理 tool call 后**
   - 实时把对话事件 append 到当前 session 的 jsonl 文件

3. **cli.py**
   - 注册 `--reflect`、`--memory-status` 等命令

### 10.3 MVP 范围

**Phase 1（已完成）**

- [x] `config.memory.enabled` 开关
- [x] `~/.miniclaw/memory/MEMORY.md` frozen 注入
- [x] `memory` tool（路径 sandbox + MEMORY.md preflight + usage 反馈）
- [x] topic 文件与子目录不限大小
- [x] `/memory-status`

**Phase 2（计划中）**

- [ ] records JSONL
- [ ] `/reflect` heartbeat
- [ ] auto-skill 生成

---

## 11. 未来工作（已识别但暂不做）

| 议题 | 说明 | 触发条件 |
|---|---|---|
| **Heartbeat gate** | 当 auto-skill 质量不稳定时，引入轻量 gate | 模型生成低质 skill 多次 |
| **可信链 / 引用追踪** | memory 关联到具体 record，便于审计 | 用户开始怀疑 memory 准确性 |
| **存储后端抽象** | 支持 SQLite / 向量库 | records 量爆炸，文件 IO 成瓶颈 |
| **多节奏心跳** | 区分"快速整理"和"深度反思" | 单次心跳时间过长 |
| **Per-workspace memory** | workspace 级独立 memory | 用户在不同项目语境差异巨大 |
| **跨机器同步** | 记忆在多台设备间同步 | 用户多设备工作 |
| **遗忘机制** | 自动降权 / 删除长期未用 memory | memory/ 膨胀失控 |

---

## 12. 设计哲学总结

本次设计的几条核心信条：

1. **"记录 vs 记忆"严格分离** — append-only log + 可变 derived state
2. **"成为最好的助手"** — 给目标，不给路径
3. **最简洁的框架** — 不预设 schema、不预设分类、不预设反思模板
4. **可插拔 = 一个开关** — 不造框架，能用就用、不好用就关
5. **每天一次"睡眠式整理"** — 模仿人脑，巩固而非频繁处理
6. **零负担** — 用户只需要偶尔"巡视"，不参与管理

---

## 13. 附录：相关参考

### 13.1 Claude / Anthropic 的做法

- [Memory tool - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) — 文件系统级 memory 原语
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — Compaction / Note-taking / Sub-agent 设计
- [How Claude remembers your project - Claude Code Docs](https://code.claude.com/docs/en/memory) — CLAUDE.md + Auto Memory 双轨设计

### 13.2 认知科学对应

| 设计元素 | 人脑对应 |
|---|---|
| records（append-only log） | 海马体 / episodic memory |
| 心跳（每日整理） | 睡眠中的 replay & consolidation |
| memory/（语义化笔记） | 皮层 / semantic memory |
| skills/auto/（程序性技能） | 小脑 / procedural memory |
| MEMORY.md 索引 | 工作记忆的"指针表" |

### 13.3 现有 Miniclaw 上下文管理

参考 `miniclaw/context/`：
- `manage.py` — context window 管理
- `micro_compact.py` — 会话内微压缩
- `summarize.py` — 摘要生成
- `tokens.py` — token 计数

> 本设计**不替代**这些模块，而是在其上层构建**跨会话**的持久化能力。
