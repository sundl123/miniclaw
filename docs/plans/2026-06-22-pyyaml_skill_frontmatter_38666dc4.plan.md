---
name: PyYAML skill frontmatter
overview: "用 PyYAML 替换 miniclaw 中简陋的 frontmatter 行解析，修复 firecrawl 等 skill 的 `description: |` / `>-` 多行 YAML 被解析成 `|` 的问题，并补充单元测试。"
todos:
  - id: add-pyyaml-dep
    content: 在 pyproject.toml 与 requirements.txt 添加 pyyaml>=6.0.2,<7
    status: completed
  - id: rewrite-parse-frontmatter
    content: 用 yaml.safe_load 重写 parse_frontmatter，并加 _meta_str 规范化 name/description
    status: completed
  - id: add-tests
    content: 在 tests/test_skills.py 补充块标量/折叠标量/坏 YAML/扫描集成测试
    status: completed
  - id: run-tests
    content: make test 确认全绿，并抽查 firecrawl skill 描述注入正确
    status: completed
isProject: false
---

# 用 PyYAML 修复 Skill description 解析

## 问题回顾

[`miniclaw/skills.py`](file:///Users/sundongliang/Projects/miniclaw/miniclaw/skills.py) 的 `parse_frontmatter()` 用逐行正则只认 `key: value` 单行格式。firecrawl 等 skill 使用标准 YAML 块标量：

```yaml
description: |
  Extract clean markdown from any URL...
```

结果被解析为 `description="|"`，注入 system prompt 后模型无法按描述匹配 skill。

```mermaid
flowchart LR
  SKILL_md["SKILL.md frontmatter"] --> parse["parse_frontmatter"]
  parse --> registry["_scan_skills_dir"]
  registry --> prompt["build_system_prompt"]
  prompt --> model["LLM skill routing"]
```

## 方案（推荐，已确认）

- 引入 **PyYAML**，版本约束：`pyyaml>=6.0.2,<7`
- **不新增 lock 文件**（与 miniclaw 现状一致）
- 仅改 frontmatter 解析层；`strip_frontmatter` / `load_skill_body` 逻辑不变

## 实现步骤

### 1. 添加依赖

同步更新两处（miniclaw 目前双轨维护）：

- [`pyproject.toml`](file:///Users/sundongliang/Projects/miniclaw/pyproject.toml) `dependencies` 增加 `pyyaml>=6.0.2,<7`
- [`requirements.txt`](file:///Users/sundongliang/Projects/miniclaw/requirements.txt) 增加同一行

### 2. 重写 `parse_frontmatter()`

文件：[`miniclaw/skills.py`](file:///Users/sundongliang/Projects/miniclaw/miniclaw/skills.py)

```python
import yaml

def parse_frontmatter(content: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
```

要点：
- 用 `safe_load` 处理 `|`、`>`、`>-`、引号转义、列表字段（如 `allowed-tools`）
- YAML 语法错误时返回 `{}`（与「无 frontmatter」一致），避免脏数据进入注册表
- 删除手写引号剥离逻辑（由 PyYAML 接管）

### 3. 规范化 `name` / `description` 取值

在 `_scan_skills_dir()` 内对 meta 做轻量 coerce（仅这两字段被下游使用）：

```python
def _meta_str(meta: dict, key: str, default: str = "") -> str:
    val = meta.get(key, default)
    if val is None:
        return default
    if not isinstance(val, str):
        val = str(val)
    return val.strip() or default
```

- `name`：`_meta_str(meta, "", "")` 为空时回退 `dir_name`（保持现有行为）
- `description`：`_meta_str(meta, "description", "(无描述)")`

这样 `>-` 折叠标量、多行 `|` 都会变成完整单行/多行字符串，不再出现 `|>` 字面量。

### 4. 补充测试

文件：[`tests/test_skills.py`](file:///Users/sundongliang/Projects/miniclaw/tests/test_skills.py)

在 `TestParseFrontmatter` 新增用例（保留现有 3 个测试，应全部继续通过）：

| 用例 | 覆盖 |
|------|------|
| `test_block_scalar_pipe` | `description: \|` + 缩进多行 |
| `test_folded_scalar_strip` | `description: >-` + 折行合并 |
| `test_folded_scalar_gt` | `description: >` |
| `test_extra_yaml_keys` | frontmatter 含 `allowed-tools:` 列表时，`description` 仍正确 |
| `test_invalid_yaml_returns_empty` | 坏 YAML → `{}` |

在 `TestScanSkillsMetadata` 新增：

- `test_scan_multiline_description`：临时目录写入 firecrawl 风格 SKILL.md，`scan_skills_metadata` 返回完整 description 而非 `|`

### 5. 验证

```bash
cd /Users/sundongliang/Projects/miniclaw
pip3 install -e .   # 或 make dev
make test           # python3 -m pytest tests/ -v
```

手动抽查（可选）：启动 miniclaw 后看 system prompt / 日志，firecrawl 系列应显示完整英文描述，不再是 `- firecrawl: |`。

## 不在本次范围

- 不引入 `uv.lock` / `poetry.lock`
- 不修改用户 `~/.miniclaw/skills/` 下的 skill 文件内容
- 不做 description 长度截断（system prompt 膨胀是独立优化项）

## 风险与回退

- **风险**：极个别 frontmatter 若含非标准 YAML，以前可能「部分解析」，现在会整段 `{}`；对 skill 生态可接受（无 name 则仍用目录名）
- **回退**：移除 PyYAML 依赖并恢复旧 `parse_frontmatter` 即可
