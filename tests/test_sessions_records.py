"""Tests for session records dual-write."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.sessions.config import SessionsConfig
from miniclaw.sessions.db import SessionDB
from miniclaw.sessions.records import RecordsWriter


class TestSessionsRecords(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.user_root = os.path.join(self._tmpdir.name, ".miniclaw")
        os.makedirs(self.user_root)
        self.db_path = os.path.join(self.user_root, "state.db")
        self.records_dir = os.path.join(self.user_root, "records")
        os.makedirs(self.records_dir)

        self.patcher_data = patch(
            "miniclaw.sessions.paths.get_user_data_dir",
            return_value=self.user_root,
        )
        self.patcher_records = patch(
            "miniclaw.sessions.records.get_state_db_path",
            return_value=self.db_path,
        )
        self.patcher_data.start()
        self.patcher_records.start()

        self.cfg = SessionsConfig(enabled=True, records_max_event_bytes=100)

    def tearDown(self):
        self.patcher_records.stop()
        self.patcher_data.stop()
        self._tmpdir.cleanup()

    def test_dual_write_seq_alignment(self):
        writer = RecordsWriter.open(
            self.cfg, workspace="/proj", model="test-model",
        )
        writer.append_user("hello")
        writer.append_assistant({"role": "assistant", "content": "hi there"})

        db = SessionDB(self.db_path)
        rows = db.get_messages_around(writer.session_id, 2, window=5)["window"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["seq"], 2)
        self.assertEqual(rows[1]["seq"], 3)

        with open(writer._jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        seqs = [line["seq"] for line in lines]
        self.assertEqual(seqs, [1, 2, 3])
        self.assertEqual(lines[0]["type"], "session_start")

    def test_content_truncation(self):
        writer = RecordsWriter.open(
            self.cfg, workspace="/proj", model="test-model",
        )
        big = "x" * 500
        writer.append_user(big)

        with open(writer._jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        user_line = [l for l in lines if l.get("role") == "user"][0]
        self.assertTrue(user_line.get("truncated"))
        self.assertEqual(user_line["original_bytes"], 500)
        self.assertLessEqual(len(user_line["content"].encode("utf-8")), 100)

    def test_session_meta_events(self):
        writer = RecordsWriter.open(
            self.cfg, workspace="/proj", model="test-model",
        )
        writer.append_meta("session_clear")
        writer.mark_session_end()

        db = SessionDB(self.db_path)
        session = db.get_session(writer.session_id)
        self.assertIsNotNone(session.get("ended_at"))

        with open(writer._jsonl_path, "r", encoding="utf-8") as f:
            types = [json.loads(line).get("type") for line in f if line.strip()]
        self.assertIn("session_clear", types)
        self.assertIn("session_end", types)


if __name__ == "__main__":
    unittest.main()
