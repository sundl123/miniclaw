"""Tests for memory tool handler."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.memory.config import MEMORY_MD_FILENAME, MemoryConfig
from miniclaw.memory.store import MemoryStore
from miniclaw.memory.tool import handle_memory
from miniclaw.tools import execute_tool, get_tool_schemas
from miniclaw.tools_config import ReadToolConfig, ToolsConfig


class TestMemoryTool(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory_root = os.path.join(self._tmpdir.name, "memory")
        os.makedirs(self.memory_root)
        self.cfg = MemoryConfig(enabled=True, memory_md_max_bytes=200, memory_md_max_lines=10)
        self.patcher = patch("miniclaw.memory.paths.get_memory_dir", return_value=self.memory_root)
        self.patcher.start()
        self.store = MemoryStore(self.cfg)
        self.store.ensure_layout()
        self.ctx = {"memory_store": self.store}

    def tearDown(self):
        self.patcher.stop()
        self._tmpdir.cleanup()

    def test_disabled_without_store(self):
        out = json.loads(handle_memory({"action": "status"}, context={}))
        self.assertFalse(out["success"])

    def test_status_action(self):
        out = json.loads(handle_memory({"action": "status"}, context=self.ctx))
        self.assertTrue(out["success"])
        self.assertIn("memory_md_usage", out)

    def test_write_memory_md_success(self):
        out = json.loads(handle_memory(
            {"action": "write", "path": MEMORY_MD_FILENAME, "content": "# Memory\nok\n"},
            context=self.ctx,
        ))
        self.assertTrue(out["success"])
        self.assertIn("memory_md_usage", out)

    def test_path_traversal_rejected(self):
        out = json.loads(handle_memory(
            {"action": "read", "path": "../secret.txt"},
            context=self.ctx,
        ))
        self.assertFalse(out["success"])

    def test_schema_included_when_enabled(self):
        schemas = get_tool_schemas(include_memory=True)
        names = [s["function"]["name"] for s in schemas]
        self.assertIn("memory", names)

    def test_schema_excluded_when_disabled(self):
        schemas = get_tool_schemas(include_memory=False)
        names = [s["function"]["name"] for s in schemas]
        self.assertNotIn("memory", names)

    def test_execute_tool_memory(self):
        result = json.loads(execute_tool(
            "memory",
            {"action": "write", "path": "notes/a.md", "content": "detail"},
            workspace_root=self._tmpdir.name,
            context=self.ctx,
        ))
        self.assertTrue(result["success"])

    def test_read_rejects_huge_file_via_execute_tool(self):
        notes_dir = os.path.join(self.memory_root, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "big.md"), "wb") as f:
            f.write(b"x" * 5000)
        tools_cfg = ToolsConfig(
            read=ReadToolConfig(max_file_bytes=1000, max_output_tokens=8000),
            max_tool_result_chars=100_000,
            max_glob_files=500,
        )
        result = json.loads(execute_tool(
            "memory",
            {"action": "read", "path": "notes/big.md"},
            workspace_root=self._tmpdir.name,
            context=self.ctx,
            tools_config=tools_cfg,
        ))
        self.assertFalse(result["success"])
        self.assertIn("exceeds maximum", result["error"].lower())

    def test_list_truncates_via_execute_tool(self):
        many_dir = os.path.join(self.memory_root, "many")
        os.makedirs(many_dir, exist_ok=True)
        for i in range(5):
            with open(os.path.join(many_dir, f"f{i}.txt"), "w", encoding="utf-8") as f:
                f.write("x")
        tools_cfg = ToolsConfig(
            read=ReadToolConfig(),
            max_tool_result_chars=100_000,
            max_glob_files=2,
        )
        result = json.loads(execute_tool(
            "memory",
            {"action": "list", "path": "many"},
            workspace_root=self._tmpdir.name,
            context=self.ctx,
            tools_config=tools_cfg,
        ))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(result["entries_truncated"])
        self.assertEqual(result["total_entries"], 5)


if __name__ == "__main__":
    unittest.main()
