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


if __name__ == "__main__":
    unittest.main()
