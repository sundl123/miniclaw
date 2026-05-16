"""Tests for conversation summarization."""
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.context.config import ContextConfig, SummarizeConfig
from miniclaw.context.summarize import summarize_conversation, _parse_summary
from miniclaw.context.manage import manage_messages, manage_messages_end_of_turn, init_ctx_mgmt


class TestParseSummary(unittest.TestCase):
    def test_extracts_summary_block(self):
        text = "<analysis>x</analysis><summary>Hello summary</summary>"
        self.assertEqual(_parse_summary(text), "Hello summary")


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
                {"role": "assistant", "content": "<summary>Compacted</summary>"},
                {},
            )
            new_msgs, ok = summarize_conversation(client, "m", messages, cfg)
        self.assertTrue(ok)
        self.assertTrue(any(m.get("is_compact_summary") for m in new_msgs))
        self.assertEqual(new_msgs[-1]["content"], "last")

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


class TestManagePending(unittest.TestCase):
    def test_sets_pending_not_summarize_in_loop(self):
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
        messages = [{"role": "system", "content": "s"}]
        for i in range(20):
            messages.append({"role": "user", "content": "x" * 200})
            messages.append({"role": "assistant", "content": "y" * 200})
        manage_messages(messages, cfg, ctx)
        self.assertTrue(ctx["_ctx_mgmt"].get("pending_summarize"))


if __name__ == "__main__":
    unittest.main()
