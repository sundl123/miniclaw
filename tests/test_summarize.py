"""Tests for conversation summarization."""
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.context.config import ContextConfig, SummarizeConfig
from miniclaw.context.summarize import (
    summarize_conversation,
    extract_compact_summary,
    _parse_summary,
    _rebuild_messages,
    _strip_non_summary_blocks,
    _is_valid_summary,
    prepare_tail_for_rebuild,
)
from miniclaw.context.manage import manage_messages, init_ctx_mgmt


class TestPrepareTail(unittest.TestCase):
    def test_drops_orphan_tool_without_parent_assistant(self):
        """Reproduces MiniMax 2013: tool id not found after naive tail slice."""
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_old",
                    "type": "function",
                    "function": {"name": "bash", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_old", "content": "old output"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_function_yd096oj2ibwa_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"README.md"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_function_yd096oj2ibwa_1", "content": "readme"},
            {"role": "assistant", "content": "done"},
        ]
        _, tail = prepare_tail_for_rebuild(messages, keep=3)
        tool_ids = [m.get("tool_call_id") for m in tail if m.get("role") == "tool"]
        self.assertNotIn("call_old", tool_ids)
        self.assertIn("call_function_yd096oj2ibwa_1", tool_ids)
        self.assertTrue(_assistant_has_tool_id_in_tail(tail, "call_function_yd096oj2ibwa_1"))

    def test_expands_backward_to_include_assistant_for_leading_tool(self):
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "body"},
            {"role": "assistant", "content": "summary"},
        ]
        _, tail = prepare_tail_for_rebuild(messages, keep=2)
        roles = [m["role"] for m in tail]
        self.assertEqual(roles[0], "assistant")
        self.assertIn("tool_calls", tail[0])


def _assistant_has_tool_id_in_tail(tail: list[dict], tool_call_id: str) -> bool:
    for msg in tail:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if tc.get("id") == tool_call_id:
                return True
    return False


class TestParseSummary(unittest.TestCase):
    def test_extracts_summary_block(self):
        text = "<analysis>x</analysis><summary>Hello summary</summary>"
        self.assertEqual(_parse_summary(text), "Hello summary")

    def test_strips_thinking_before_parse(self):
        raw = (
            "<think>internal notes</think>\n"
            "<analysis>draft</analysis>\n"
            "<summary>1. User intent: Do work.\n"
            "2. Key files/code: foo.ts\n"
            "3. Errors and fixes: none\n"
            "4. Completed work: done\n"
            "5. Pending tasks: none\n"
            "6. Next step: continue</summary>"
        )
        parsed = _parse_summary(raw)
        self.assertIsNotNone(parsed)
        self.assertIn("User intent", parsed)
        self.assertNotIn("internal notes", parsed)

    def test_truncated_summary_without_close_tag(self):
        raw = (
            "<think>x</think>"
            "<summary>1. User intent: test\n2. Key files/code: a.py"
        )
        parsed = _parse_summary(raw)
        self.assertIn("User intent", parsed)
        self.assertNotIn("redacted_thinking", parsed.lower())

    def test_no_summary_tag_returns_none(self):
        self.assertIsNone(_parse_summary("<think>only thinking</think>"))

    def test_strip_non_summary_blocks(self):
        text = "<thinking>a</thinking> rest <analysis>b</analysis> tail"
        self.assertEqual(_strip_non_summary_blocks(text), "rest  tail")

    def test_rejects_template_echo(self):
        placeholder = (
            "1. User intent: ...\n2. Key files/code: ...\n"
            "3. Errors and fixes: ...\n4. Completed work: ...\n"
            "5. Pending tasks: ...\n6. Next step: ..."
        )
        self.assertFalse(_is_valid_summary(placeholder))

    def test_rejects_leaked_thinking_markers(self):
        leaked = (
            "1. User intent: x\n2. Key files/code: y\n3. Errors and fixes: none\n"
            "4. Completed work: z\n5. Pending tasks: none\n6. Next step: n\n"
            "<thinking>oops</thinking>"
        )
        self.assertFalse(_is_valid_summary(leaked))

    def test_accepts_real_summary(self):
        real = (
            "1. User intent: Summarize the claude-code repo.\n"
            "2. Key files/code: README.md describes a security research snapshot.\n"
            "3. Errors and fixes: none\n"
            "4. Completed work: Explored with bash/glob and read README.\n"
            "5. Pending tasks: none\n"
            "6. Next step: N/A"
        )
        self.assertTrue(_is_valid_summary(real))


class TestExtractCompactSummary(unittest.TestCase):
    def test_extracts_from_rebuilt_messages(self):
        msgs = _rebuild_messages(
            {"role": "system", "content": "sys"},
            "hello summary",
            [],
        )
        self.assertEqual(extract_compact_summary(msgs), "hello summary")

    def test_returns_empty_without_compact_message(self):
        self.assertEqual(extract_compact_summary([
            {"role": "user", "content": "plain"},
        ]), "")

    def test_truncates_to_max_chars(self):
        long_summary = "x" * 5000
        msgs = _rebuild_messages(
            {"role": "system", "content": "sys"},
            long_summary,
            [],
        )
        self.assertEqual(len(extract_compact_summary(msgs, max_chars=100)), 100)


class TestSummarize(unittest.TestCase):
    def test_rebuilds_messages_on_success(self):
        cfg = ContextConfig(summarize=SummarizeConfig(keep_recent_messages=2))
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "last"},
        ]
        client = MagicMock()
        with patch("miniclaw.api.chat_raw") as mock_raw:
            mock_raw.return_value = (
                {"role": "assistant", "content": (
                    "<summary>1. User intent: Test old message.\n"
                    "2. Key files/code: none\n3. Errors and fixes: none\n"
                    "4. Completed work: Discussed prior topic.\n"
                    "5. Pending tasks: none\n6. Next step: recent</summary>"
                )},
                {},
            )
            new_msgs, ok = summarize_conversation(client, "m", messages, cfg)
        self.assertTrue(ok)
        self.assertTrue(any(m.get("is_compact_summary") for m in new_msgs))
        self.assertEqual(new_msgs[-1]["content"], "last")  # tail preserved

    def test_failure_returns_original(self):
        cfg = ContextConfig(summarize=SummarizeConfig(keep_recent_messages=2))
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
        ]
        client = MagicMock()
        with patch("miniclaw.api.chat_raw", side_effect=RuntimeError("fail")):
            new_msgs, ok = summarize_conversation(client, "m", messages, cfg)
        self.assertFalse(ok)
        self.assertEqual(new_msgs, messages)

    def test_rejects_raw_without_summary_block(self):
        cfg = ContextConfig(summarize=SummarizeConfig(keep_recent_messages=2))
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
        ]
        client = MagicMock()
        with patch("miniclaw.api.chat_raw") as mock_raw:
            mock_raw.return_value = (
                {"role": "assistant", "content": (
                    "<think>long internal</think>"
                    "<analysis>notes</analysis>"
                )},
                {},
            )
            new_msgs, ok = summarize_conversation(client, "m", messages, cfg)
        self.assertFalse(ok)
        self.assertEqual(new_msgs, messages)


class TestManageImmediateSummarize(unittest.TestCase):
    def test_summarizes_immediately_when_over_threshold(self):
        cfg = ContextConfig(
            context_window_tokens=1000,
            reserve_output_tokens=100,
            auto_summarize=__import__(
                "miniclaw.context.config", fromlist=["AutoSummarizeConfig"]
            ).AutoSummarizeConfig(
                threshold_buffer_tokens=100,
                min_messages_before_summarize=2,
            ),
        )
        ctx = {}
        init_ctx_mgmt(ctx)
        client = MagicMock()
        messages = [{"role": "system", "content": "s"}]
        for i in range(20):
            messages.append({"role": "user", "content": "x" * 200})
            messages.append({"role": "assistant", "content": "y" * 200})
        compacted = [{"role": "system", "content": "s"}, {"role": "user", "content": "summary"}]
        progress: list[str] = []

        with patch(
            "miniclaw.context.manage.summarize_conversation",
            return_value=(compacted, True),
        ) as mock_sum:
            result = manage_messages(
                client, "m", messages, cfg, ctx,
                on_compact_progress=progress.append,
            )
        mock_sum.assert_called_once()
        self.assertEqual(result, compacted)
        self.assertEqual(progress, ["start", "done"])

    def test_skips_when_compacting_flag_set(self):
        cfg = ContextConfig(enabled=True)
        ctx = {"_ctx_mgmt": {"compacting": True}}
        client = MagicMock()
        with patch("miniclaw.context.manage.summarize_conversation") as mock_sum:
            result = manage_messages(client, "m", [{"role": "user", "content": "hi"}], cfg, ctx)
        mock_sum.assert_not_called()
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
