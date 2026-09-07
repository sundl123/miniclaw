"""单元测试：rules 系统、todo_write 工具、ask_followup_question 工具。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.rules import load_rules
from miniclaw.tools.todo_write import get_todos, handle_todo_write
from miniclaw.skills import build_system_prompt


# ---------------------------------------------------------------------------
# Rules 系统测试
# ---------------------------------------------------------------------------

class TestRulesLoading(unittest.TestCase):
    """测试 rules 文件扫描与加载。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, relpath: str, content: str):
        path = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_no_rules_returns_none(self):
        self.assertIsNone(load_rules(self.tmp))

    def test_agents_md_only(self):
        self._write("AGENTS.md", "# Project Rules\nBe nice.")
        result = load_rules(self.tmp)
        self.assertIsNotNone(result)
        self.assertIn("# Project Rules", result)
        self.assertIn("Be nice.", result)

    def test_rules_dir_only(self):
        self._write(".miniclaw/rules/style.md", "Always use spaces.")
        self._write(".miniclaw/rules/security.md", "No eval().")
        result = load_rules(self.tmp)
        self.assertIsNotNone(result)
        self.assertIn("### style", result)
        self.assertIn("Always use spaces.", result)
        self.assertIn("### security", result)
        self.assertIn("No eval().", result)

    def test_agents_md_and_rules_combined(self):
        self._write("AGENTS.md", "# Project Rules\nUse type hints.")
        self._write(".miniclaw/rules/test.md", "Write tests.")
        result = load_rules(self.tmp)
        self.assertIsNotNone(result)
        self.assertIn("Use type hints.", result)
        self.assertIn("Write tests.", result)
        self.assertIn("---", result)  # separator

    def test_rules_sorted_by_name(self):
        self._write(".miniclaw/rules/c.md", "C")
        self._write(".miniclaw/rules/a.md", "A")
        self._write(".miniclaw/rules/b.md", "B")
        result = load_rules(self.tmp)
        idx_a = result.index("### a")
        idx_b = result.index("### b")
        idx_c = result.index("### c")
        self.assertLess(idx_a, idx_b)
        self.assertLess(idx_b, idx_c)

    def test_skips_non_md_files(self):
        self._write(".miniclaw/rules/config.json", "{}")
        self._write(".miniclaw/rules/.gitkeep", "")
        self._write(".miniclaw/rules/style.md", "Use spaces.")
        result = load_rules(self.tmp)
        self.assertIn("style", result)
        self.assertNotIn("config.json", result)

    def test_oversized_file_skipped(self):
        content = "x" * 33000
        self._write(".miniclaw/rules/big.md", content)
        result = load_rules(self.tmp)
        self.assertIsNone(result)

    def test_empty_file_skipped(self):
        self._write(".miniclaw/rules/empty.md", "\n\n")
        result = load_rules(self.tmp)
        self.assertIsNone(result)

    def test_system_prompt_includes_rules(self):
        prompt = build_system_prompt(
            [], workspace_root="/tmp",
            rules_block="## My Rules\nAlways lint.",
        )
        self.assertIn("项目规则", prompt)
        self.assertIn("Always lint.", prompt)

    def test_system_prompt_without_rules(self):
        prompt = build_system_prompt([], workspace_root="/tmp")
        self.assertNotIn("项目规则", prompt)


# ---------------------------------------------------------------------------
# todo_write 工具测试
# ---------------------------------------------------------------------------

class TestTodoWrite(unittest.TestCase):
    """测试 todo_write 工具（任务列表存活于 context，不落盘）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ctx = {}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, todos, merge=False):
        return handle_todo_write(
            {"todos": todos, "merge": merge}, self.tmp, context=self.ctx,
        )

    def test_create_todos_replace(self):
        result = self._write([
            {"content": "Add login", "status": "pending"},
            {"content": "Add dashboard", "status": "in_progress"},
        ])
        self.assertIn("2 条", result)
        self.assertIn("Add login", result)
        self.assertIn("in_progress", result)

    def test_create_todos_cancelled_item(self):
        result = self._write([{"content": "Won't do", "status": "cancelled"}])
        self.assertIn("cancelled", result)

    def test_merge_updates_existing_by_id(self):
        self._write([
            {"content": "Task A", "status": "pending", "id": "a"},
            {"content": "Task B", "status": "pending", "id": "b"},
        ])
        result = self._write(
            [{"content": "Task A", "status": "completed", "id": "a"}], merge=True,
        )
        lines = result.split("\n")
        self.assertTrue(any("Task A" in l and "completed" in l for l in lines),
                        f"Task A should be completed in:\n{result}")
        self.assertTrue(any("Task B" in l and "pending" in l for l in lines),
                        f"Task B should remain pending in:\n{result}")

    def test_merge_adds_new_without_id(self):
        self._write([{"content": "Task A", "status": "pending", "id": "a"}])
        result = self._write([{"content": "Task B", "status": "pending"}], merge=True)
        self.assertIn("Task A", result)
        self.assertIn("Task B", result)

    def test_empty_todos(self):
        result = self._write([])
        self.assertIn("（暂无任务）", result)

    def test_invalid_status_defaults_to_pending(self):
        result = self._write([{"content": "Bad status", "status": "invalid_status"}])
        self.assertIn("pending", result)

    def test_missing_content_skipped(self):
        result = self._write([
            {"content": "Valid", "status": "pending"},
            {"content": "", "status": "pending"},
            {"content": "   ", "status": "pending"},
        ])
        self.assertIn("1 条", result)
        self.assertIn("Valid", result)

    def test_error_on_non_list_todos(self):
        result = handle_todo_write(
            {"todos": "not_a_list", "merge": False}, self.tmp, context=self.ctx,
        )
        data = json.loads(result)
        self.assertIn("error", data)

    def test_stores_in_context_not_on_disk(self):
        self._write([{"content": "Write tests", "status": "completed"}])
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, ".miniclaw", "todos.json")),
            "todo_write 不应再往工作区落盘",
        )
        stored = get_todos(self.ctx)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["content"], "Write tests")

    def test_merge_preserves_existing_order(self):
        """回归：只更新中间一项时，列表顺序不得被打乱。"""
        self._write([
            {"content": "A", "status": "pending", "id": "a"},
            {"content": "B", "status": "pending", "id": "b"},
            {"content": "C", "status": "pending", "id": "c"},
        ])
        self._write([{"content": "B", "status": "in_progress", "id": "b"}], merge=True)
        self.assertEqual([t["id"] for t in get_todos(self.ctx)], ["a", "b", "c"])

    def test_merge_appends_new_items_at_end(self):
        self._write([{"content": "A", "status": "pending", "id": "a"}])
        self._write([{"content": "Z", "status": "pending", "id": "z"}], merge=True)
        self.assertEqual([t["id"] for t in get_todos(self.ctx)], ["a", "z"])

    def test_merge_without_id_matches_by_content(self):
        """回归：无 id 条目重复 merge 不得累积成多份。"""
        self._write([{"content": "Same task", "status": "pending"}])
        for _ in range(3):
            self._write([{"content": "Same task", "status": "in_progress"}], merge=True)
        stored = get_todos(self.ctx)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], "in_progress")

    def test_replace_discards_previous_list(self):
        self._write([{"content": "Old", "status": "pending"}])
        self._write([{"content": "New", "status": "pending"}])
        self.assertEqual([t["content"] for t in get_todos(self.ctx)], ["New"])

    def test_without_context_is_stateless(self):
        handle_todo_write({"todos": [{"content": "A", "status": "pending"}],
                           "merge": False}, self.tmp)
        result = handle_todo_write({"todos": [{"content": "B", "status": "pending"}],
                                    "merge": True}, self.tmp)
        self.assertIn("1 条", result)
        self.assertNotIn("A", result)

    def test_todo_write_result_not_micro_compacted(self):
        """任务清单是模型的 self-conditioning 依据，不能被微压缩掉。"""
        from miniclaw.context.micro_compact import TOOL_COMPACT_POLICY
        self.assertFalse(TOOL_COMPACT_POLICY["todo_write"].compact_output)


class TestTodoWriteDispatch(unittest.TestCase):
    """测试 dispatch 层把 context 透传给 todo_write 并渲染清单。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dispatch_threads_context_and_renders(self):
        from miniclaw.tools import execute_tool
        context = {"workspace_root": self.tmp, "mode": "agent"}
        with patch("miniclaw.tools.dispatch.print_todos") as mock_render, \
                patch("miniclaw.tools.dispatch.print_tool_call"):
            execute_tool(
                "todo_write",
                {"todos": [{"content": "Step one", "status": "in_progress"}],
                 "merge": False},
                workspace_root=self.tmp,
                context=context,
            )
        self.assertEqual(
            [t["content"] for t in get_todos(context)], ["Step one"],
        )
        mock_render.assert_called_once()
        rendered = mock_render.call_args.args[0]
        self.assertEqual(rendered[0]["content"], "Step one")

    def test_dispatch_merge_across_calls_uses_context(self):
        from miniclaw.tools import execute_tool
        context = {"workspace_root": self.tmp, "mode": "agent"}
        with patch("miniclaw.tools.dispatch.print_todos"), \
                patch("miniclaw.tools.dispatch.print_tool_call"):
            execute_tool(
                "todo_write",
                {"todos": [{"content": "A", "status": "pending", "id": "a"},
                           {"content": "B", "status": "pending", "id": "b"}],
                 "merge": False},
                workspace_root=self.tmp, context=context,
            )
            execute_tool(
                "todo_write",
                {"todos": [{"content": "A", "status": "completed", "id": "a"}],
                 "merge": True},
                workspace_root=self.tmp, context=context,
            )
        stored = get_todos(context)
        self.assertEqual([t["id"] for t in stored], ["a", "b"])
        self.assertEqual(stored[0]["status"], "completed")

    def test_dispatch_renders_with_agent_depth_indent(self):
        """sub-agent 的清单要带缩进渲染，避免与主 agent 混淆。"""
        from miniclaw.tools import execute_tool
        context = {"workspace_root": self.tmp, "mode": "agent", "agent_depth": 1}
        with patch("miniclaw.tools.dispatch.print_todos") as mock_render, \
                patch("miniclaw.tools.dispatch.print_tool_call"):
            execute_tool(
                "todo_write",
                {"todos": [{"content": "child task", "status": "pending"}],
                 "merge": False},
                workspace_root=self.tmp, context=context,
            )
        self.assertEqual(mock_render.call_args.kwargs["indent"], 1)

    def test_subagent_todos_isolated_from_parent(self):
        """子 agent 的清单与主 agent 完全隔离，replace/merge 都不得影响父。"""
        from miniclaw.subagent.runner import build_child_context
        from miniclaw.subagent.types import GENERAL
        from miniclaw.tools import execute_tool

        parent = {"workspace_root": self.tmp, "mode": "agent", "agent_depth": 0}
        with patch("miniclaw.tools.dispatch.print_todos"), \
                patch("miniclaw.tools.dispatch.print_tool_call"):
            execute_tool(
                "todo_write",
                {"todos": [{"content": "parent task", "status": "in_progress",
                            "id": "p1"}], "merge": False},
                workspace_root=self.tmp, context=parent,
            )
            child = build_child_context(parent, definition=GENERAL)
            self.assertEqual(get_todos(child), [])
            for merge in (False, True):
                execute_tool(
                    "todo_write",
                    {"todos": [{"content": "child task", "status": "pending",
                                "id": "c1"}], "merge": merge},
                    workspace_root=self.tmp, context=child,
                )

        self.assertEqual([t["id"] for t in get_todos(child)], ["c1"])
        self.assertEqual([t["id"] for t in get_todos(parent)], ["p1"])
        self.assertIsNot(get_todos(child), get_todos(parent))


# ---------------------------------------------------------------------------
# ask_followup_question 工具测试
# ---------------------------------------------------------------------------

class TestAskFollowup(unittest.TestCase):
    """测试 ask_followup_question 工具。"""

    def test_requires_question(self):
        from miniclaw.tools.ask import handle_ask
        result = handle_ask({"question": ""}, "/tmp")
        data = json.loads(result)
        self.assertIn("error", data)

    def test_returns_answer_json(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="my answer"):
            result = handle_ask({"question": "What framework?"}, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["answer"], "my answer")
        self.assertIn("question", data)

    def test_with_options_and_header(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="2"):
            result = handle_ask({
                "question": "Pick one",
                "header": "Choice",
                "options": ["React", "Vue", "Svelte"],
            }, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["answer"], "2")
        self.assertEqual(data["question"], "Pick one")

    def test_with_dict_options(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="1"):
            result = handle_ask({
                "question": "Which one?",
                "options": [
                    {"label": "React", "description": "Fast"},
                    {"label": "Vue", "description": "Simple"},
                ],
            }, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["answer"], "1")

    def test_multi_select(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="1,3"):
            result = handle_ask({
                "question": "Select",
                "options": ["A", "B", "C"],
                "multi_select": True,
            }, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["answer"], "1,3")

    def test_rejects_non_list_options(self):
        from miniclaw.tools.ask import handle_ask
        result = handle_ask({
            "question": "Q",
            "options": "not_a_list",
        }, "/tmp")
        data = json.loads(result)
        self.assertIn("error", data)

    def test_renders_question_and_options(self):
        """问题与选项必须真正输出到终端，否则用户看不到选项框。"""
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="1"), \
                patch("miniclaw.tools.ask.console") as mock_console:
            handle_ask({
                "question": "Pick one",
                "header": "Choice",
                "options": ["React", {"label": "Vue", "description": "Simple"}],
            }, "/tmp")
        self.assertTrue(mock_console.print.called)
        rendered = "".join(
            str(getattr(call.args[0], "renderable", call.args[0]) if call.args else "")
            for call in mock_console.print.call_args_list
        )
        self.assertIn("Pick one", rendered)
        self.assertIn("React", rendered)
        self.assertIn("Vue", rendered)
        self.assertIn("Simple", rendered)

    def test_renders_without_options(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="free text"), \
                patch("miniclaw.tools.ask.console") as mock_console:
            handle_ask({"question": "Anything?"}, "/tmp")
        self.assertTrue(mock_console.print.called)

    def test_maps_index_to_label(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="2"), \
                patch("miniclaw.tools.ask.console"):
            result = handle_ask({
                "question": "Pick one",
                "options": ["React", {"label": "Vue"}, "Svelte"],
            }, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["answer"], "2")
        self.assertEqual(data["selected"], ["Vue"])

    def test_maps_multi_select_indexes(self):
        from miniclaw.tools.ask import handle_ask
        with patch("miniclaw.tools.ask.prompt", return_value="1, 3"), \
                patch("miniclaw.tools.ask.console"):
            result = handle_ask({
                "question": "Select",
                "options": ["A", "B", "C"],
                "multi_select": True,
            }, "/tmp")
        data = json.loads(result)
        self.assertEqual(data["selected"], ["A", "C"])

    def test_free_text_answer_has_no_selected(self):
        from miniclaw.tools.ask import handle_ask
        for raw in ("Svelte", "0", "9", ""):
            with self.subTest(raw=raw):
                with patch("miniclaw.tools.ask.prompt", return_value=raw), \
                        patch("miniclaw.tools.ask.console"):
                    result = handle_ask({
                        "question": "Pick one",
                        "options": ["A", "B"],
                    }, "/tmp")
                data = json.loads(result)
                self.assertNotIn("selected", data)
                self.assertEqual(data["answer"], raw.strip())

    def test_cancelled_input_returns_error(self):
        from miniclaw.tools.ask import handle_ask
        for exc in (EOFError, KeyboardInterrupt):
            with self.subTest(exc=exc.__name__):
                with patch("miniclaw.tools.ask.prompt", side_effect=exc), \
                        patch("miniclaw.tools.ask.console"):
                    result = handle_ask({"question": "Q"}, "/tmp")
                data = json.loads(result)
                self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
