"""开发者日志与 chat_raw 请求记录。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from miniclaw.api import chat_raw
from miniclaw.dev_logging import setup_dev_logging, _rotate_if_needed, _cleanup_old_backups


class TestDevLogging(unittest.TestCase):
    def test_setup_creates_fixed_name_log(self):
        """测试 setup_dev_logging 创建固定文件名的日志"""
        with tempfile.TemporaryDirectory() as d:
            path = setup_dev_logging(log_dir=d)
            self.assertEqual(Path(path).name, "dev.log")
            self.assertTrue(Path(path).is_file())
            self.assertIn("dev.log", os.listdir(d))

    def test_setup_logs_startup_timestamp(self):
        """测试日志内容包含启动时间戳"""
        with tempfile.TemporaryDirectory() as d:
            path = setup_dev_logging(log_dir=d)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("dev log started at 20", content)

    def test_rotation_triggers_when_file_exceeds_max_bytes(self):
        """测试文件超过 max_bytes 时触发轮转"""
        with tempfile.TemporaryDirectory() as d:
            current_log = os.path.join(d, "dev.log")

            # 创建 3000 字节的文件（超过 2000 阈值）
            with open(current_log, "w") as f:
                f.write("x" * 3000)

            # 触发轮转（max_bytes=2000, backup_count=3）
            _rotate_if_needed(d, current_log, max_bytes=2000, backup_count=3)

            # 验证：当前日志应该被重命名
            self.assertFalse(os.path.exists(current_log))
            rotated_files = [f for f in os.listdir(d) if f.startswith("dev.log.")]
            self.assertEqual(len(rotated_files), 1)

            # 验证：轮转后的文件应该保留原内容
            rotated_content = Path(os.path.join(d, rotated_files[0])).read_text()
            self.assertEqual(len(rotated_content), 3000)

    def test_rotation_skips_small_file(self):
        """测试文件未超过阈值时不触发轮转"""
        with tempfile.TemporaryDirectory() as d:
            current_log = os.path.join(d, "dev.log")

            # 创建 100 字节的文件（小于 2000 阈值）
            with open(current_log, "w") as f:
                f.write("x" * 100)

            _rotate_if_needed(d, current_log, max_bytes=2000, backup_count=3)

            # 验证：当前日志应该保持不变
            self.assertTrue(os.path.exists(current_log))
            self.assertEqual(os.path.getsize(current_log), 100)
            rotated_files = [f for f in os.listdir(d) if f.startswith("dev.log.")]
            self.assertEqual(len(rotated_files), 0)

    def test_cleanup_removes_old_backups(self):
        """测试清理超过数量的旧备份"""
        import time
        with tempfile.TemporaryDirectory() as d:
            # 创建 5 个备份文件（按顺序创建，让 mtime 不同）
            for i in range(5):
                path = os.path.join(d, f"dev.log.20260412-120000-00000{i}")
                with open(path, "w") as f:
                    f.write(f"old-{i}")
                time.sleep(0.01)  # 确保 mtime 不同

            # 清理后保留 3 个
            _cleanup_old_backups(d, backup_count=3)

            remaining = sorted([f for f in os.listdir(d) if f.startswith("dev.log.")])
            self.assertEqual(len(remaining), 3)
            # 验证保留的是最新的 3 个（i=0,1 最旧，被删除）
            self.assertTrue(any(f.endswith("2") for f in remaining))
            self.assertTrue(any(f.endswith("3") for f in remaining))
            self.assertTrue(any(f.endswith("4") for f in remaining))
            self.assertFalse(any(f.endswith("0") for f in remaining))
            self.assertFalse(any(f.endswith("1") for f in remaining))

    def test_chat_raw_logs_full_payload(self):
        """测试 chat_raw 记录完整的请求和响应"""
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

            files = list(Path(d).glob("dev.log"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text(encoding="utf-8")
            self.assertIn("chat request", text)
            self.assertIn("system-prompt-x", text)
            self.assertIn('"messages"', text)
            self.assertIn("test-model", text)


if __name__ == "__main__":
    unittest.main()
