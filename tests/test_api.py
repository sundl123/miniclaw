"""API 模块的单元测试（不含真实网络请求）。"""
import json
import time
import unittest
from unittest.mock import patch, MagicMock

from miniclaw.api import (
    chat, chat_raw, chat_stream, create_client,
    _execute_tool_call, _build_message, _consume_stream,
    _StreamResult, _StreamPrinter,
)


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
        m.assert_called_once_with("bash", {"command": "echo hi"}, workspace_root=None, context=None)

    def test_tool_call_with_workspace_root(self):
        tc = {
            "function": {"name": "read", "arguments": '{"path": "f.txt"}'},
        }
        with patch("miniclaw.api.execute_tool") as m:
            m.return_value = "content"
            _execute_tool_call(tc, workspace_root="/tmp/workspace")
        m.assert_called_once_with("read", {"path": "f.txt"}, workspace_root="/tmp/workspace", context=None)

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


# ---------------------------------------------------------------------------
# Fake objects for stream tests (avoid MagicMock's hasattr quirks)
# ---------------------------------------------------------------------------

_UNSET = object()


class _FakeDelta:
    def __init__(self, content=None, tool_calls=None, reasoning_details=_UNSET):
        self.content = content
        self.tool_calls = tool_calls
        if reasoning_details is not _UNSET:
            self.reasoning_details = reasoning_details


class _FakeChoice:
    def __init__(self, delta):
        self.delta = delta


class _FakeChunk:
    def __init__(self, delta=None, usage=None):
        self.choices = [_FakeChoice(delta)] if delta is not None else []
        self.usage = usage


class _FakeFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _FakeToolCallDelta:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = _FakeFunction(name, arguments)


# ---------------------------------------------------------------------------
# _build_message tests
# ---------------------------------------------------------------------------

class TestBuildMessage(unittest.TestCase):
    def test_content_only(self):
        result = _StreamResult(content_parts=["Hello", " world"])
        msg = _build_message(result)
        self.assertEqual(msg, {"role": "assistant", "content": "Hello world"})

    def test_empty_result(self):
        msg = _build_message(_StreamResult())
        self.assertEqual(msg, {"role": "assistant", "content": ""})

    def test_with_tool_calls(self):
        result = _StreamResult(
            tool_calls_acc={
                0: {"id": "c1", "type": "function",
                    "function": {"name": "bash", "arguments": "{}"}},
            },
        )
        msg = _build_message(result)
        self.assertIn("tool_calls", msg)
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "bash")

    def test_with_reasoning(self):
        result = _StreamResult(
            reasoning_acc={
                0: {"type": "reasoning.text", "text": "step-1",
                    "id": "r1", "format": "", "index": 0},
            },
        )
        msg = _build_message(result)
        self.assertIn("reasoning_details", msg)
        self.assertEqual(msg["reasoning_details"][0]["text"], "step-1")

    def test_tool_calls_sorted_by_index(self):
        result = _StreamResult(
            tool_calls_acc={
                2: {"id": "c3", "type": "function",
                    "function": {"name": "read", "arguments": "{}"}},
                0: {"id": "c1", "type": "function",
                    "function": {"name": "bash", "arguments": "{}"}},
            },
        )
        msg = _build_message(result)
        self.assertEqual(msg["tool_calls"][0]["id"], "c1")
        self.assertEqual(msg["tool_calls"][1]["id"], "c3")


# ---------------------------------------------------------------------------
# _consume_stream tests
# ---------------------------------------------------------------------------

class TestConsumeStream(unittest.TestCase):
    def _run(self, chunks):
        printer = _StreamPrinter(enabled=False)
        return _consume_stream(iter(chunks), printer, time.monotonic())

    def test_accumulates_text_content(self):
        chunks = [
            _FakeChunk(delta=_FakeDelta(content="Hello")),
            _FakeChunk(delta=_FakeDelta(content=" world")),
        ]
        result = self._run(chunks)
        self.assertEqual(result.content_parts, ["Hello", " world"])

    def test_accumulates_tool_calls_across_chunks(self):
        chunks = [
            _FakeChunk(delta=_FakeDelta(tool_calls=[
                _FakeToolCallDelta(index=0, id="call_1", name="bash", arguments='{"co'),
            ])),
            _FakeChunk(delta=_FakeDelta(tool_calls=[
                _FakeToolCallDelta(index=0, arguments='mmand": "ls"}'),
            ])),
        ]
        result = self._run(chunks)
        self.assertIn(0, result.tool_calls_acc)
        self.assertEqual(result.tool_calls_acc[0]["id"], "call_1")
        self.assertEqual(
            result.tool_calls_acc[0]["function"]["arguments"],
            '{"command": "ls"}',
        )

    def test_accumulates_reasoning(self):
        rd = [{"index": 0, "type": "reasoning.text",
               "id": "r1", "format": "", "text": "think"}]
        chunks = [_FakeChunk(delta=_FakeDelta(reasoning_details=rd))]
        result = self._run(chunks)
        self.assertIn(0, result.reasoning_acc)
        self.assertEqual(result.reasoning_acc[0]["text"], "think")

    def test_extracts_usage_from_final_chunk(self):
        usage_obj = MagicMock()
        chunks = [
            _FakeChunk(delta=_FakeDelta(content="hi")),
            _FakeChunk(usage=usage_obj),
        ]
        result = self._run(chunks)
        self.assertIs(result.usage, usage_obj)

    def test_skips_empty_choices(self):
        chunks = [
            _FakeChunk(),
            _FakeChunk(delta=_FakeDelta(content="ok")),
        ]
        result = self._run(chunks)
        self.assertEqual(result.content_parts, ["ok"])

    def test_ttft_set_on_first_content(self):
        chunks = [_FakeChunk(delta=_FakeDelta(content="hi"))]
        result = self._run(chunks)
        self.assertIsNotNone(result.ttft)
        self.assertGreaterEqual(result.ttft, 0)

    def test_ttfc_set_on_first_content(self):
        chunks = [_FakeChunk(delta=_FakeDelta(content="hi"))]
        result = self._run(chunks)
        self.assertIsNotNone(result.ttfc)
        self.assertGreaterEqual(result.ttfc, 0)

    def test_ttft_set_on_reasoning_before_content(self):
        rd = [{"index": 0, "type": "reasoning.text",
               "id": "r1", "format": "", "text": "t"}]
        chunks = [
            _FakeChunk(delta=_FakeDelta(reasoning_details=rd)),
            _FakeChunk(delta=_FakeDelta(content="ans")),
        ]
        result = self._run(chunks)
        self.assertIsNotNone(result.ttft)
        self.assertIsNotNone(result.ttfc)
        self.assertLessEqual(result.ttft, result.ttfc)

    def test_no_tokens_means_no_timing(self):
        chunks = [_FakeChunk()]
        result = self._run(chunks)
        self.assertIsNone(result.ttft)
        self.assertIsNone(result.ttfc)


# ---------------------------------------------------------------------------
# chat_stream integration tests
# ---------------------------------------------------------------------------

class TestChatStream(unittest.TestCase):
    def _make_stream_client(self, chunks):
        client = MagicMock()
        client.chat.completions.create.return_value = iter(chunks)
        return client

    def test_returns_message_and_usage(self):
        usage_obj = MagicMock()
        usage_obj.prompt_tokens = 10
        usage_obj.completion_tokens = 5
        usage_obj.prompt_tokens_details = None

        chunks = [
            _FakeChunk(delta=_FakeDelta(content="Hello")),
            _FakeChunk(usage=usage_obj),
        ]
        client = self._make_stream_client(chunks)
        msg, usage = chat_stream(
            client, [{"role": "user", "content": "hi"}], print_output=False,
        )
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["content"], "Hello")
        self.assertIs(usage, usage_obj)

    def test_stream_with_tool_calls(self):
        chunks = [
            _FakeChunk(delta=_FakeDelta(tool_calls=[
                _FakeToolCallDelta(index=0, id="call_1",
                                   name="bash", arguments='{"command": "ls"}'),
            ])),
        ]
        client = self._make_stream_client(chunks)
        msg, _ = chat_stream(client, [], print_output=False)
        self.assertIn("tool_calls", msg)
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "bash")

    def test_stream_with_reasoning(self):
        rd = [{"index": 0, "type": "reasoning.text",
               "id": "r1", "format": "", "text": "think"}]
        chunks = [
            _FakeChunk(delta=_FakeDelta(reasoning_details=rd)),
            _FakeChunk(delta=_FakeDelta(content="answer")),
        ]
        client = self._make_stream_client(chunks)
        msg, _ = chat_stream(client, [], print_output=False)
        self.assertIn("reasoning_details", msg)
        self.assertEqual(msg["content"], "answer")

    def test_stream_empty_response(self):
        client = self._make_stream_client([_FakeChunk()])
        msg, usage = chat_stream(client, [], print_output=False)
        self.assertEqual(msg, {"role": "assistant", "content": ""})
        self.assertIsNone(usage)


if __name__ == "__main__":
    unittest.main()
