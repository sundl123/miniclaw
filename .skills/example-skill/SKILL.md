---
name: example-skill
description: 测试用技能，用于验证通过 code-execution-tool 读取本文件并按说明执行简单文件与 bash 操作。
---

# Example Skill（示例技能）

本技能用于在 miniclaw 中测试「模型通过工具访问 .skills 目录」的流程。

## 何时使用

- 用户想了解有哪些可用技能、或想测试技能能力时，可先阅读本 SKILL.md。
- 用户要求「按 example-skill 做一个小示例」时，可按下方步骤执行。

## 使用方式

1. **查看本文件**：你已通过 `view_file` 读取到本 SKILL.md。
2. **可选**：若需要输出模板，可用 `view_file` 查看 `.skills/example-skill/assets/template.md`。
3. **简单示例**：可用 `create_file` 在工作区根下创建 `hello_skill.txt`，内容为一行：`Hello from example-skill.`
4. **或执行 bash**：用 `run_bash` 执行 `echo "example-skill OK"`，将输出返回给用户。

## 目录结构

```
.skills/example-skill/
├── SKILL.md          # 本文件
└── assets/
    └── template.md   # 可选模板
```

按需读取，无需一次全部加载（渐进式披露）。
