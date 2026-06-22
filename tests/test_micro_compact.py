"""Tests for micro-compaction policies."""
import json
import unittest

from miniclaw.context.config import ContextConfig, MicroCompactConfig
from miniclaw.context.micro_compact import micro_compact, count_compacted


def _cfg(**kwargs) -> ContextConfig:
    mc = MicroCompactConfig(
        keep_recent_tool_results=1,
        keep_recent_turns=1,
        placeholder_max_chars=100,
        **{k: v for k, v in kwargs.items() if k in (
            "keep_recent_tool_results", "keep_recent_turns", "placeholder_max_chars",
        )},
    )
    return ContextConfig(micro_compact=mc)


class TestMicroCompact(unittest.TestCase):
    def _read_exchange(self, path: str, content: str, *, stale_first: bool = True) -> list[dict]:
        """Two read rounds; first is stale when keep_recent_tool_results=1."""
        big = content
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": json.dumps({"path": path})},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": big},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "read", "arguments": json.dumps({"path": "other.py"})},
                }],
            },
            {"role": "tool", "tool_call_id": "call_2", "content": "line 1\n"},
        ]
        return msgs

    def test_read_compacts_stale_result_only(self):
        msgs = self._read_exchange("a.py", "x" * 500)
        n = micro_compact(msgs, _cfg())
        self.assertGreater(n, 0)
        self.assertTrue(msgs[3].get("_compacted"))
        content = msgs[3]["content"]
        self.assertTrue(content.startswith("[compacted]"))
        self.assertIn("read", content)
        self.assertIn("tokens", content)
        self.assertIn("re-invoke read", content)
        self.assertNotIn("args:", content)
        self.assertNotIn('"path": "a.py"', content)
        self.assertNotIn("\n", content)
        self.assertNotIn("_compacted", msgs[5])  # recent tool result kept

    def test_placeholder_one_line_format(self):
        msgs = self._read_exchange("a.py", "x" * 500)
        micro_compact(msgs, _cfg())
        self.assertNotIn("\n", msgs[3]["content"])

    def test_write_compacts_arguments_not_short_result(self):
        content = "y" * 500
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "w"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_w1",
                    "type": "function",
                    "function": {
                        "name": "write",
                        "arguments": json.dumps({"path": "f.py", "content": content}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "call_w1", "content": "Successfully wrote to f.py"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_r2",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"g.py"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_r2", "content": "ok"},
        ]
        micro_compact(msgs, _cfg())
        args = json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"])
        self.assertTrue(args.get("_compacted"))
        self.assertNotIn("content", args)
        self.assertEqual(args.get("_content_chars"), 500)
        self.assertEqual(msgs[3]["content"], "Successfully wrote to f.py")

    def test_tool_call_ids_preserved(self):
        msgs = self._read_exchange("a.py", "z" * 300)
        micro_compact(msgs, _cfg())
        self.assertEqual(msgs[3]["tool_call_id"], "call_1")

    def test_count_compacted(self):
        msgs = self._read_exchange("a.py", "z" * 300)
        micro_compact(msgs, _cfg())
        self.assertGreaterEqual(count_compacted(msgs), 1)

    def test_memory_write_compacts_arguments(self):
        content = "y" * 500
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "w"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_m1",
                    "type": "function",
                    "function": {
                        "name": "memory",
                        "arguments": json.dumps({
                            "action": "write",
                            "path": "notes/a.md",
                            "content": content,
                        }),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_m1",
                "content": json.dumps({"success": True, "message": "ok"}),
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_m2",
                    "type": "function",
                    "function": {"name": "memory", "arguments": '{"action":"status"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_m2", "content": '{"success": true}'},
        ]
        micro_compact(msgs, _cfg())
        args = json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"])
        self.assertTrue(args.get("_compacted"))
        self.assertNotIn("content", args)
        self.assertEqual(args.get("_content_chars"), 500)
        self.assertIn("memory read", args.get("_hint", ""))

    def test_memory_read_compacts_stale_result(self):
        big = json.dumps({"success": True, "content": "x" * 500})
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_r1",
                    "type": "function",
                    "function": {
                        "name": "memory",
                        "arguments": json.dumps({"action": "read", "path": "notes/a.md"}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "call_r1", "content": big},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_r2",
                    "type": "function",
                    "function": {"name": "memory", "arguments": '{"action":"status"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_r2", "content": '{"success": true}'},
        ]
        micro_compact(msgs, _cfg())
        self.assertTrue(msgs[3].get("_compacted"))
        self.assertIn("[compacted] memory", msgs[3]["content"])


if __name__ == "__main__":
    unittest.main()
