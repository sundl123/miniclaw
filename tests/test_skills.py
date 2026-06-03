"""技能扫描与 system prompt 的单元测试。"""
import os
import tempfile
import unittest

import miniclaw.dirs as dirs_mod
from miniclaw.skills import (
    SkillRegistry,
    build_system_prompt,
    discover_skills,
    normalize_skill_name,
    parse_frontmatter,
    scan_skills_metadata,
    strip_frontmatter,
)


class TestParseFrontmatter(unittest.TestCase):
    def test_empty_content(self):
        self.assertEqual(parse_frontmatter(""), {})

    def test_no_frontmatter(self):
        self.assertEqual(parse_frontmatter("hello world"), {})

    def test_valid_frontmatter(self):
        content = """---
name: my-skill
description: A test skill
---
Body here"""
        self.assertEqual(parse_frontmatter(content), {"name": "my-skill", "description": "A test skill"})

    def test_quoted_description(self):
        content = '''---
name: x
description: "Hello \\"quoted\\""
---'''
        self.assertEqual(parse_frontmatter(content)["description"], 'Hello "quoted"')


class TestStripFrontmatter(unittest.TestCase):
    def test_strips_block(self):
        content = "---\nname: x\n---\n\nHello body"
        self.assertEqual(strip_frontmatter(content), "Hello body")

    def test_no_frontmatter_unchanged(self):
        self.assertEqual(strip_frontmatter("plain text"), "plain text")


class TestNormalizeSkillName(unittest.TestCase):
    def test_strips_slash(self):
        self.assertEqual(normalize_skill_name("/commit"), "commit")

    def test_plain_name(self):
        self.assertEqual(normalize_skill_name("commit"), "commit")


class TestScanSkillsMetadata(unittest.TestCase):
    def test_nonexistent_dir(self):
        result = scan_skills_metadata("/nonexistent/skills/dir")
        self.assertEqual(result, [])

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = scan_skills_metadata(d)
        self.assertEqual(result, [])

    def test_scan_one_skill(self):
        with tempfile.TemporaryDirectory() as d:
            skill_dir = os.path.join(d, "foo")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: foo\ndescription: Foo skill\n---\n")
            result = scan_skills_metadata(d)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "foo")
        self.assertEqual(result[0]["description"], "Foo skill")


class TestDiscoverSkills(unittest.TestCase):
    def setUp(self):
        self._orig_user_data_dir = dirs_mod.USER_DATA_DIR
        self._tmpdir = tempfile.mkdtemp()
        dirs_mod.USER_DATA_DIR = self._tmpdir

    def tearDown(self):
        dirs_mod.USER_DATA_DIR = self._orig_user_data_dir
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_skill(self, base: str, dir_name: str, name: str, desc: str, body: str = "Body"):
        skill_dir = os.path.join(base, dir_name)
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {name}\ndescription: {desc}\n---\n{body}")

    def test_global_and_project(self):
        with tempfile.TemporaryDirectory() as workspace:
            global_skills = os.path.join(self._tmpdir, "skills")
            project_skills = os.path.join(workspace, ".miniclaw", "skills")
            self._write_skill(global_skills, "g1", "g1", "Global one")
            self._write_skill(project_skills, "p1", "p1", "Project one")

            registry = discover_skills(workspace)
            names = {m["name"] for m in registry.list_metadata()}
            self.assertEqual(names, {"g1", "p1"})

    def test_project_overrides_global(self):
        with tempfile.TemporaryDirectory() as workspace:
            global_skills = os.path.join(self._tmpdir, "skills")
            project_skills = os.path.join(workspace, ".miniclaw", "skills")
            self._write_skill(global_skills, "shared", "shared", "Global desc", "Global body")
            self._write_skill(project_skills, "shared", "shared", "Project desc", "Project body")

            registry = discover_skills(workspace)
            entry = registry.lookup("shared")
            self.assertEqual(entry.description, "Project desc")
            self.assertEqual(entry.source, "project")
            body = registry.load_skill_body("shared")
            self.assertIn("Project body", body)
            self.assertIn(entry.skill_dir, body)


class TestLoadSkillBody(unittest.TestCase):
    def test_base_directory_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            skill_dir = os.path.join(d, "foo")
            os.makedirs(skill_dir)
            md_path = os.path.join(skill_dir, "SKILL.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("---\nname: foo\ndescription: d\n---\n# Title\n\nDo work.")
            from miniclaw.skills import SkillEntry
            registry = SkillRegistry({
                "foo": SkillEntry(
                    name="foo",
                    description="d",
                    skill_dir=os.path.abspath(skill_dir),
                    skill_md_path=md_path,
                    source="project",
                ),
            })
            body = registry.load_skill_body("foo")
            self.assertTrue(body.startswith(f"Base directory for this skill: {os.path.abspath(skill_dir)}"))
            self.assertIn("# Title", body)
            self.assertNotIn("name: foo", body)


class TestSkillDirs(unittest.TestCase):
    def test_skill_dirs_returns_frozenset(self):
        from miniclaw.skills import SkillEntry
        registry = SkillRegistry({
            "a": SkillEntry("a", "A", "/tmp/a", "/tmp/a/SKILL.md", "global"),
            "b": SkillEntry("b", "B", "/tmp/b", "/tmp/b/SKILL.md", "project"),
        })
        dirs = registry.skill_dirs()
        self.assertEqual(dirs, frozenset({"/tmp/a", "/tmp/b"}))


class TestBuildSystemPrompt(unittest.TestCase):
    def test_empty_list(self):
        out = build_system_prompt([])
        self.assertIn("当前可用技能列表", out)
        self.assertIn("暂无", out)
        self.assertIn("Skill", out)
        self.assertNotIn("~/.miniclaw", out)

    def test_with_skills(self):
        meta = [
            {"name": "a", "description": "A", "source": "global"},
            {"name": "b", "description": "B", "source": "project"},
        ]
        out = build_system_prompt(meta)
        self.assertIn("- a: A", out)
        self.assertIn("- b: B", out)
        self.assertNotIn("[global]", out)
        self.assertNotIn("[project]", out)
        self.assertNotIn("~/.miniclaw", out)

    def test_without_workspace_root(self):
        out = build_system_prompt([])
        self.assertNotIn("当前工作区目录", out)

    def test_with_workspace_root(self):
        out = build_system_prompt([], workspace_root="/tmp/my-workspace")
        self.assertIn("当前工作区目录：/tmp/my-workspace", out)


if __name__ == "__main__":
    unittest.main()
