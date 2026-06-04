"""技能目录扫描、注册表与 system prompt 构建。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from miniclaw.config import get_local_iso_date
from miniclaw.dirs import get_user_data_dir

_BASE_DIR_PREFIX = "Base directory for this skill: {dir}\n\n"


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


def strip_frontmatter(content: str) -> str:
    """去掉 YAML frontmatter，返回正文。"""
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", content, re.DOTALL)
    if match:
        return content[match.end():]
    return content


def normalize_skill_name(name: str) -> str:
    """规范化 skill 名称，兼容 /commit 写法。"""
    return (name or "").strip().lstrip("/")


@dataclass
class SkillEntry:
    name: str
    description: str
    skill_dir: str
    skill_md_path: str
    source: str  # "global" | "project"


class SkillRegistry:
    """已发现的 skill 注册表。"""

    def __init__(self, entries: dict[str, SkillEntry] | None = None):
        self._entries = dict(entries or {})

    def lookup(self, name: str) -> SkillEntry | None:
        return self._entries.get(normalize_skill_name(name))

    def list_metadata(self) -> list[dict]:
        return [
            {
                "name": e.name,
                "description": e.description,
                "source": e.source,
            }
            for e in sorted(self._entries.values(), key=lambda x: x.name)
        ]

    def skill_dirs(self) -> frozenset[str]:
        return frozenset(e.skill_dir for e in self._entries.values())

    def load_skill_body(self, name: str) -> str:
        """读取 SKILL.md 正文，剥离 frontmatter 并注入 Base directory 前缀。"""
        entry = self.lookup(name)
        if entry is None:
            raise KeyError(name)
        with open(entry.skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        body = strip_frontmatter(content).lstrip("\n")
        return _BASE_DIR_PREFIX.format(dir=entry.skill_dir) + body


def _scan_skills_dir(skills_dir: str, source: str) -> dict[str, SkillEntry]:
    """扫描单个 skills 目录，返回 name -> SkillEntry。"""
    result: dict[str, SkillEntry] = {}
    if not os.path.isdir(skills_dir):
        return result
    for dir_name in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, dir_name)
        if not os.path.isdir(skill_dir):
            continue
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        meta = parse_frontmatter(content)
        name = meta.get("name") or dir_name
        result[name] = SkillEntry(
            name=name,
            description=meta.get("description", "(无描述)"),
            skill_dir=os.path.abspath(skill_dir),
            skill_md_path=os.path.abspath(skill_md),
            source=source,
        )
    return result


def discover_skills(workspace: str) -> SkillRegistry:
    """扫描全局与项目 skill 目录；同名时 project 覆盖 global。"""
    global_dir = os.path.join(get_user_data_dir(), "skills")
    project_dir = os.path.join(workspace, ".miniclaw", "skills")
    entries = _scan_skills_dir(global_dir, "global")
    entries.update(_scan_skills_dir(project_dir, "project"))
    return SkillRegistry(entries)


def scan_skills_metadata(skills_dir: str) -> list[dict]:
    """扫描 skills 目录，返回 [{"name": "...", "description": "..."}, ...]。"""
    entries = _scan_skills_dir(skills_dir, "project")
    return [
        {"name": e.name, "description": e.description}
        for e in sorted(entries.values(), key=lambda x: x.name)
    ]


def build_system_prompt(skill_metadata_list: list[dict], *, workspace_root: str = None) -> str:
    """根据技能元数据列表拼接 system prompt。"""
    env_lines = ""
    path_hint = "文件工具（read/write/edit/grep/glob）的 path 必须使用绝对路径。"
    if workspace_root:
        env_lines = (
            f"\n当前工作区目录：{workspace_root}\n"
            f"当前日期：{get_local_iso_date()}\n"
        )
        path_hint = (
            "文件工具（read/write/edit/grep/glob）的 path 必须使用绝对路径。"
            f" workspace 内文件以 {workspace_root} 为前缀；"
            "skill reference 以 Skill 加载后的 Base directory 为前缀。"
        )
    lines = [
        "你是助手，可以使用提供的工具来完成任务。",
        env_lines,
        "## 技能（Skills）",
        "当任务与某个 skill 的描述匹配时，必须先调用 Skill 工具加载，再按 skill 正文执行。",
        "不要跳过 Skill 工具直接回答。",
        path_hint,
        "",
        "## 当前可用技能列表",
    ]
    if skill_metadata_list:
        for s in skill_metadata_list:
            lines.append(f"- {s['name']}: {s['description']}")
    else:
        lines.append("（暂无可用 skill）")
    return "\n".join(lines)
