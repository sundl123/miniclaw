"""API 模块的单元测试（不含真实网络请求）。"""
import json
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.api import chat, _execute_tool_call


class TestExecuteToolCall(unittest.TestCase):
    def test_code_execution_call(self):
        tc = {
            "function": {"name": "code_execution", "arguments": '{"action": "run_bash", "command": "echo hi"}'},
        }
        with patch("miniclaw.api.handle_code_execution") as m:
            m.return_value = "hi"
            out = _execute_tool_call(tc)
        self.assertEqual(out, "hi")
        m.assert_called_once()

    def test_code_execution_with_workspace_root(self):
        tc = {
            "function": {"name": "code_execution", "arguments": '{"action": "run_bash", "command": "pwd"}'},
        }
        with patch("miniclaw.api.handle_code_execution") as m:
            m.return_value = "/tmp/workspace"
            _execute_tool_call(tc, workspace_root="/tmp/workspace")
        m.assert_called_once_with(
            {"action": "run_bash", "command": "pwd"},
            workspace_root="/tmp/workspace",
        )

    def test_unknown_tool(self):
        tc = {"function": {"name": "unknown_tool", "arguments": "{}"}}
        out = _execute_tool_call(tc)
        data = json.loads(out)
        self.assertIn("error", data)
        self.assertIn("Unknown tool", data["error"])


class TestChat(unittest.TestCase):
    def test_chat_returns_content_from_chat_raw(self):
        with patch("miniclaw.api.chat_raw") as m:
            m.return_value = ({"content": " Hello "}, {})
            out = chat("fake-key", [])
        self.assertEqual(out, "Hello")

    def test_chat_handles_empty_content(self):
        with patch("miniclaw.api.chat_raw") as m:
            m.return_value = ({"content": None}, {})
            out = chat("fake-key", [])
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
