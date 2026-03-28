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
    def test_returns_six_tools(self):
        schemas = get_tool_schemas()
        self.assertEqual(len(schemas), 6)
        names = {s["function"]["name"] for s in schemas}
        self.assertEqual(names, {"read", "write", "edit", "glob", "grep", "bash"})

    def test_all_have_function_type(self):
        for s in get_tool_schemas():
            self.assertEqual(s["type"], "function")
            self.assertIn("parameters", s["function"])


if __name__ == "__main__":
    unittest.main()
