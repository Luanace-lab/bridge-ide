from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bridge_mcp  # noqa: E402
import common  # noqa: E402
import start_agents  # noqa: E402
import tmux_manager  # noqa: E402


class TestBridgeMcpRegisterTokenFallback(unittest.TestCase):
    def test_prefers_env_register_token(self) -> None:
        with patch.dict(os.environ, {"BRIDGE_REGISTER_TOKEN": "env-register-token"}, clear=False):
            token = bridge_mcp._load_bridge_register_token("/tmp/does-not-matter.json")
        self.assertEqual(token, "env-register-token")

    def test_reads_register_token_from_tokens_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"register_token": "file-register-token"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"BRIDGE_REGISTER_TOKEN": ""}, clear=False):
                token = bridge_mcp._load_bridge_register_token(str(token_file))
        self.assertEqual(token, "file-register-token")

    def test_reads_register_token_from_env_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"register_token": "env-path-register-token"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BRIDGE_REGISTER_TOKEN": "",
                    "BRIDGE_TOKEN_CONFIG_FILE": str(token_file),
                },
                clear=False,
            ):
                token = bridge_mcp._load_bridge_register_token()
        self.assertEqual(token, "env-path-register-token")


class TestStartAgentsAuthBootstrap(unittest.TestCase):
    def test_prefers_env_user_token(self) -> None:
        with patch.dict(os.environ, {"BRIDGE_USER_TOKEN": "env-user-token"}, clear=False):
            token = start_agents._load_user_token(Path("/tmp/does-not-matter.json"))
        self.assertEqual(token, "env-user-token")

    def test_reads_user_token_from_tokens_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"user_token": "file-user-token"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"BRIDGE_USER_TOKEN": ""}, clear=False):
                token = start_agents._load_user_token(token_file)
        self.assertEqual(token, "file-user-token")

    def test_auth_headers_include_loaded_user_token(self) -> None:
        with patch.object(start_agents, "_load_user_token", return_value="loaded-user-token"):
            headers = start_agents._auth_headers()
        self.assertEqual(headers["X-Bridge-Token"], "loaded-user-token")
        self.assertEqual(headers["X-Bridge-Agent"], "system")
        self.assertEqual(headers["Content-Type"], "application/json")


class TestCommonAuthBootstrap(unittest.TestCase):
    def test_common_prefers_env_user_token(self) -> None:
        with patch.dict(os.environ, {"BRIDGE_USER_TOKEN": "common-env-user-token"}, clear=False):
            token = common.load_bridge_user_token(Path("/tmp/does-not-matter.json"))
        self.assertEqual(token, "common-env-user-token")

    def test_common_reads_user_token_from_env_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"user_token": "common-file-user-token"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BRIDGE_USER_TOKEN": "",
                    "BRIDGE_TOKEN_CONFIG_FILE": str(token_file),
                },
                clear=False,
            ):
                token = common.load_bridge_user_token()
        self.assertEqual(token, "common-file-user-token")

    def test_common_builds_auth_headers_with_agent_id(self) -> None:
        with patch.object(common, "load_bridge_user_token", return_value="common-loaded-user-token"):
            headers = common.build_bridge_auth_headers(
                agent_id="watcher",
                content_type="application/json; charset=utf-8",
            )
        self.assertEqual(headers["X-Bridge-Token"], "common-loaded-user-token")
        self.assertEqual(headers["X-Bridge-Agent"], "watcher")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_common_builds_ws_auth_message_from_loaded_user_token(self) -> None:
        with patch.object(common, "load_bridge_user_token", return_value="common-ws-user-token"):
            payload = common.build_bridge_ws_auth_message()
        self.assertEqual(payload, {"type": "auth", "token": "common-ws-user-token"})

    def test_common_http_get_json_forwards_headers(self) -> None:
        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"ok": true}'

        with patch.object(common, "urlopen", return_value=_Response()) as fake_urlopen:
            payload = common.http_get_json(
                "http://127.0.0.1:9111/history?limit=1",
                timeout=5.0,
                headers={"X-Bridge-Token": "header-token", "X-Bridge-Agent": "watcher"},
            )

        self.assertEqual(payload, {"ok": True})
        request = fake_urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-bridge-token"), "header-token")
        self.assertEqual(request.get_header("X-bridge-agent"), "watcher")


class TestTmuxManagerBridgeRuntimeEnv(unittest.TestCase):
    def test_bridge_runtime_env_includes_register_token_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"register_token": "runtime-file-register-token"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BRIDGE_REGISTER_TOKEN": "",
                    "BRIDGE_TOKEN_CONFIG_FILE": str(token_file),
                },
                clear=False,
            ):
                env = tmux_manager._bridge_runtime_env()
        self.assertEqual(env["BRIDGE_TOKEN_CONFIG_FILE"], str(token_file.resolve()))
        self.assertEqual(env["BRIDGE_REGISTER_TOKEN"], "runtime-file-register-token")

    def test_bridge_runtime_env_prefers_env_register_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text(
                json.dumps({"register_token": "file-register-token"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BRIDGE_REGISTER_TOKEN": "env-register-token",
                    "BRIDGE_TOKEN_CONFIG_FILE": str(token_file),
                },
                clear=False,
            ):
                env = tmux_manager._bridge_runtime_env()
        self.assertEqual(env["BRIDGE_REGISTER_TOKEN"], "env-register-token")


if __name__ == "__main__":
    unittest.main()
