"""Tests for context token estimation."""
import unittest

from miniclaw.context.tokens import (
    estimate_messages_tokens,
    estimate_text_tokens,
    get_estimated_tokens,
    update_usage_from_response,
)


class TestTokenEstimation(unittest.TestCase):
    def test_estimate_text_tokens(self):
        self.assertGreater(estimate_text_tokens("hello world"), 0)

    def test_json_uses_more_tokens_per_char(self):
        json_text = '{"a":1,"b":2}'
        plain = "a" * len(json_text)
        self.assertGreater(estimate_text_tokens(json_text), estimate_text_tokens(plain) // 2)

    def test_tool_calls_counted(self):
        messages = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path":"big.py"}'},
            }],
        }]
        self.assertGreater(estimate_messages_tokens(messages), 0)

    def test_usage_preferred(self):
        ctx = {}
        update_usage_from_response(ctx, type("U", (), {"prompt_tokens": 50000})())
        messages = [{"role": "user", "content": "x"}]
        self.assertEqual(get_estimated_tokens(messages, ctx), 50000)


if __name__ == "__main__":
    unittest.main()
