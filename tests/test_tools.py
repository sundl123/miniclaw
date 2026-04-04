"""工具模块的单元测试。"""
import json
import os
import tempfile
import unittest

from miniclaw.tools import (
    resolve_path,
    handle_read,
    handle_write,
    handle_edit,
    handle_glob,
    handle_grep,
    handle_bash,
    execute_tool,
    get_tool_schemas,
    handle_enter_plan_mode,
    handle_exit_plan_mode,
    _is_plan_dir_write,
    _check_plan_mode,
)


class TestResolvePath(unittest.TestCase):
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as root:
            p = resolve_path("a/b.txt", root)
            self.assertEqual(p, os.path.join(root, "a", "b.txt"))

    def test_escape_forbidden(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                resolve_path("../../../etc/passwd", root)


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


class TestGetToolSchemas(unittest.TestCase):
    def test_returns_eight_tools(self):
        schemas = get_tool_schemas()
        self.assertEqual(len(schemas), 8)
        names = {s["function"]["name"] for s in schemas}
        self.assertEqual(names, {
            "read", "write", "edit", "glob", "grep", "bash",
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
            self.assertIsNone(_check_plan_mode("write", {"path": "x.py"}, ctx))
            self.assertIsNone(_check_plan_mode("bash", {"command": "rm -rf /"}, ctx))

    def test_plan_mode_allows_readonly(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            for tool in ("read", "glob", "grep", "enter_plan_mode", "exit_plan_mode"):
                self.assertIsNone(_check_plan_mode(tool, {}, ctx))

    def test_plan_mode_allows_plan_dir_write(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            self.assertIsNone(
                _check_plan_mode("write", {"path": ".miniclaw/plans/my-plan.md"}, ctx)
            )

    def test_plan_mode_allows_any_file_in_plan_dir(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            self.assertIsNone(
                _check_plan_mode("write", {"path": ".miniclaw/plans/feature-x.md"}, ctx)
            )
            self.assertIsNone(
                _check_plan_mode("edit", {"path": ".miniclaw/plans/bugfix.md"}, ctx)
            )

    def test_plan_mode_blocks_other_write(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = _check_plan_mode("write", {"path": "src/main.py"}, ctx)
            self.assertIsNotNone(result)
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("Plan Mode", data["error"])

    def test_plan_mode_blocks_bash(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = _check_plan_mode("bash", {"command": "echo hi"}, ctx)
            self.assertIsNotNone(result)

    def test_plan_mode_blocks_edit_non_plan(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = self._make_ctx(root)
            result = _check_plan_mode("edit", {"path": "foo.py", "old_string": "a", "new_string": "b"}, ctx)
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


if __name__ == "__main__":
    unittest.main()
