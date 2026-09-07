"""Sub-agent unit tests (no live network)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from miniclaw.subagent.config import SubagentConfig
from miniclaw.subagent.prompt import append_worker_instructions
from miniclaw.subagent.runner import (
    build_child_context,
    filter_tools_for_agent,
    run_subagent,
)
from miniclaw.subagent.tool import get_agent_tool_schema, handle_agent
from miniclaw.subagent.types import EXPLORE, GENERAL, resolve_agent_definition
from miniclaw.tools import execute_tool, get_tool_schemas


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


class TestAgentTypes(unittest.TestCase):
    def test_default_general(self):
        self.assertEqual(resolve_agent_definition(None).agent_type, "general")
        self.assertEqual(resolve_agent_definition("").agent_type, "general")

    def test_unknown_returns_none(self):
        self.assertIsNone(resolve_agent_definition("nope"))


class TestFilterTools(unittest.TestCase):
    def setUp(self):
        self.parent = [
            _schema("read"),
            _schema("write"),
            _schema("edit"),
            _schema("grep"),
            _schema("glob"),
            _schema("bash"),
            _schema("Skill"),
            _schema("Agent"),
            _schema("memory"),
            _schema("session_search"),
            _schema("enter_plan_mode"),
        ]

    def test_general_strips_agent_memory_session(self):
        names = {s["function"]["name"] for s in filter_tools_for_agent(self.parent, GENERAL)}
        self.assertNotIn("Agent", names)
        self.assertNotIn("memory", names)
        self.assertNotIn("session_search", names)
        self.assertIn("write", names)
        self.assertIn("read", names)

    def test_explore_whitelist(self):
        names = {s["function"]["name"] for s in filter_tools_for_agent(self.parent, EXPLORE)}
        self.assertEqual(names, {"read", "grep", "glob", "bash", "Skill"})

    def test_todo_write_general_only(self):
        """general 可以自己维护任务清单；explore 只读，拿不到 todo_write。

        用真实 schema 列表，确保 todo_write 真的在父工具池里。
        """
        real_parent = get_tool_schemas(
            include_memory=True, include_session_search=True, include_agent=True,
        )
        self.assertIn(
            "todo_write",
            {s["function"]["name"] for s in real_parent},
        )
        general = {s["function"]["name"]
                   for s in filter_tools_for_agent(real_parent, GENERAL)}
        explore = {s["function"]["name"]
                   for s in filter_tools_for_agent(real_parent, EXPLORE)}
        self.assertIn("todo_write", general)
        self.assertNotIn("todo_write", explore)


class TestSchemas(unittest.TestCase):
    def test_include_agent_false(self):
        schemas = get_tool_schemas(include_agent=False)
        names = {s["function"]["name"] for s in schemas}
        self.assertNotIn("Agent", names)

    def test_include_agent_true(self):
        schemas = get_tool_schemas(include_agent=True)
        names = {s["function"]["name"] for s in schemas}
        self.assertIn("Agent", names)
        agent = get_agent_tool_schema()
        self.assertEqual(agent["function"]["name"], "Agent")


class TestPrompt(unittest.TestCase):
    def test_worker_appended(self):
        out = append_worker_instructions("BASE", "general")
        self.assertIn("BASE", out)
        self.assertIn("sub-agent worker", out)
        self.assertNotIn("READ-ONLY explore", out)

    def test_explore_extra(self):
        out = append_worker_instructions("BASE", "explore")
        self.assertIn("READ-ONLY explore", out)


class TestChildContext(unittest.TestCase):
    def test_increments_depth_and_drops_writer(self):
        parent = {
            "agent_depth": 0,
            "mode": "plan",
            "records_writer": object(),
            "skill_registry": "reg",
            "todos": [{"content": "parent task", "status": "in_progress"}],
        }
        child = build_child_context(parent, definition=EXPLORE)
        self.assertEqual(child["agent_depth"], 1)
        self.assertTrue(child["readonly_bash_only"])
        self.assertNotIn("records_writer", child)
        self.assertNotIn("todos", child)  # sub-agent must not inherit parent plan
        self.assertEqual(child["mode"], "plan")
        self.assertEqual(parent["agent_depth"], 0)  # parent untouched
        self.assertEqual(len(parent["todos"]), 1)  # parent plan untouched


class TestDepthGuard(unittest.TestCase):
    def test_handle_agent_rejects_nested(self):
        out = handle_agent(
            {"description": "x", "prompt": "y"},
            "/tmp",
            context={"agent_depth": 1, "subagent_config": SubagentConfig(enabled=True)},
        )
        data = json.loads(out)
        self.assertIn("error", data)
        self.assertIn("depth", data["error"].lower())


class TestExploreReadonlyBash(unittest.TestCase):
    def test_rejects_rm(self):
        ctx = {"readonly_bash_only": True, "workspace_root": os.getcwd()}
        out = execute_tool("bash", {"command": "rm -rf /tmp/x"}, context=ctx)
        data = json.loads(out)
        self.assertIn("error", data)
        self.assertIn("read-only", data["error"].lower())

    def test_allows_ls(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {"readonly_bash_only": True, "workspace_root": td}
            out = execute_tool("bash", {"command": "ls"}, context=ctx)
            # should not be a JSON error
            if out.startswith("{"):
                data = json.loads(out)
                self.assertNotIn("error", data)


class TestPlanModeInherited(unittest.TestCase):
    def test_write_blocked_in_plan_even_for_general_child(self):
        with tempfile.TemporaryDirectory() as td:
            plan_dir = os.path.join(td, "plans")
            os.makedirs(plan_dir)
            ctx = {
                "mode": "plan",
                "plan_dir": plan_dir,
                "workspace_root": td,
                "readonly_bash_only": False,
            }
            target = os.path.join(td, "code.py")
            out = execute_tool(
                "write",
                {"path": target, "content": "x"},
                workspace_root=td,
                context=ctx,
            )
            data = json.loads(out)
            self.assertIn("error", data)
            self.assertFalse(os.path.isfile(target))


class TestRunSubagent(unittest.TestCase):
    def _llm_ctx(self, **extra):
        tools = get_tool_schemas(include_agent=True, include_memory=True)
        ctx = {
            "agent_depth": 0,
            "mode": "agent",
            "subagent_config": SubagentConfig(enabled=True, max_turns=5),
            "llm": {
                "client": MagicMock(),
                "model": "test-model",
                "timeout": 30,
                "tools": tools,
                "system_prompt": "SYS",
                "context_config": None,
            },
        }
        ctx.update(extra)
        return ctx

    def test_disabled(self):
        ctx = self._llm_ctx(subagent_config=SubagentConfig(enabled=False))
        out = run_subagent(
            description="d",
            prompt="p",
            subagent_type="general",
            workspace_root="/tmp",
            context=ctx,
        )
        self.assertIn("disabled", json.loads(out)["error"].lower())

    def test_completed(self):
        ctx = self._llm_ctx()

        def _fake_run(*args, **kwargs):
            return "hello from child", [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "p"},
                {"role": "assistant", "content": "hello from child"},
            ]

        with patch("miniclaw.api.run_turn_with_tools", side_effect=_fake_run):
            out = run_subagent(
                description="find stuff",
                prompt="look around",
                subagent_type="explore",
                workspace_root="/tmp",
                context=ctx,
            )
        data = json.loads(out)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["agent_type"], "explore")
        self.assertEqual(data["result"], "hello from child")
        self.assertEqual(data["tool_use_count"], 0)

    def test_truncated(self):
        ctx = self._llm_ctx()

        def _fake_run(*args, **kwargs):
            child_ctx = kwargs["context"]
            child_ctx["_subagent_truncated"] = True
            return "partial", [
                {"role": "assistant", "content": "partial"},
                {"role": "tool", "content": "x"},
            ]

        with patch("miniclaw.api.run_turn_with_tools", side_effect=_fake_run):
            out = run_subagent(
                description="long",
                prompt="keep going",
                subagent_type="general",
                workspace_root="/tmp",
                context=ctx,
            )
        data = json.loads(out)
        self.assertEqual(data["status"], "truncated")
        self.assertEqual(data["tool_use_count"], 1)
        self.assertIn("max_turns", data.get("error", ""))


class TestSubagentConfigEnv(unittest.TestCase):
    def test_env_override(self):
        from miniclaw.settings import get_subagent_config

        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"MINICLAW_SUBAGENT": "1"}):
                cfg = get_subagent_config(td)
            self.assertTrue(cfg.enabled)

            with patch.dict(os.environ, {"MINICLAW_SUBAGENT": "0"}):
                cfg = get_subagent_config(td)
            self.assertFalse(cfg.enabled)


if __name__ == "__main__":
    unittest.main()
