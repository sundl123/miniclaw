"""Code execution 工具的单元测试。"""
import json
import os
import tempfile
import unittest

from miniclaw.code_execution import (
    resolve_path,
    handle_code_execution,
    get_code_execution_tool_schema,
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


class TestHandleCodeExecution(unittest.TestCase):
    def test_missing_action(self):
        out = handle_code_execution({})
        self.assertIn("error", json.loads(out))

    def test_unknown_action(self):
        out = handle_code_execution({"action": "unknown"})
        self.assertIn("未知 action", out)

    def test_view_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "f.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("hello")
            rel = os.path.relpath(path, root)
            out = handle_code_execution({"action": "view_file", "path": rel}, root)
        self.assertEqual(out, "hello")

    def test_view_file_not_found(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_code_execution({"action": "view_file", "path": "nonexistent.txt"}, root)
        self.assertIn("error", json.loads(out))

    def test_create_file(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_code_execution(
                {"action": "create_file", "path": "out.txt", "content": "x"},
                root,
            )
            self.assertIn("Created", out)
            p = os.path.join(root, "out.txt")
            self.assertTrue(os.path.isfile(p))
            with open(p, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "x")

    def test_run_bash(self):
        with tempfile.TemporaryDirectory() as root:
            out = handle_code_execution({"action": "run_bash", "command": "echo ok"}, root)
        self.assertEqual(out.strip(), "ok")


class TestGetCodeExecutionToolSchema(unittest.TestCase):
    def test_schema_has_function_name(self):
        s = get_code_execution_tool_schema()
        self.assertEqual(s["type"], "function")
        self.assertEqual(s["function"]["name"], "code_execution")
        self.assertIn("action", s["function"]["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
