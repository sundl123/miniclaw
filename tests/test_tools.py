"""工具模块的单元测试。"""
import json
import os
import tempfile
import unittest

from miniclaw.config import resolve_glob_pattern, resolve_path, resolve_read_path
from miniclaw.tools import (
    handle_read,
    handle_write,
    handle_edit,
    handle_glob,
    handle_grep,
    handle_bash,
    handle_skill,
    execute_tool,
    get_tool_schemas,
)
from miniclaw.plan_mode import (
    handle_enter_plan_mode,
    handle_exit_plan_mode,
    _is_plan_dir_write,
    check_plan_mode,
    is_readonly_bash,
)
from miniclaw.settings import load_workspace_config, get_plan_allowed_patterns
from miniclaw.tools_config import ReadToolConfig, ToolsConfig
from miniclaw.skills import SkillEntry, SkillRegistry


class TestResolvePath(unittest.TestCase):
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as root:
            p = resolve_path("a/b.txt", root)
            self.assertEqual(p, os.path.join(root, "a", "b.txt"))

    def test_escape_forbidden(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                resolve_path("../../../etc/passwd", root)

    def test_absolute_workspace_path(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "docs", "report.md")
            resolved = resolve_path(target, root)
            self.assertEqual(resolved, os.path.normpath(target))

    def test_absolute_outside_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                resolve_path("/etc/passwd", root)


class TestResolveReadPath(unittest.TestCase):
    def test_absolute_workspace_path(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("x")
            resolved = resolve_read_path(p, root)
            self.assertEqual(resolved, os.path.normpath(p))

    def test_registered_skill_dir_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.md")
                with open(ref, "w") as f:
                    f.write("ref")
                resolved = resolve_read_path(
                    ref, root, registered_skill_dirs=frozenset({skill_dir}),
                )
                self.assertEqual(resolved, os.path.normpath(ref))

    def test_unregistered_skill_dir_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.md")
                with open(ref, "w") as f:
                    f.write("ref")
                with self.assertRaises(PermissionError):
                    resolve_read_path(ref, root)

    def test_outside_workspace_and_skill_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                with tempfile.TemporaryDirectory() as other:
                    secret = os.path.join(other, "secret.txt")
                    with open(secret, "w") as f:
                        f.write("secret")
                    with self.assertRaises(PermissionError):
                        resolve_read_path(
                            secret, root, registered_skill_dirs=frozenset({skill_dir}),
                        )


class TestResolveGlobPattern(unittest.TestCase):
    def test_relative_pattern_uses_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            full, base = resolve_glob_pattern("**/*.py", root)
            self.assertEqual(base, os.path.normpath(root))
            self.assertEqual(full, os.path.join(root, "**/*.py"))

    def test_absolute_pattern_in_registered_skill_dir(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                pattern = os.path.join(skill_dir, "**", "*.md")
                full, base = resolve_glob_pattern(
                    pattern, root, registered_skill_dirs=frozenset({skill_dir}),
                )
                self.assertEqual(full, pattern)
                self.assertEqual(base, os.path.normpath(skill_dir))


class TestHandleSkill(unittest.TestCase):
    def _make_registry(self, skill_dir: str, name: str = "demo") -> SkillRegistry:
        md = os.path.join(skill_dir, "SKILL.md")
        return SkillRegistry({
            name: SkillEntry(
                name=name,
                description="Demo",
                skill_dir=os.path.abspath(skill_dir),
                skill_md_path=md,
                source="global",
            ),
        })

    def test_load_skill_body(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                md = os.path.join(skill_dir, "SKILL.md")
                with open(md, "w") as f:
                    f.write("---\nname: demo\ndescription: d\n---\n# Demo skill")
                ctx = {"skill_registry": self._make_registry(skill_dir)}
                out = handle_skill({"skill": "/demo"}, root, context=ctx)
                self.assertIn("Base directory for this skill:", out)
                self.assertIn("# Demo skill", out)

    def test_read_registered_skill_without_load(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.txt")
                with open(ref, "w") as f:
                    f.write("reference content")
                ctx = {"skill_registry": self._make_registry(skill_dir)}
                read_out = handle_read({"path": ref}, root, context=ctx)
                self.assertIn("reference content", read_out)

    def test_read_unregistered_skill_dir_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.txt")
                with open(ref, "w") as f:
                    f.write("secret")
                ctx = {"skill_registry": SkillRegistry()}
                out = handle_read({"path": ref}, root, context=ctx)
                self.assertIn("error", json.loads(out))

    def test_grep_in_registered_skill_dir(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.txt")
                with open(ref, "w") as f:
                    f.write("findme here\n")
                ctx = {"skill_registry": self._make_registry(skill_dir)}
                out = handle_grep(
                    {"pattern": "findme", "path": skill_dir}, root, context=ctx,
                )
                self.assertIn("findme", out)

    def test_glob_in_registered_skill_dir(self):
        with tempfile.TemporaryDirectory() as root:
            with tempfile.TemporaryDirectory() as skill_dir:
                ref = os.path.join(skill_dir, "ref.md")
                with open(ref, "w") as f:
                    f.write("x")
                pattern = os.path.join(skill_dir, "*.md")
                ctx = {"skill_registry": self._make_registry(skill_dir)}
                out = handle_glob({"pattern": pattern}, root, context=ctx)
                self.assertIn("ref.md", out)

    def test_unknown_skill(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {"skill_registry": SkillRegistry()}
            out = handle_skill({"skill": "missing"}, root, context=ctx)
            data = json.loads(out)
            self.assertIn("error", data)
            self.assertIn("missing", data["error"])


class TestHandleRead(unittest.TestCase):
    def test_read_file(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("line1\nline2\nline3\n")
            out = handle_read({"path": "f.txt"}, root)
            self.assertIn("1|line1", out)
            self.assertIn("2|line2", out)
            self.assertIn("3|line3", out)

    def test_read_with_offset_limit(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("a\nb\nc\nd\n")
            out = handle_read({"path": "f.txt", "offset": 1, "limit": 2}, root)
            self.assertNotIn("1|", out)
            self.assertIn("2|b", out)
            self.assertIn("3|c", out)
            self.assertNotIn("4|", out)

    def test_read_missing_file(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_read({"path": "nope.txt"}, root)
            self.assertIn("error", json.loads(out))

    def test_read_missing_path(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_read({}, root)
            self.assertIn("error", json.loads(out))

    def test_read_rejects_oversized_file_without_limit(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "big.txt")
            with open(p, "wb") as f:
                f.write(b"x" * 300_000)
            cfg = ToolsConfig(read=ReadToolConfig(max_file_bytes=262144), max_tool_result_chars=100_000, max_glob_files=500)
            out = handle_read({"path": "big.txt"}, root, tools_cfg=cfg)
            data = json.loads(out)
            self.assertIn("error", data)
            self.assertIn("offset", data["error"].lower())

    def test_read_truncates_when_limit_set_and_output_huge(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "lines.txt")
            with open(p, "w") as f:
                for i in range(500):
                    f.write(f"line {i}: " + ("word " * 40) + "\n")
            cfg = ToolsConfig(read=ReadToolConfig(max_output_tokens=50), max_tool_result_chars=100_000, max_glob_files=500)
            out = handle_read({"path": "lines.txt", "offset": 0, "limit": 200}, root, tools_cfg=cfg)
            self.assertIn("[truncated]", out)

    def test_read_rejects_huge_output_without_limit(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "dense.txt")
            with open(p, "w") as f:
                f.write("x" * 50_000)
            cfg = ToolsConfig(read=ReadToolConfig(max_file_bytes=1_000_000, max_output_tokens=100), max_tool_result_chars=100_000, max_glob_files=500)
            out = handle_read({"path": "dense.txt"}, root, tools_cfg=cfg)
            data = json.loads(out)
            self.assertIn("error", data)


class TestHandleWrite(unittest.TestCase):
    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_write({"path": "out.txt", "content": "hello"}, root)
            self.assertIn("Successfully", out)
            with open(os.path.join(root, "out.txt")) as f:
                self.assertEqual(f.read(), "hello")

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_write({"path": "a/b/c.txt", "content": "deep"}, root)
            self.assertIn("Successfully", out)
            self.assertTrue(os.path.isfile(os.path.join(root, "a", "b", "c.txt")))

    def test_write_missing_path(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_write({"content": "x"}, root)
            self.assertIn("error", json.loads(out))

    def test_write_absolute_path(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "docs", "report.md")
            out = handle_write({"path": target, "content": "hello"}, root)
            self.assertIn("Successfully", out)
            self.assertIn(os.path.normpath(target), out)
            with open(target) as f:
                self.assertEqual(f.read(), "hello")


class TestHandleEdit(unittest.TestCase):
    def test_edit_exact_match(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("hello world")
            out = handle_edit({"path": "f.txt", "old_string": "world", "new_string": "python"}, root)
            self.assertIn("Successfully", out)
            with open(p) as f:
                self.assertEqual(f.read(), "hello python")

    def test_edit_no_match(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("hello")
            out = handle_edit({"path": "f.txt", "old_string": "xyz", "new_string": "abc"}, root)
            self.assertIn("error", json.loads(out))

    def test_edit_multiple_matches(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("aa aa aa")
            out = handle_edit({"path": "f.txt", "old_string": "aa", "new_string": "bb"}, root)
            data = json.loads(out)
            self.assertIn("error", data)
            self.assertIn("3", data["error"])

    def test_edit_missing_old_string(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("hello")
            out = handle_edit({"path": "f.txt", "old_string": "", "new_string": "x"}, root)
            self.assertIn("error", json.loads(out))

    def test_edit_absolute_path(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("hello world")
            out = handle_edit(
                {"path": p, "old_string": "world", "new_string": "python"}, root,
            )
            self.assertIn("Successfully", out)
            self.assertIn(os.path.normpath(p), out)
            with open(p) as f:
                self.assertEqual(f.read(), "hello python")


class TestHandleGlob(unittest.TestCase):
    def test_glob_finds_files(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "a.py"), "w") as f:
                f.write("")
            with open(os.path.join(root, "b.py"), "w") as f:
                f.write("")
            out = handle_glob({"pattern": "*.py"}, root)
            self.assertIn("a.py", out)
            self.assertIn("b.py", out)

    def test_glob_no_match(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_glob({"pattern": "*.xyz"}, root)
            self.assertEqual(out, "No files found")

    def test_glob_missing_pattern(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_glob({}, root)
            self.assertIn("error", json.loads(out))

    def test_glob_truncates_file_list(self):
        with tempfile.TemporaryDirectory() as root:
            for i in range(10):
                with open(os.path.join(root, f"f{i}.py"), "w") as f:
                    f.write("")
            cfg = ToolsConfig(read=ReadToolConfig(), max_tool_result_chars=100_000, max_glob_files=3)
            out = handle_glob({"pattern": "*.py"}, root, tools_cfg=cfg)
            self.assertIn(".py", out)
            self.assertIn("more files (truncated)", out)
            self.assertEqual(len(out.splitlines()), 4)  # 3 paths + truncation notice


class TestHandleGrep(unittest.TestCase):
    def test_grep_finds_match(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "f.txt"), "w") as f:
                f.write("hello world\nfoo bar\n")
            out = handle_grep({"pattern": "hello"}, root)
            self.assertIn("hello", out)

    def test_grep_no_match(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "f.txt"), "w") as f:
                f.write("abc\n")
            out = handle_grep({"pattern": "zzz"}, root)
            self.assertEqual(out, "No matches found")

    def test_grep_missing_pattern(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_grep({}, root)
            self.assertIn("error", json.loads(out))


class TestHandleBash(unittest.TestCase):
    def test_bash_echo(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_bash({"command": "echo ok"}, root)
            self.assertEqual(out.strip(), "ok")

    def test_bash_failure(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_bash({"command": "exit 1"}, root)
            self.assertIn("exit code: 1", out)

    def test_bash_missing_command(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_bash({}, root)
            self.assertIn("error", json.loads(out))


class TestExecuteTool(unittest.TestCase):
    def test_unknown_tool(self):
        out = execute_tool("nonexistent", {}, "/tmp")
        data = json.loads(out)
        self.assertIn("error", data)
        self.assertIn("未知工具", data["error"])

    def test_dispatches_bash(self):
        with tempfile.TemporaryDirectory() as root:
            out = execute_tool("bash", {"command": "echo dispatched"}, root)
            self.assertEqual(out.strip(), "dispatched")

    def test_execute_tool_caps_bash_output(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = ToolsConfig(read=ReadToolConfig(), max_tool_result_chars=500, max_glob_files=500)
            out = execute_tool(
                "bash",
                {"command": "python3 -c \"print('x' * 2000)\""},
                root,
                tools_config=cfg,
            )
            self.assertIn("[truncated]", out)
            self.assertLessEqual(len(out), 600)


class TestGetToolSchemas(unittest.TestCase):
    def test_returns_nine_tools(self):
        schemas = get_tool_schemas()
        self.assertEqual(len(schemas), 9)
        names = {s["function"]["name"] for s in schemas}
        self.assertEqual(names, {
            "read", "write", "edit", "glob", "grep", "bash", "Skill",
            "enter_plan_mode", "exit_plan_mode",
        })

    def test_all_have_function_type(self):
        for s in get_tool_schemas():
            self.assertEqual(s["type"], "function")
            self.assertIn("parameters", s["function"])


# ---------------------------------------------------------------------------
# Plan Mode 测试
# ---------------------------------------------------------------------------

class TestEnterPlanMode(unittest.TestCase):
    def test_enter_from_agent(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {"mode": "agent", "plan_dir": os.path.join(root, ".miniclaw", "plans")}
            result = handle_enter_plan_mode({}, root, ctx)
            self.assertEqual(ctx["mode"], "plan")
            self.assertIn("Plan Mode", result)
            self.assertIn("plans", result)

    def test_nested_enter_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {"mode": "plan", "plan_dir": os.path.join(root, ".miniclaw", "plans")}
            result = handle_enter_plan_mode({}, root, ctx)
            self.assertEqual(ctx["mode"], "plan")
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("嵌套", data["error"])


class TestExitPlanMode(unittest.TestCase):
    def test_exit_from_plan(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {"mode": "plan", "plan_dir": os.path.join(root, ".miniclaw", "plans")}
            result = handle_exit_plan_mode({}, root, ctx)
            self.assertEqual(ctx["mode"], "agent")
            self.assertIn("执行模式", result)
            self.assertIn("- [ ]", result)

    def test_exit_from_agent_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {"mode": "agent", "plan_dir": os.path.join(root, ".miniclaw", "plans")}
            result = handle_exit_plan_mode({}, root, ctx)
            self.assertEqual(ctx["mode"], "agent")
            data = json.loads(result)
            self.assertIn("error", data)


class TestIsPlanDirWrite(unittest.TestCase):
    def test_write_to_plan_dir(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertTrue(_is_plan_dir_write("write", {"path": ".miniclaw/plans/refactor.md"}, ctx))

    def test_write_to_plan_dir_nested(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertTrue(_is_plan_dir_write("write", {"path": ".miniclaw/plans/v2/design.md"}, ctx))

    def test_write_to_other_file(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertFalse(_is_plan_dir_write("write", {"path": "src/main.py"}, ctx))

    def test_write_to_miniclaw_but_not_plans(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertFalse(_is_plan_dir_write("write", {"path": ".miniclaw/config.json"}, ctx))

    def test_edit_in_plan_dir(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertTrue(_is_plan_dir_write("edit", {"path": ".miniclaw/plans/my-plan.md"}, ctx))

    def test_write_to_plan_dir_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            plan_file = os.path.join(plan_dir, "code-review-service-layer.md")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertTrue(_is_plan_dir_write("write", {"path": plan_file}, ctx))

    def test_bash_not_plan_dir(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            ctx = {"plan_dir": plan_dir, "workspace_root": root}
            self.assertFalse(_is_plan_dir_write("bash", {"command": "echo hi"}, ctx))


class TestCheckPlanMode(unittest.TestCase):
    def _make_ctx(self, root, mode="plan"):
        return {
            "mode": mode,
            "plan_dir": os.path.join(root, ".miniclaw", "plans"),
            "workspace_root": root,
        }

    def test_agent_mode_allows_everything(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root, "agent")
            self.assertIsNone(check_plan_mode("write", {"path": "x.py"}, ctx))
            self.assertIsNone(check_plan_mode("bash", {"command": "rm -rf /"}, ctx))

    def test_plan_mode_allows_readonly(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            for tool in ("read", "glob", "grep", "Skill", "enter_plan_mode", "exit_plan_mode"):
                self.assertIsNone(check_plan_mode(tool, {}, ctx))

    def test_plan_mode_allows_plan_dir_write(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            self.assertIsNone(
                check_plan_mode("write", {"path": ".miniclaw/plans/my-plan.md"}, ctx)
            )

    def test_plan_mode_allows_plan_dir_write_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            plan_file = os.path.join(root, ".miniclaw", "plans", "my-plan.md")
            self.assertIsNone(
                check_plan_mode("write", {"path": plan_file}, ctx)
            )

    def test_plan_mode_allows_any_file_in_plan_dir(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            self.assertIsNone(
                check_plan_mode("write", {"path": ".miniclaw/plans/feature-x.md"}, ctx)
            )
            self.assertIsNone(
                check_plan_mode("edit", {"path": ".miniclaw/plans/bugfix.md"}, ctx)
            )

    def test_plan_mode_blocks_other_write(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = check_plan_mode("write", {"path": "src/main.py"}, ctx)
            self.assertIsNotNone(result)
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("Plan Mode", data["error"])

    def test_plan_mode_allows_readonly_bash(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            self.assertIsNone(check_plan_mode("bash", {"command": "echo hi"}, ctx))
            self.assertIsNone(check_plan_mode("bash", {"command": "ls -la"}, ctx))
            self.assertIsNone(check_plan_mode("bash", {"command": "git log --oneline"}, ctx))

    def test_plan_mode_blocks_non_readonly_bash(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = check_plan_mode("bash", {"command": "rm -rf /tmp/test"}, ctx)
            self.assertIsNotNone(result)
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("只读", data["error"])

    def test_plan_mode_blocks_edit_non_plan(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = check_plan_mode("edit", {"path": "foo.py", "old_string": "a", "new_string": "b"}, ctx)
            self.assertIsNotNone(result)


class TestExecuteToolPlanMode(unittest.TestCase):
    def test_execute_tool_plan_mode_blocks_write(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {
                "mode": "plan",
                "plan_dir": os.path.join(root, ".miniclaw", "plans"),
                "workspace_root": root,
            }
            result = execute_tool("write", {"path": "x.py", "content": "hi"}, root, context=ctx)
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("Plan Mode", data["error"])

    def test_execute_tool_plan_mode_allows_read(self):
        with tempfile.TemporaryDirectory() as root:
            p = os.path.join(root, "f.txt")
            with open(p, "w") as f:
                f.write("hello\n")
            ctx = {
                "mode": "plan",
                "plan_dir": os.path.join(root, ".miniclaw", "plans"),
                "workspace_root": root,
            }
            result = execute_tool("read", {"path": "f.txt"}, root, context=ctx)
            self.assertIn("hello", result)

    def test_execute_tool_plan_mode_allows_plan_dir_write(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            os.makedirs(plan_dir)
            ctx = {
                "mode": "plan",
                "plan_dir": plan_dir,
                "workspace_root": root,
            }
            result = execute_tool("write", {"path": ".miniclaw/plans/my-plan.md", "content": "# Plan"}, root, context=ctx)
            self.assertIn("Successfully", result)
            with open(os.path.join(plan_dir, "my-plan.md")) as f:
                self.assertEqual(f.read(), "# Plan")

    def test_execute_tool_plan_mode_allows_plan_dir_write_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            os.makedirs(plan_dir)
            plan_file = os.path.join(plan_dir, "my-plan.md")
            ctx = {
                "mode": "plan",
                "plan_dir": plan_dir,
                "workspace_root": root,
            }
            result = execute_tool(
                "write", {"path": plan_file, "content": "# Plan"}, root, context=ctx,
            )
            self.assertIn("Successfully", result)
            with open(plan_file) as f:
                self.assertEqual(f.read(), "# Plan")

    def test_execute_tool_plan_mode_allows_multiple_plan_files(self):
        with tempfile.TemporaryDirectory() as root:
            plan_dir = os.path.join(root, ".miniclaw", "plans")
            os.makedirs(plan_dir)
            ctx = {
                "mode": "plan",
                "plan_dir": plan_dir,
                "workspace_root": root,
            }
            r1 = execute_tool("write", {"path": ".miniclaw/plans/step1.md", "content": "# Step 1"}, root, context=ctx)
            r2 = execute_tool("write", {"path": ".miniclaw/plans/step2.md", "content": "# Step 2"}, root, context=ctx)
            self.assertIn("Successfully", r1)
            self.assertIn("Successfully", r2)
            self.assertTrue(os.path.isfile(os.path.join(plan_dir, "step1.md")))
            self.assertTrue(os.path.isfile(os.path.join(plan_dir, "step2.md")))

    def test_execute_tool_enter_exit_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {
                "mode": "agent",
                "plan_dir": os.path.join(root, ".miniclaw", "plans"),
                "workspace_root": root,
            }
            result = execute_tool("enter_plan_mode", {}, root, context=ctx)
            self.assertEqual(ctx["mode"], "plan")
            self.assertIn("Plan Mode", result)

            result = execute_tool("exit_plan_mode", {}, root, context=ctx)
            self.assertEqual(ctx["mode"], "agent")
            self.assertIn("执行模式", result)

    def test_execute_tool_nested_enter_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = {
                "mode": "plan",
                "plan_dir": os.path.join(root, ".miniclaw", "plans"),
                "workspace_root": root,
            }
            result = execute_tool("enter_plan_mode", {}, root, context=ctx)
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertEqual(ctx["mode"], "plan")


# ---------------------------------------------------------------------------
# Bash 只读判定测试
# ---------------------------------------------------------------------------

class TestIsReadonlyBash(unittest.TestCase):
    """is_readonly_bash() 的单元测试。"""

    # --- 内置白名单命令 ---

    def test_simple_readonly_commands(self):
        for cmd in ("ls", "ls -la", "cat foo.py", "head -20 main.py",
                     "wc -l *.py", "find . -name '*.py'", "pwd", "echo hello"):
            self.assertTrue(is_readonly_bash(cmd), f"应为只读: {cmd}")

    def test_grep_and_search(self):
        self.assertTrue(is_readonly_bash("grep -rn 'def main' ."))
        self.assertTrue(is_readonly_bash("rg 'TODO' src/"))

    def test_git_readonly_subcommands(self):
        for sub in ("log", "status", "diff", "branch", "show", "tag",
                     "ls-files", "blame"):
            cmd = f"git {sub}"
            self.assertTrue(is_readonly_bash(cmd), f"应为只读: {cmd}")
        self.assertTrue(is_readonly_bash("git log --oneline -10"))
        self.assertTrue(is_readonly_bash("git diff HEAD~1"))

    def test_git_write_subcommands_blocked(self):
        for sub in ("commit", "push", "pull", "merge", "rebase",
                     "checkout", "reset", "clean", "rm"):
            cmd = f"git {sub}"
            self.assertFalse(is_readonly_bash(cmd), f"应为非只读: {cmd}")

    def test_bare_git_blocked(self):
        self.assertFalse(is_readonly_bash("git"))

    # --- 非白名单命令 ---

    def test_write_commands_blocked(self):
        for cmd in ("rm -rf /tmp/test", "mkdir new_dir", "mv a.py b.py",
                     "cp src dst", "touch new.txt", "chmod 755 script.sh"):
            self.assertFalse(is_readonly_bash(cmd), f"应为非只读: {cmd}")

    # --- 重定向检测 ---

    def test_redirect_blocked(self):
        self.assertFalse(is_readonly_bash("echo hello > out.txt"))
        self.assertFalse(is_readonly_bash("cat a.py >> all.txt"))
        self.assertFalse(is_readonly_bash("ls -la > files.txt"))

    # --- 复合命令 ---

    def test_compound_all_readonly(self):
        self.assertTrue(is_readonly_bash("ls && cat foo.py"))
        self.assertTrue(is_readonly_bash("git status && git log --oneline"))
        self.assertTrue(is_readonly_bash("echo start; ls; echo done"))
        self.assertTrue(is_readonly_bash("cat a.py | grep def | wc -l"))

    def test_compound_with_write_blocked(self):
        self.assertFalse(is_readonly_bash("ls && rm -rf /tmp"))
        self.assertFalse(is_readonly_bash("echo ok; mkdir new"))
        self.assertFalse(is_readonly_bash("git status && git commit -m 'x'"))

    # --- 边界情况 ---

    def test_empty_command(self):
        self.assertTrue(is_readonly_bash(""))
        self.assertTrue(is_readonly_bash("   "))

    def test_absolute_path_command(self):
        self.assertTrue(is_readonly_bash("/usr/bin/ls -la"))
        self.assertTrue(is_readonly_bash("/usr/bin/cat foo.txt"))

    # --- 配置文件正则扩展 ---

    def test_extra_patterns_match(self):
        import re
        pats = [re.compile(r"^firecrawl\b"), re.compile(r"^curl\s+-s")]
        self.assertTrue(is_readonly_bash("firecrawl search 'topic'", pats))
        self.assertTrue(is_readonly_bash("curl -s https://example.com", pats))

    def test_extra_patterns_no_match(self):
        import re
        pats = [re.compile(r"^firecrawl\b")]
        self.assertFalse(is_readonly_bash("wget https://example.com", pats))

    def test_extra_patterns_in_compound(self):
        import re
        pats = [re.compile(r"^firecrawl\b")]
        self.assertTrue(is_readonly_bash("ls && firecrawl search 'x'", pats))
        self.assertFalse(is_readonly_bash("firecrawl search 'x' && rm tmp", pats))


# ---------------------------------------------------------------------------
# 配置文件加载测试
# ---------------------------------------------------------------------------

class TestConfigLoading(unittest.TestCase):
    """settings.py 配置加载的单元测试。"""

    def setUp(self):
        """隔离全局配置目录，避免测试读到真实的 ~/.miniclaw/config.json。"""
        import miniclaw.dirs as dirs_mod
        self._orig_user_data_dir = dirs_mod.USER_DATA_DIR
        self._tmpdir = tempfile.mkdtemp()
        dirs_mod.USER_DATA_DIR = self._tmpdir

    def tearDown(self):
        import miniclaw.dirs as dirs_mod
        dirs_mod.USER_DATA_DIR = self._orig_user_data_dir
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_config_file(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(load_workspace_config(root), {})
            self.assertEqual(get_plan_allowed_patterns(root), [])

    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as root:
            cfg_dir = os.path.join(root, ".miniclaw")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "config.json"), "w") as f:
                json.dump({
                    "plan_mode": {
                        "allowed_bash_patterns": [r"^firecrawl\b", r"^curl\s"]
                    }
                }, f)
            config = load_workspace_config(root)
            self.assertIn("plan_mode", config)
            patterns = get_plan_allowed_patterns(root)
            self.assertEqual(len(patterns), 2)

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as root:
            cfg_dir = os.path.join(root, ".miniclaw")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "config.json"), "w") as f:
                f.write("{bad json")
            self.assertEqual(load_workspace_config(root), {})

    def test_invalid_regex_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            cfg_dir = os.path.join(root, ".miniclaw")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "config.json"), "w") as f:
                json.dump({
                    "plan_mode": {
                        "allowed_bash_patterns": [r"^good\b", "[invalid(regex"]
                    }
                }, f)
            patterns = get_plan_allowed_patterns(root)
            self.assertEqual(len(patterns), 1)

    def test_non_list_patterns_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            cfg_dir = os.path.join(root, ".miniclaw")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "config.json"), "w") as f:
                json.dump({"plan_mode": {"allowed_bash_patterns": "not a list"}}, f)
            self.assertEqual(get_plan_allowed_patterns(root), [])

    def test_config_integrates_with_check_plan_mode(self):
        """配置文件的正则应在 check_plan_mode 中生效。"""
        with tempfile.TemporaryDirectory() as root:
            cfg_dir = os.path.join(root, ".miniclaw")
            plans_dir = os.path.join(cfg_dir, "plans")
            os.makedirs(plans_dir)
            with open(os.path.join(cfg_dir, "config.json"), "w") as f:
                json.dump({
                    "plan_mode": {"allowed_bash_patterns": [r"^firecrawl\b"]}
                }, f)
            ctx = {
                "mode": "plan",
                "plan_dir": plans_dir,
                "workspace_root": root,
            }
            self.assertIsNone(
                check_plan_mode("bash", {"command": "firecrawl search 'ai'"}, ctx)
            )
            result = check_plan_mode("bash", {"command": "wget http://x.com"}, ctx)
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
