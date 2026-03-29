"""API 模块的单元测试（不含真实网络请求）。"""
import json
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.api import chat, chat_raw, _execute_tool_call, create_client


def _make_mock_client(content=" Hello ", tool_calls=None):
    """构造一个返回指定内容的 mock OpenAI client。"""
    client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message = mock_msg
    mock_resp.usage = None
    mock_resp.model_dump.return_value = {}
    client.chat.completions.create.return_value = mock_resp
    return client


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
    def test_chat_returns_content(self):
        client = _make_mock_client(content=" Hello ")
        out = chat(client, [])
        self.assertEqual(out, "Hello")

    def test_chat_handles_empty_content(self):
        client = _make_mock_client(content=None)
        out = chat(client, [])
        self.assertEqual(out, "")


class TestChatRaw(unittest.TestCase):
    def test_returns_message_dict_and_data(self):
        client = _make_mock_client(content="world")
        msg, data = chat_raw(client, [{"role": "user", "content": "hi"}])
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["content"], "world")
        self.assertIsInstance(data, dict)

    def test_includes_tool_calls_when_present(self):
        tc = MagicMock()
        tc.id = "call_1"
        tc.type = "function"
        tc.function.name = "bash"
        tc.function.arguments = '{"command": "ls"}'
        client = _make_mock_client(content="", tool_calls=[tc])
        msg, _ = chat_raw(client, [])
        self.assertIn("tool_calls", msg)
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "bash")


class TestCreateClient(unittest.TestCase):
    def test_returns_openai_client(self):
        client = create_client("test-key")
        self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
