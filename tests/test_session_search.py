"""Tests for session_search tool."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.sessions.config import SessionsConfig
from miniclaw.sessions.db import SessionDB
from miniclaw.sessions.records import RecordsWriter
from miniclaw.sessions.search import handle_session_search
from miniclaw.tools import execute_tool, get_tool_schemas


class TestSessionSearch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.user_root = os.path.join(self._tmpdir.name, ".miniclaw")
        os.makedirs(self.user_root)
        self.db_path = os.path.join(self.user_root, "state.db")
        os.makedirs(os.path.join(self.user_root, "records"))

        self.patcher_data = patch(
            "miniclaw.sessions.paths.get_user_data_dir",
            return_value=self.user_root,
        )
        self.patcher_db = patch(
            "miniclaw.sessions.records.get_state_db_path",
            return_value=self.db_path,
        )
        self.patcher_data.start()
        self.patcher_db.start()

        self.cfg = SessionsConfig(enabled=True)
        self.current_writer = RecordsWriter.open(
            self.cfg, workspace="/current", model="m1",
        )
        self.current_writer.append_user("current session noise")

        self.past_writer = RecordsWriter.open(
            self.cfg, workspace="/past", model="m1",
        )
        self.past_writer.append_user("We discussed agent harness architecture")
        self.past_writer.append_assistant({
            "role": "assistant",
            "content": "Agent harness layers: records, memory, skills.",
        })
        self.past_sid = self.past_writer.session_id
        self.past_match_seq = 2

        self.db = SessionDB(self.db_path)

    def tearDown(self):
        self.patcher_db.stop()
        self.patcher_data.stop()
        self._tmpdir.cleanup()

    def test_disabled_without_db(self):
        out = json.loads(handle_session_search({}))
        self.assertFalse(out["success"])

    def test_browse_excludes_current_session(self):
        out = json.loads(handle_session_search(
            {},
            db=self.db,
            current_session_id=self.current_writer.session_id,
            config=self.cfg,
        ))
        self.assertTrue(out["success"])
        self.assertEqual(out["shape"], "browse")
        ids = [r["session_id"] for r in out["results"]]
        self.assertNotIn(self.current_writer.session_id, ids)
        self.assertIn(self.past_sid, ids)

    def test_discovery_finds_past_topic(self):
        out = json.loads(handle_session_search(
            {"query": "harness"},
            db=self.db,
            current_session_id=self.current_writer.session_id,
            config=self.cfg,
        ))
        self.assertTrue(out["success"])
        self.assertEqual(out["shape"], "discovery")
        self.assertGreaterEqual(out["count"], 1)
        hit = out["hits"][0]
        self.assertEqual(hit["session_id"], self.past_sid)
        self.assertIn("bookend_start", hit)
        self.assertIn("window", hit)

    def test_scroll_rejects_current_session(self):
        out = json.loads(handle_session_search(
            {
                "session_id": self.current_writer.session_id,
                "around_seq": 2,
            },
            db=self.db,
            current_session_id=self.current_writer.session_id,
            config=self.cfg,
        ))
        self.assertFalse(out["success"])

    def test_scroll_past_session(self):
        out = json.loads(handle_session_search(
            {
                "session_id": self.past_sid,
                "around_seq": self.past_match_seq,
                "window": 2,
            },
            db=self.db,
            current_session_id=self.current_writer.session_id,
            config=self.cfg,
        ))
        self.assertTrue(out["success"])
        self.assertEqual(out["shape"], "scroll")
        self.assertGreaterEqual(len(out["messages"]), 1)

    def test_schema_included_when_enabled(self):
        schemas = get_tool_schemas(include_session_search=True)
        names = [s["function"]["name"] for s in schemas]
        self.assertIn("session_search", names)

    def test_execute_tool_session_search(self):
        ctx = {
            "session_db": self.db,
            "session_id": self.current_writer.session_id,
            "sessions_config": self.cfg,
        }
        result = json.loads(execute_tool(
            "session_search",
            {"query": "harness"},
            workspace_root=self._tmpdir.name,
            context=ctx,
        ))
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
