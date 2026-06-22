"""Tests for MemoryStore and path sandbox."""
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.memory.budget import ContentMeasure
from miniclaw.memory.config import MEMORY_MD_FILENAME, MemoryConfig
from miniclaw.memory.paths import normalize_memory_rel_path, resolve_memory_path
from miniclaw.memory.store import MemoryStore
from miniclaw.tools_config import ReadToolConfig


class TestMemoryPaths(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory_root = os.path.join(self._tmpdir.name, "memory")
        os.makedirs(self.memory_root)

    def tearDown(self):
        self._tmpdir.cleanup()

    @patch("miniclaw.memory.paths.get_memory_dir")
    def test_reject_parent_traversal(self, mock_dir):
        mock_dir.return_value = self.memory_root
        with self.assertRaises(PermissionError):
            normalize_memory_rel_path("../etc/passwd")

    @patch("miniclaw.memory.paths.get_memory_dir")
    def test_resolve_under_root(self, mock_dir):
        mock_dir.return_value = self.memory_root
        p = resolve_memory_path("notes/foo.md")
        self.assertTrue(p.startswith(self.memory_root))


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory_root = os.path.join(self._tmpdir.name, "memory")
        os.makedirs(self.memory_root)
        self.cfg = MemoryConfig(
            enabled=True,
            memory_md_max_bytes=200,
            memory_md_max_lines=10,
            warn_threshold_pct=80,
        )
        self.patcher = patch("miniclaw.memory.paths.get_memory_dir", return_value=self.memory_root)
        self.patcher.start()
        self.store = MemoryStore(self.cfg)

    def tearDown(self):
        self.patcher.stop()
        self._tmpdir.cleanup()

    def _md_path(self):
        return os.path.join(self.memory_root, MEMORY_MD_FILENAME)

    def test_ensure_layout_creates_placeholder(self):
        self.store.ensure_layout()
        self.assertTrue(os.path.isfile(self._md_path()))

    def test_load_snapshot_truncates_oversized_file(self):
        huge = "x" * 500
        with open(self._md_path(), "w", encoding="utf-8") as f:
            f.write(huge)
        self.store.load_snapshot()
        block = self.store.format_for_system_prompt()
        self.assertIsNotNone(block)
        self.assertTrue(self.store.truncation_meta.truncated)
        self.assertLess(len(self.store._prompt_snapshot.encode("utf-8")), 500)

    def test_frozen_snapshot_unchanged_after_write(self):
        with open(self._md_path(), "w", encoding="utf-8") as f:
            f.write("# Memory\ninitial\n")
        self.store.load_snapshot()
        before = self.store.format_for_system_prompt()
        self.store.write_file(MEMORY_MD_FILENAME, "# Memory\nupdated\n")
        after = self.store.format_for_system_prompt()
        self.assertEqual(before, after)

    def test_preflight_rejects_oversized_memory_md(self):
        self.store.ensure_layout()
        content = "y" * 500
        result = self.store.write_file(MEMORY_MD_FILENAME, content)
        self.assertFalse(result["success"])
        with open(self._md_path(), encoding="utf-8") as f:
            on_disk = f.read()
        self.assertNotEqual(on_disk, content)

    def test_topic_write_unlimited(self):
        self.store.ensure_layout()
        big = "z" * 50_000
        result = self.store.write_file("notes/big.md", big)
        self.assertTrue(result["success"])
        self.assertEqual(os.path.getsize(os.path.join(self.memory_root, "notes", "big.md")), 50_000)

    def test_delete_memory_md_forbidden(self):
        self.store.ensure_layout()
        result = self.store.delete_file(MEMORY_MD_FILENAME)
        self.assertFalse(result["success"])
        self.assertTrue(os.path.isfile(self._md_path()))

    def test_delete_topic_allowed(self):
        self.store.write_file("temp.md", "gone")
        result = self.store.delete_file("temp.md")
        self.assertTrue(result["success"])
        self.assertFalse(os.path.isfile(os.path.join(self.memory_root, "temp.md")))

    def test_usage_warning_at_threshold(self):
        self.store.ensure_layout()
        # 85% of 200 bytes
        content = "a" * 170
        result = self.store.write_file(MEMORY_MD_FILENAME, content)
        self.assertTrue(result["success"])
        self.assertIsNotNone(result.get("warning"))

    def test_edit_preflight_failure_preserves_disk(self):
        self.store.write_file(MEMORY_MD_FILENAME, "short")
        result = self.store.edit_file(MEMORY_MD_FILENAME, "short", "x" * 500)
        self.assertFalse(result["success"])
        with open(self._md_path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), "short")

    def test_read_rejects_oversized_topic_without_limit(self):
        notes_dir = os.path.join(self.memory_root, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        huge_path = os.path.join(notes_dir, "huge.md")
        with open(huge_path, "wb") as f:
            f.write(b"x" * 5000)
        read_cfg = ReadToolConfig(max_file_bytes=1000, max_output_tokens=8000)
        result = self.store.read_file("notes/huge.md", read_cfg=read_cfg)
        self.assertFalse(result["success"])
        self.assertIn("exceeds maximum", result["error"].lower())

    def test_read_truncates_with_limit_when_output_huge(self):
        lines = "\n".join("word " * 50 for _ in range(100)) + "\n"
        self.store.write_file("notes/dense.md", lines)
        read_cfg = ReadToolConfig(max_file_bytes=1_000_000, max_output_tokens=50)
        result = self.store.read_file(
            "notes/dense.md", offset=0, limit=100, read_cfg=read_cfg,
        )
        self.assertTrue(result["success"])
        self.assertTrue(result.get("content_truncated"))
        self.assertIn("[truncated]", result["content"])

    def test_list_truncates_entries(self):
        many_dir = os.path.join(self.memory_root, "many")
        os.makedirs(many_dir, exist_ok=True)
        for i in range(10):
            with open(os.path.join(many_dir, f"f{i}.txt"), "w", encoding="utf-8") as f:
                f.write("x")
        result = self.store.list_files("many", max_entries=3)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["entries"]), 3)
        self.assertTrue(result["entries_truncated"])
        self.assertEqual(result["total_entries"], 10)


if __name__ == "__main__":
    unittest.main()
