"""技能目录扫描与 system prompt 构建。"""
import os
import re


def parse_frontmatter(content: str) -> dict:
    """从 SKILL.md 内容中解析 YAML frontmatter，返回 name、description 等。"""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    block = match.group(1)
    data = {}
    for line in block.split("\n"):
        m = re.match(r"^(\w+):\s*(.*)$", line.strip())
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"')
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1].replace("\\'", "'")
            data[key] = val
    return data


def scan_skills_metadata(skills_dir: str) -> list[dict]:
    """扫描 skills 目录，返回 [{"name": "...", "description": "..."}, ...]。"""
    result = []
    if not os.path.isdir(skills_dir):
        return result
    for name in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, name)
        if not os.path.isdir(path):
            continue
        skill_md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        meta = parse_frontmatter(content)
        result.append({
            "name": meta.get("name") or name,
            "description": meta.get("description", "(无描述)"),
        })
    return result


def build_system_prompt(skill_metadata_list: list[dict], *, workspace_root: str = None) -> str:
    """根据技能元数据列表拼接 system prompt。"""
    workspace_line = ""
    if workspace_root:
        workspace_line = f"\n当前工作区目录：{workspace_root}\n"
    lines = [
        "你是助手，可以使用提供的工具来完成任务。",
        workspace_line,
        "## 技能（Skills）的访问方式",
        "技能存放在工作区的 .miniclaw/skills 目录中。",
        "每个技能对应一个子目录，例如 .miniclaw/skills/<skill_name>/。",
        "目录内必有 SKILL.md，描述该技能的用途与使用方式；可能还有 assets/ 等子目录存放模板或脚本。",
        "当你认为用户需求可能涉及某技能时，应先用 read 查看对应 .miniclaw/skills/<skill_name>/SKILL.md，再根据 SKILL.md 的说明决定是否执行 bash 或读写其他文件。",
        "",
        "## 当前可用技能列表（自动从 .miniclaw/skills 扫描）",
    ]
    if skill_metadata_list:
        for s in skill_metadata_list:
            lines.append(f"- {s['name']}: {s['description']}")
    else:
        lines.append("（暂无，可在 .miniclaw/skills 下添加技能目录及 SKILL.md）")
    return "\n".join(lines)
