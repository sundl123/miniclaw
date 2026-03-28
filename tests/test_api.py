"""API 模块的单元测试（不含真实网络请求）。"""
import json
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.api import chat, _execute_tool_call


class TestExecuteToolCall(unittest.TestCase):
    def test_bash_call(self):
        tc = {
            "function": {"name": "bash", "arguments": '{"command": "echo hi"}'},
        }
        with patch("miniclaw.api.execute_tool") as m:
            m.return_value = "hi"
            out = _execute_tool_call(tc)
        self.assertEqual(out, "hi")
        m.assert_called_once_with("bash", {"command": "echo hi"}, workspace_root=None)

    def test_tool_call_with_workspace_root(self):
        tc = {
            "function": {"name": "read", "arguments": '{"path": "f.txt"}'},
        }
        with patch("miniclaw.api.execute_tool") as m:
            m.return_value = "content"
            _execute_tool_call(tc, workspace_root="/tmp/workspace")
        m.assert_called_once_with("read", {"path": "f.txt"}, workspace_root="/tmp/workspace")

    def test_unknown_tool(self):
        tc = {"function": {"name": "unknown_tool", "arguments": "{}"}}
        out = _execute_tool_call(tc)
        data = json.loads(out)
        self.assertIn("error", data)


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
