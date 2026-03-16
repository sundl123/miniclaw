"""技能扫描与 system prompt 的单元测试。"""
import os
import tempfile
import unittest

from miniclaw.skills import parse_frontmatter, scan_skills_metadata, build_system_prompt


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


class TestBuildSystemPrompt(unittest.TestCase):
    def test_empty_list(self):
        out = build_system_prompt([])
        self.assertIn("当前可用技能列表", out)
        self.assertIn("暂无", out)

    def test_with_skills(self):
        meta = [{"name": "a", "description": "A"}, {"name": "b", "description": "B"}]
        out = build_system_prompt(meta)
        self.assertIn("- a: A", out)
        self.assertIn("- b: B", out)
        self.assertIn(".skills", out)


if __name__ == "__main__":
    unittest.main()
