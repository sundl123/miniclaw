"""开发者日志与 chat_raw 请求记录。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from miniclaw.api import chat_raw
from miniclaw.dev_logging import setup_dev_logging


class TestDevLogging(unittest.TestCase):
    def test_setup_creates_timestamped_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = setup_dev_logging(log_dir=d)
            self.assertTrue(Path(path).is_file())
            self.assertTrue(path.endswith(".log"))
            self.assertIn(Path(path).name, os.listdir(d))

    def test_chat_raw_logs_full_payload(self):
        with tempfile.TemporaryDirectory() as d:
            setup_dev_logging(log_dir=d)

            mock_msg = MagicMock()
            mock_msg.content = "ok"
            mock_msg.tool_calls = None
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message = mock_msg
            mock_resp.usage = None
            mock_resp.model_dump.return_value = {}

            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_resp

            messages = [
                {"role": "system", "content": "system-prompt-x"},
                {"role": "user", "content": "hi"},
            ]
            tools = [{"type": "function", "function": {"name": "code_execution"}}]
            chat_raw(mock_client, messages, model="test-model", tools=tools, tool_choice="auto")

            files = list(Path(d).glob("*.log"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text(encoding="utf-8")
            self.assertIn("chat request", text)
            self.assertIn("system-prompt-x", text)
            self.assertIn('"messages"', text)
            self.assertIn("test-model", text)


if __name__ == "__main__":
    unittest.main()
