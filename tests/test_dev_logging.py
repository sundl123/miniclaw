"""开发者日志与 chat_raw 请求记录。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from miniclaw.api import chat_raw
from miniclaw.dev_logging import setup_dev_logging


class TestDevLogging(unittest.TestCase):
    def test_setup_creates_timestamped_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = setup_dev_logging(log_dir=d)
            self.assertTrue(Path(path).is_file())
            self.assertTrue(path.endswith(".log"))
            self.assertIn(Path(path).name, os.listdir(d))

    def test_chat_raw_logs_full_payload_redacts_key(self):
        with tempfile.TemporaryDirectory() as d:
            setup_dev_logging(log_dir=d)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "base_resp": {"status_code": 0},
                "choices": [{"message": {"content": "ok"}}],
            }
            mock_resp.raise_for_status = MagicMock()
            messages = [{"role": "system", "content": "system-prompt-x"}, {"role": "user", "content": "hi"}]
            tools = [{"type": "function", "function": {"name": "code_execution"}}]
            with patch("miniclaw.api.requests.post", return_value=mock_resp):
                chat_raw("secret-api-key", messages, model="test-model", tools=tools, tool_choice="auto")

            files = list(Path(d).glob("*.log"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text(encoding="utf-8")
            self.assertIn("chat_raw request", text)
            self.assertIn("system-prompt-x", text)
            self.assertIn('"messages"', text)
            self.assertIn('"tools"', text)
            self.assertIn("test-model", text)
            self.assertIn("Bearer ***", text)
            self.assertNotIn("secret-api-key", text)


if __name__ == "__main__":
    unittest.main()
