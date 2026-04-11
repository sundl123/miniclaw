"""CLI 模块的单元测试。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from miniclaw.dirs import resolve_workspace, ensure_user_config


class TestResolveWorkspace(unittest.TestCase):
    def test_defaults_to_cwd(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINICLAW_WORKSPACE", None)
            result = resolve_workspace(None)
        self.assertEqual(result, os.getcwd())

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


class TestEnsureUserConfig(unittest.TestCase):
    """ensure_user_config() 的单元测试，使用临时目录模拟 ~/.miniclaw/。"""

    def _run_with_temp_home(self, callback):
        """在临时目录中模拟 USER_DATA_DIR 来运行测试。"""
        import miniclaw.dirs as dirs_mod
        with tempfile.TemporaryDirectory() as tmp:
            fake_data_dir = os.path.join(tmp, ".miniclaw")
            original = dirs_mod.USER_DATA_DIR
            dirs_mod.USER_DATA_DIR = fake_data_dir
            try:
                return callback(fake_data_dir)
            finally:
                dirs_mod.USER_DATA_DIR = original

    def test_creates_dir_and_file(self):
        def check(data_dir):
            path, created = ensure_user_config()
            self.assertTrue(created)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(path, os.path.join(data_dir, "config.json"))
            return path
        self._run_with_temp_home(check)

    def test_created_file_is_valid_json(self):
        def check(data_dir):
            path, _ = ensure_user_config()
            with open(path) as f:
                data = json.load(f)
            self.assertIn("plan_mode", data)
            self.assertIsInstance(data["plan_mode"]["allowed_bash_patterns"], list)
        self._run_with_temp_home(check)

    def test_does_not_overwrite_existing(self):
        def check(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            config_path = os.path.join(data_dir, "config.json")
            with open(config_path, "w") as f:
                f.write('{"custom": true}')
            path, created = ensure_user_config()
            self.assertFalse(created)
            with open(path) as f:
                data = json.load(f)
            self.assertTrue(data["custom"])
        self._run_with_temp_home(check)

    def test_force_overwrites(self):
        def check(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            config_path = os.path.join(data_dir, "config.json")
            with open(config_path, "w") as f:
                f.write('{"custom": true}')
            path, created = ensure_user_config(force=True)
            self.assertTrue(created)
            with open(path) as f:
                data = json.load(f)
            self.assertNotIn("custom", data)
            self.assertIn("plan_mode", data)
        self._run_with_temp_home(check)

    def test_second_call_returns_false(self):
        def check(data_dir):
            _, created1 = ensure_user_config()
            self.assertTrue(created1)
            _, created2 = ensure_user_config()
            self.assertFalse(created2)
        self._run_with_temp_home(check)


if __name__ == "__main__":
    unittest.main()
