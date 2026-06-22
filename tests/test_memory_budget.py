"""Tests for memory budget measurement and truncation."""
import unittest

from miniclaw.memory.budget import (
    ContentMeasure,
    check_budget,
    truncate_for_prompt,
)
from miniclaw.memory.config import MemoryConfig


class TestContentMeasure(unittest.TestCase):
    def test_empty(self):
        m = ContentMeasure.from_text("")
        self.assertEqual(m.used_bytes, 0)
        self.assertEqual(m.used_lines, 0)

    def test_single_line_no_trailing_newline(self):
        m = ContentMeasure.from_text("hello")
        self.assertEqual(m.used_lines, 1)

    def test_multiline_with_trailing_newline(self):
        m = ContentMeasure.from_text("a\nb\n")
        self.assertEqual(m.used_lines, 2)

    def test_bytes_unicode(self):
        m = ContentMeasure.from_text("中文")
        self.assertGreater(m.used_bytes, 2)


class TestCheckBudget(unittest.TestCase):
    def setUp(self):
        self.cfg = MemoryConfig(
            enabled=True,
            memory_md_max_bytes=100,
            memory_md_max_lines=3,
        )

    def test_within_limits(self):
        r = check_budget("a\nb\n", self.cfg)
        self.assertTrue(r.ok)
        self.assertEqual(r.violations, ())

    def test_bytes_exceeded(self):
        content = "x" * 101
        r = check_budget(content, self.cfg)
        self.assertFalse(r.ok)
        self.assertIn("bytes", r.violations)

    def test_lines_exceeded(self):
        content = "a\nb\nc\nd\n"
        r = check_budget(content, self.cfg)
        self.assertFalse(r.ok)
        self.assertIn("lines", r.violations)

    def test_single_huge_line(self):
        content = "x" * 101
        r = check_budget(content, self.cfg)
        self.assertFalse(r.ok)
        self.assertIn("bytes", r.violations)


class TestTruncateForPrompt(unittest.TestCase):
    def setUp(self):
        self.cfg = MemoryConfig(
            enabled=True,
            memory_md_max_bytes=10,
            memory_md_max_lines=2,
        )

    def test_no_truncation_when_ok(self):
        text = "ab"
        out, meta = truncate_for_prompt(text, self.cfg)
        self.assertEqual(out, text)
        self.assertFalse(meta.truncated)

    def test_truncates_by_lines(self):
        text = "line1\nline2\nline3\n"
        out, meta = truncate_for_prompt(text, self.cfg)
        self.assertTrue(meta.truncated)
        self.assertIn("line1", out)
        self.assertNotIn("line3", out)

    def test_truncates_by_bytes(self):
        text = "12345678901\n"
        out, meta = truncate_for_prompt(text, self.cfg)
        self.assertTrue(meta.truncated)
        self.assertLessEqual(len(out.encode("utf-8")), 10)


if __name__ == "__main__":
    unittest.main()
