"""CLI 模块的单元测试。"""
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.cli import resolve_workspace
from miniclaw.config import WORKSPACE_ROOT


class TestResolveWorkspace(unittest.TestCase):
    def test_defaults_to_project_root(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINICLAW_WORKSPACE", None)
            result = resolve_workspace(None)
        self.assertEqual(result, WORKSPACE_ROOT)

    def test_env_var_overrides_default(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"MINICLAW_WORKSPACE": d}):
                result = resolve_workspace(None)
            self.assertEqual(result, os.path.abspath(d))

    def test_cli_arg_overrides_env_var(self):
        with tempfile.TemporaryDirectory() as cli_dir:
            with tempfile.TemporaryDirectory() as env_dir:
                with patch.dict(os.environ, {"MINICLAW_WORKSPACE": env_dir}):
                    result = resolve_workspace(cli_dir)
            self.assertEqual(result, os.path.abspath(cli_dir))

    def test_nonexistent_path_exits(self):
        with self.assertRaises(SystemExit):
            resolve_workspace("/nonexistent/path/that/does/not/exist")

    def test_relative_path_resolved_to_absolute(self):
        with tempfile.TemporaryDirectory() as d:
            basename = os.path.basename(d)
            parent = os.path.dirname(d)
            with patch("os.path.abspath", return_value=d):
                result = resolve_workspace(basename)
            self.assertTrue(os.path.isabs(result))


if __name__ == "__main__":
    unittest.main()
