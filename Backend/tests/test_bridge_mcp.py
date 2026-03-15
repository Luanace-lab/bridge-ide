"""
Unit tests for bridge_mcp.py reconnect/history recovery logic.
"""

import asyncio
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import load_bridge_agent_session_token  # noqa: E402


class TestBridgeMcpHistoryRecovery(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_recovers_unseen_targeted_and_broadcast_messages(self):
        mod = self._mod()
        history = [
            {"id": 100, "from": "user", "to": "codex", "content": "old"},
            {"id": 101, "from": "user", "to": "viktor", "content": "other agent"},
            {"id": 102, "from": "user", "to": "all", "content": "broadcast"},
            {"id": 103, "from": "codex", "to": "all", "content": "own broadcast"},
            {"id": 104, "from": "user", "to": "codex", "content": "new"},
        ]

        recoverable, new_last_seen = mod._select_recoverable_history_messages(
            history_msgs=history,
            agent_id="codex",
            last_seen_msg_id=101,
        )

        self.assertEqual([m["id"] for m in recoverable], [102, 104])
        self.assertEqual(new_last_seen, 104)

    def test_advances_last_seen_even_if_no_message_targets_agent(self):
        mod = self._mod()
        history = [
            {"id": 200, "from": "user", "to": "viktor", "content": "x"},
            {"id": 201, "from": "user", "to": "ordo", "content": "y"},
        ]

        recoverable, new_last_seen = mod._select_recoverable_history_messages(
            history_msgs=history,
            agent_id="codex",
            last_seen_msg_id=150,
        )

        self.assertEqual(recoverable, [])
        self.assertEqual(new_last_seen, 201)

    def test_ignores_invalid_ids(self):
        mod = self._mod()
        history = [
            {"id": None, "from": "user", "to": "codex"},
            {"id": "abc", "from": "user", "to": "codex"},
            {"id": "300", "from": "user", "to": "codex"},
        ]

        recoverable, new_last_seen = mod._select_recoverable_history_messages(
            history_msgs=history,
            agent_id="codex",
            last_seen_msg_id=250,
        )

        self.assertEqual([m["id"] for m in recoverable], ["300"])
        self.assertEqual(new_last_seen, 300)

    def test_normalize_last_seen_resets_on_server_restart_signal(self):
        mod = self._mod()
        self.assertEqual(
            mod._normalize_last_seen_for_possible_server_restart(
                20,
                200,
                source="history",
            ),
            -1,
        )
        self.assertEqual(
            mod._normalize_last_seen_for_possible_server_restart(
                190,
                200,
                source="history",
            ),
            200,
        )


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestBridgeMcpRegisterIdentityContract(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_bridge_register_forwards_cli_identity_env(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"ok": True, "session_token": "tok-register"})

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_once = mod._registered_once
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_bridge_post = mod._bridge_post
        old_ensure_background_tasks = mod._ensure_background_tasks
        try:
            mod._agent_id = None
            mod._session_token = None
            mod._registered_once = False
            mod._registered_role = ""
            mod._registered_capabilities = []
            mod._bridge_post = fake_bridge_post
            mod._ensure_background_tasks = lambda: None
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "",
                },
                clear=False,
            ):
                raw = asyncio.run(mod.bridge_register("codex", role="Coder", capabilities=["code"]))
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_once = old_registered_once
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._bridge_post = old_bridge_post
            mod._ensure_background_tasks = old_ensure_background_tasks

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(captured["path"], "/register")
        payload = captured["kwargs"]["json"]
        self.assertEqual(payload["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(payload["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(payload["project_root"], "/tmp/project")
        self.assertEqual(payload["instruction_path"], "/tmp/project/.agent_sessions/codex/AGENTS.md")
        self.assertEqual(payload["identity_source"], "cli_register")
        self.assertEqual(payload["cli_identity_source"], "cli_register")

    def test_auto_reregister_reuses_cli_identity_env(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"ok": True, "session_token": "tok-reregister"})

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._session_token = "tok-old"
            mod._registered_role = "Coder"
            mod._registered_capabilities = ["code"]
            mod._bridge_post = fake_bridge_post
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "",
                },
                clear=False,
            ):
                ok = asyncio.run(mod._auto_reregister())
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._bridge_post = old_bridge_post

        self.assertTrue(ok)
        self.assertEqual(captured["path"], "/register")
        payload = captured["kwargs"]["json"]
        self.assertEqual(payload["resume_id"], "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        self.assertEqual(payload["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(payload["project_root"], "/tmp/project")
        self.assertEqual(payload["context_lost"], False)
        self.assertEqual(payload["identity_source"], "cli_reregister")
        self.assertEqual(payload["cli_identity_source"], "cli_reregister")

    def test_bridge_heartbeat_reuses_cli_identity_env_and_auto_reregisters(self):
        mod = self._mod()
        captured: list[dict[str, object]] = []

        async def fake_bridge_post(path, **kwargs):
            captured.append({"path": path, "kwargs": kwargs})
            return _DummyResponse({"ok": True, "registered": False, "timestamp": "2026-03-11T15:00:00Z"})

        async def fake_auto_reregister():
            return True

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        old_auto_reregister = mod._auto_reregister
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            mod._auto_reregister = fake_auto_reregister
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "",
                },
                clear=False,
            ):
                raw = asyncio.run(mod.bridge_heartbeat())
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post
            mod._auto_reregister = old_auto_reregister

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertFalse(data["registered"])
        self.assertTrue(data["auto_reregistered"])
        self.assertEqual(captured[0]["path"], "/heartbeat")
        payload = captured[0]["kwargs"]["json"]
        self.assertEqual(payload["resume_id"], "cccccccc-cccc-cccc-cccc-cccccccccccc")
        self.assertEqual(payload["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(payload["project_root"], "/tmp/project")
        self.assertEqual(payload["instruction_path"], "/tmp/project/.agent_sessions/codex/AGENTS.md")
        self.assertEqual(payload["identity_source"], "cli_heartbeat")
        self.assertEqual(payload["cli_identity_source"], "cli_heartbeat")

    def test_bridge_receive_auto_registers_from_cli_identity_and_fetches_server_messages(self):
        mod = self._mod()
        captured: list[tuple[str, str, dict[str, object]]] = []

        async def fake_bridge_post(path, **kwargs):
            captured.append(("post", path, kwargs))
            return _DummyResponse({"ok": True, "session_token": "tok-auto"})

        async def fake_bridge_get(path, **kwargs):
            captured.append(("get", path, kwargs))
            return _DummyResponse({
                "agent": "codex",
                "count": 1,
                "messages": [{"id": 42, "from": "user", "to": "codex", "content": "hello"}],
            })

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_once = mod._registered_once
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_last_seen_msg_id = mod._last_seen_msg_id
        old_bridge_post = mod._bridge_post
        old_bridge_get = mod._bridge_get
        old_ensure_background_tasks = mod._ensure_background_tasks
        try:
            mod._agent_id = None
            mod._session_token = None
            mod._registered_once = False
            mod._registered_role = ""
            mod._registered_capabilities = []
            mod._last_seen_msg_id = -1
            mod._bridge_post = fake_bridge_post
            mod._bridge_get = fake_bridge_get
            mod._ensure_background_tasks = lambda: None
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_CLI_AGENT_ID": "codex",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "",
                },
                clear=False,
            ):
                raw = asyncio.run(mod.bridge_receive())
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_once = old_registered_once
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._last_seen_msg_id = old_last_seen_msg_id
            mod._bridge_post = old_bridge_post
            mod._bridge_get = old_bridge_get
            mod._ensure_background_tasks = old_ensure_background_tasks

        data = json.loads(raw)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["messages"][0]["id"], 42)
        self.assertEqual(captured[0][0], "post")
        self.assertEqual(captured[0][1], "/register")
        self.assertEqual(captured[1][0], "get")
        self.assertEqual(captured[1][1], "/receive/codex")

    def test_bridge_receive_server_fallback_updates_last_seen_message_id(self):
        mod = self._mod()

        async def fake_bridge_get(path, **kwargs):
            del kwargs
            self.assertEqual(path, "/receive/codex")
            return _DummyResponse({
                "agent": "codex",
                "count": 2,
                "messages": [
                    {"id": 7, "from": "user", "to": "codex", "content": "a"},
                    {"id": 9, "from": "user", "to": "codex", "content": "b"},
                ],
            })

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_last_seen_msg_id = mod._last_seen_msg_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._session_token = "tok-existing"
            mod._last_seen_msg_id = 3
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_receive())
            updated_last_seen = mod._last_seen_msg_id
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._last_seen_msg_id = old_last_seen_msg_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 2)
        self.assertEqual(updated_last_seen, 9)

    def test_bridge_receive_server_fallback_filters_already_seen_messages(self):
        mod = self._mod()

        async def fake_bridge_get(path, **kwargs):
            del kwargs
            self.assertEqual(path, "/receive/codex")
            return _DummyResponse({
                "agent": "codex",
                "count": 3,
                "messages": [
                    {"id": 7, "from": "user", "to": "codex", "content": "dup-a"},
                    {"id": 8, "from": "user", "to": "codex", "content": "dup-b"},
                    {"id": 9, "from": "user", "to": "codex", "content": "fresh"},
                ],
            })

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_last_seen_msg_id = mod._last_seen_msg_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._session_token = "tok-existing"
            mod._last_seen_msg_id = 8
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_receive())
            updated_last_seen = mod._last_seen_msg_id
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._last_seen_msg_id = old_last_seen_msg_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 1)
        self.assertEqual([m["id"] for m in data["messages"]], [9])
        self.assertEqual(updated_last_seen, 9)

    def test_bridge_register_persists_helper_session_token_in_workspace(self):
        mod = self._mod()

        async def fake_bridge_post(path, **kwargs):
            return _DummyResponse({"ok": True, "session_token": "tok-register-persist"})

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_once = mod._registered_once
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_bridge_post = mod._bridge_post
        old_ensure_background_tasks = mod._ensure_background_tasks
        try:
            mod._agent_id = None
            mod._session_token = None
            mod._registered_once = False
            mod._registered_role = ""
            mod._registered_capabilities = []
            mod._bridge_post = fake_bridge_post
            mod._ensure_background_tasks = lambda: None
            with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_CLI_WORKSPACE": tmpdir,
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": f"{tmpdir}/AGENTS.md",
                },
                clear=False,
            ):
                asyncio.run(mod.bridge_register("codex", role="Coder", capabilities=["code"]))
                stored = load_bridge_agent_session_token(tmpdir, agent_id="codex")
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_once = old_registered_once
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._bridge_post = old_bridge_post
            mod._ensure_background_tasks = old_ensure_background_tasks

        self.assertEqual(stored, "tok-register-persist")

    def test_auth_headers_recover_persisted_agent_session_token(self):
        mod = self._mod()

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        recovered_session_token = None
        try:
            mod._agent_id = "codex"
            mod._session_token = None
            with tempfile.TemporaryDirectory() as tmpdir:
                session_file = os.path.join(tmpdir, ".bridge", "agent_session.json")
                os.makedirs(os.path.dirname(session_file), exist_ok=True)
                with open(session_file, "w", encoding="utf-8") as fh:
                    json.dump(
                        {
                            "agent_id": "codex",
                            "session_token": "tok-from-disk",
                            "source": "test",
                        },
                        fh,
                    )
                with patch.dict(
                    mod.os.environ,
                    {
                        "BRIDGE_CLI_WORKSPACE": tmpdir,
                    },
                    clear=False,
                ):
                    headers = mod._auth_headers()
                    recovered_session_token = mod._session_token
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token

        self.assertEqual(headers["X-Bridge-Token"], "tok-from-disk")
        self.assertEqual(recovered_session_token, "tok-from-disk")

    def test_auto_reregister_persists_helper_session_token_in_workspace(self):
        mod = self._mod()

        async def fake_bridge_post(path, **kwargs):
            return _DummyResponse({"ok": True, "session_token": "tok-reregister-persist"})

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._session_token = "tok-old"
            mod._registered_role = "Coder"
            mod._registered_capabilities = ["code"]
            mod._bridge_post = fake_bridge_post
            with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_CLI_WORKSPACE": tmpdir,
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                },
                clear=False,
            ):
                ok = asyncio.run(mod._auto_reregister())
                stored = load_bridge_agent_session_token(tmpdir, agent_id="codex")
        finally:
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._bridge_post = old_bridge_post

        self.assertTrue(ok)
        self.assertEqual(stored, "tok-reregister-persist")

    def test_self_reflection_agent_configs_prefers_runtime_cli_env(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        old_registered_role = mod._registered_role
        try:
            mod._agent_id = "codex_a"
            mod._registered_role = "Agent A"
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "BRIDGE_CLI_HOME_DIR": "/tmp/project/.agent_sessions/codex_a",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex_a",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex_a/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "cli_register",
                    "CLAUDE_CONFIG_DIR": "/tmp/config-dir",
                },
                clear=False,
            ):
                payload = mod._self_reflection_agent_configs()
        finally:
            mod._agent_id = old_agent_id
            mod._registered_role = old_registered_role

        self.assertEqual(
            payload,
            {
                "codex_a": {
                    "id": "codex_a",
                    "role": "Agent A",
                    "home_dir": "/tmp/project/.agent_sessions/codex_a",
                    "workspace": "/tmp/project/.agent_sessions/codex_a",
                    "project_root": "/tmp/project",
                    "resume_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "instruction_path": "/tmp/project/.agent_sessions/codex_a/AGENTS.md",
                    "identity_source": "cli_register",
                    "config_dir": "/tmp/config-dir",
                }
            },
        )

    def test_bridge_lesson_add_writes_to_runtime_cli_memory_path(self):
        mod = self._mod()
        from persistence_utils import find_agent_memory_path  # type: ignore

        tmpdir = tempfile.mkdtemp()
        backend_dir = os.path.join(tmpdir, "Backend")
        runtime_home = os.path.join(tmpdir, "project", ".agent_sessions", "codex_a")
        config_dir = os.path.join(tmpdir, ".claude-agent-codex_a")
        legacy_memory = os.path.join(backend_dir, "agents", "codex_a", "MEMORY.md")
        os.makedirs(backend_dir, exist_ok=True)
        os.makedirs(runtime_home, exist_ok=True)
        os.makedirs(os.path.dirname(legacy_memory), exist_ok=True)
        with open(legacy_memory, "w", encoding="utf-8") as fh:
            fh.write("legacy-memory")

        old_agent_id = mod._agent_id
        old_registered_role = mod._registered_role
        old_file = mod.__file__
        try:
            try:
                mod._agent_id = "codex_a"
                mod._registered_role = "Agent A"
                mod.__file__ = os.path.join(backend_dir, "bridge_mcp.py")
                with patch.dict(
                    mod.os.environ,
                    {
                        "BRIDGE_CLI_HOME_DIR": runtime_home,
                        "BRIDGE_CLI_WORKSPACE": runtime_home,
                        "BRIDGE_CLI_PROJECT_ROOT": os.path.join(tmpdir, "project"),
                        "CLAUDE_CONFIG_DIR": config_dir,
                    },
                    clear=False,
                ):
                    raw = asyncio.run(
                        mod.bridge_lesson_add(
                            title="P3_E2E_MARKER_20260311T1727",
                            content="Runtime CLI memory target",
                        )
                    )
            finally:
                mod._agent_id = old_agent_id
                mod._registered_role = old_registered_role
                mod.__file__ = old_file

            data = json.loads(raw)
            canonical_path = find_agent_memory_path("codex_a", runtime_home, config_dir)

            self.assertTrue(data["ok"])
            self.assertTrue(canonical_path)
            self.assertTrue(os.path.isfile(canonical_path))
            with open(canonical_path, encoding="utf-8") as fh:
                self.assertIn("P3_E2E_MARKER_20260311T1727", fh.read())
            with open(legacy_memory, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "legacy-memory")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bridge_reflect_passes_runtime_cli_seed_config(self):
        mod = self._mod()
        import self_reflection  # type: ignore

        tmpdir = tempfile.mkdtemp()
        backend_dir = os.path.join(tmpdir, "Backend")
        os.makedirs(backend_dir, exist_ok=True)
        captured: dict[str, object] = {}

        class RecordingSelfReflection:
            def __init__(self, base_path, agent_configs=None):
                captured["base_path"] = str(base_path)
                captured["agent_configs"] = agent_configs

            def generate_reflection_prompt(self, agent_id, context="", tasks_completed=0):
                return types.SimpleNamespace(
                    agent_id=agent_id,
                    questions=["Q1"],
                    context=context,
                    tasks_completed=tasks_completed,
                )

        old_agent_id = mod._agent_id
        old_registered_role = mod._registered_role
        old_file = mod.__file__
        try:
            try:
                mod._agent_id = "codex_a"
                mod._registered_role = "Agent A"
                mod.__file__ = os.path.join(backend_dir, "bridge_mcp.py")
                with patch.object(self_reflection, "SelfReflection", RecordingSelfReflection):
                    with patch.dict(
                        mod.os.environ,
                        {
                            "BRIDGE_RESUME_ID": "99999999-9999-9999-9999-999999999999",
                            "BRIDGE_CLI_HOME_DIR": "/tmp/project/.agent_sessions/codex_a",
                            "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex_a",
                            "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                            "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex_a/AGENTS.md",
                            "BRIDGE_CLI_IDENTITY_SOURCE": "cli_register",
                            "CLAUDE_CONFIG_DIR": "/tmp/config-dir",
                        },
                        clear=False,
                    ):
                        raw = asyncio.run(
                            mod.bridge_reflect(
                                session_summary="runtime-seeded",
                                tasks_completed=3,
                            )
                        )
            finally:
                mod._agent_id = old_agent_id
                mod._registered_role = old_registered_role
                mod.__file__ = old_file

            data = json.loads(raw)

            self.assertTrue(data["ok"])
            self.assertEqual(captured["base_path"], backend_dir)
            self.assertEqual(
                captured["agent_configs"],
                {
                    "codex_a": {
                        "id": "codex_a",
                        "role": "Agent A",
                        "home_dir": "/tmp/project/.agent_sessions/codex_a",
                        "workspace": "/tmp/project/.agent_sessions/codex_a",
                        "project_root": "/tmp/project",
                        "resume_id": "99999999-9999-9999-9999-999999999999",
                        "instruction_path": "/tmp/project/.agent_sessions/codex_a/AGENTS.md",
                        "identity_source": "cli_register",
                        "config_dir": "/tmp/config-dir",
                    }
                }
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class _RecordingBridgeHandler(BaseHTTPRequestHandler):
    server_version = "BridgeRecording/1.0"

    def log_message(self, format, *args):  # noqa: A003
        del format, args

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        self.server.requests.append({"path": self.path, "json": payload})
        if self.path == "/register":
            agent_id = str(payload.get("agent_id", "")).strip()
            if agent_id:
                self.server.registered_agents.add(agent_id)
            body = {"ok": True, "session_token": f"tok-{len(self.server.requests)}"}
        elif self.path == "/heartbeat":
            agent_id = str(payload.get("agent_id", "")).strip()
            body = {
                "ok": True,
                "registered": agent_id in self.server.registered_agents,
                "timestamp": "2026-03-11T15:00:00Z",
            }
        else:
            body = {"ok": False, "error": f"unexpected path {self.path}"}
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class TestBridgeMcpCliIdentityLiveTransport(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def _start_recording_server(self) -> tuple[ThreadingHTTPServer, str]:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingBridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        httpd.requests = []
        httpd.registered_agents = set()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_live_transport_carries_cli_identity_across_register_heartbeat_and_reregister(self):
        mod = self._mod()
        httpd, base_url = self._start_recording_server()

        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_once = mod._registered_once
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_http = mod.BRIDGE_HTTP
        old_client = mod._http_client
        old_ensure_background_tasks = mod._ensure_background_tasks
        try:
            mod._agent_id = None
            mod._session_token = None
            mod._registered_once = False
            mod._registered_role = ""
            mod._registered_capabilities = []
            mod.BRIDGE_HTTP = base_url
            mod._http_client = None
            mod._ensure_background_tasks = lambda: None
            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "",
                },
                clear=False,
            ):
                register_raw = asyncio.run(mod.bridge_register("codex", role="Coder", capabilities=["code"]))
                httpd.registered_agents.clear()
                heartbeat_raw = asyncio.run(mod.bridge_heartbeat())
        finally:
            if mod._http_client is not None:
                asyncio.run(mod._http_client.aclose())
            mod._http_client = old_client
            mod.BRIDGE_HTTP = old_http
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_once = old_registered_once
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._ensure_background_tasks = old_ensure_background_tasks

        register_data = json.loads(register_raw)
        heartbeat_data = json.loads(heartbeat_raw)
        self.assertTrue(register_data["ok"])
        self.assertTrue(heartbeat_data["auto_reregistered"])
        self.assertEqual([req["path"] for req in httpd.requests], ["/register", "/heartbeat", "/register"])

        first_register = httpd.requests[0]["json"]
        heartbeat_payload = httpd.requests[1]["json"]
        reregister_payload = httpd.requests[2]["json"]

        for payload in (first_register, heartbeat_payload, reregister_payload):
            self.assertEqual(payload["resume_id"], "dddddddd-dddd-dddd-dddd-dddddddddddd")
            self.assertEqual(payload["workspace"], "/tmp/project/.agent_sessions/codex")
            self.assertEqual(payload["project_root"], "/tmp/project")
            self.assertEqual(payload["instruction_path"], "/tmp/project/.agent_sessions/codex/AGENTS.md")
            self.assertEqual(payload["cli_identity_source"], payload["identity_source"])

        self.assertEqual(first_register["identity_source"], "cli_register")
        self.assertEqual(heartbeat_payload["identity_source"], "cli_heartbeat")
        self.assertEqual(reregister_payload["identity_source"], "cli_reregister")


class TestBridgeMcpCliIdentityServerIntegration(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
            import server as srv  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge/server import skipped: {exc}")
        return bridge_mcp, srv

    def _start_bridge_server(self, srv) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _get_json(self, base_url: str, path: str) -> dict[str, object]:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_live_bridge_server_still_normalizes_transport_identity_source_to_cli_register(self):
        mod, srv = self._mod()
        base_url = self._start_bridge_server(srv)

        orig_registered = dict(srv.REGISTERED_AGENTS)
        orig_last_seen = dict(srv.AGENT_LAST_SEEN)
        orig_tokens = dict(srv.AGENT_TOKENS)
        orig_session_tokens = dict(srv.SESSION_TOKENS)
        orig_grace_tokens = dict(srv.GRACE_TOKENS)
        orig_strict_auth = srv.BRIDGE_STRICT_AUTH
        old_agent_id = mod._agent_id
        old_session_token = mod._session_token
        old_registered_once = mod._registered_once
        old_registered_role = mod._registered_role
        old_registered_capabilities = list(mod._registered_capabilities)
        old_http = mod.BRIDGE_HTTP
        old_client = mod._http_client
        old_ensure_background_tasks = mod._ensure_background_tasks
        try:
            srv.BRIDGE_STRICT_AUTH = False
            srv.REGISTERED_AGENTS.clear()
            srv.AGENT_LAST_SEEN.clear()
            srv.AGENT_TOKENS.clear()
            srv.SESSION_TOKENS.clear()
            srv.GRACE_TOKENS.clear()

            mod._agent_id = None
            mod._session_token = None
            mod._registered_once = False
            mod._registered_role = ""
            mod._registered_capabilities = []
            mod.BRIDGE_HTTP = base_url
            mod._http_client = None
            mod._ensure_background_tasks = lambda: None

            with patch.dict(
                mod.os.environ,
                {
                    "BRIDGE_RESUME_ID": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                    "BRIDGE_CLI_WORKSPACE": "/tmp/project/.agent_sessions/codex",
                    "BRIDGE_CLI_PROJECT_ROOT": "/tmp/project",
                    "BRIDGE_CLI_INSTRUCTION_PATH": "/tmp/project/.agent_sessions/codex/AGENTS.md",
                    "BRIDGE_CLI_IDENTITY_SOURCE": "cli_transport_probe",
                },
                clear=False,
            ):
                raw = asyncio.run(mod.bridge_register("codex", role="Coder", capabilities=["code"]))
                detail = self._get_json(base_url, "/agents/codex")
        finally:
            if mod._http_client is not None:
                asyncio.run(mod._http_client.aclose())
            mod._http_client = old_client
            mod.BRIDGE_HTTP = old_http
            mod._agent_id = old_agent_id
            mod._session_token = old_session_token
            mod._registered_once = old_registered_once
            mod._registered_role = old_registered_role
            mod._registered_capabilities = old_registered_capabilities
            mod._ensure_background_tasks = old_ensure_background_tasks

            srv.REGISTERED_AGENTS.clear()
            srv.REGISTERED_AGENTS.update(orig_registered)
            srv.AGENT_LAST_SEEN.clear()
            srv.AGENT_LAST_SEEN.update(orig_last_seen)
            srv.AGENT_TOKENS.clear()
            srv.AGENT_TOKENS.update(orig_tokens)
            srv.SESSION_TOKENS.clear()
            srv.SESSION_TOKENS.update(orig_session_tokens)
            srv.GRACE_TOKENS.clear()
            srv.GRACE_TOKENS.update(orig_grace_tokens)
            srv.BRIDGE_STRICT_AUTH = orig_strict_auth

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(detail["resume_id"], "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
        self.assertEqual(detail["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(detail["project_root"], "/tmp/project")
        self.assertEqual(detail["instruction_path"], "/tmp/project/.agent_sessions/codex/AGENTS.md")
        self.assertEqual(detail["cli_identity_source"], "cli_register")


class TestBridgeMcpTodoistGuards(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_todoist_execute_rejects_foreign_approval_owner(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "other-agent",
                "action": "todoist_delete",
                "payload": {"task_id": "123"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_todoist_execute("req-1"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Approval gehoert zu Agent", data["error"])
        self.assertEqual(data.get("request_id"), "req-1")

    def test_todoist_update_rejects_empty_changes(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        try:
            mod._agent_id = "codex"
            raw = asyncio.run(mod.bridge_todoist_update(task_id="123"))
        finally:
            mod._agent_id = old_agent_id

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Keine Aenderungen angegeben", data["error"])

    def test_todoist_execute_update_rejects_empty_payload_changes(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "codex",
                "action": "todoist_update",
                "payload": {"task_id": "123"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_todoist_execute("req-2"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Keine Aenderungen im Approval-Payload", data["error"])
        self.assertEqual(data.get("request_id"), "req-2")


class TestBridgeMcpApprovalGuards(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_email_execute_rejects_foreign_approval_owner(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "other-agent",
                "payload": {"to": "x@example.com", "subject": "Hi", "body": "Body"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_email_execute("req-email"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Approval gehoert zu Agent", data["error"])
        self.assertEqual(data.get("request_id"), "req-email")

    def test_slack_execute_rejects_foreign_approval_owner(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "other-agent",
                "payload": {"channel": "general", "message": "Hi"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_slack_execute("req-slack"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Approval gehoert zu Agent", data["error"])
        self.assertEqual(data.get("request_id"), "req-slack")

    def test_telegram_execute_rejects_foreign_approval_owner(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "other-agent",
                "payload": {"to": "-100123", "message": "Hi"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_telegram_execute("req-tg"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Approval gehoert zu Agent", data["error"])
        self.assertEqual(data.get("request_id"), "req-tg")

    def test_telegram_send_auto_approved_calls_telegram_api(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(_path, **_kwargs):
            return _DummyResponse({"status": "auto_approved", "standing_approval_id": "sa-tg"})

        async def fake_telegram_call(action, params):
            captured["action"] = action
            captured["params"] = dict(params)
            return {"ok": True, "text": "sent", "chat_id": "-1001234567890"}

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        old_telegram_call = mod._telegram_call
        old_send_whitelist = list(mod._TELEGRAM_SEND_WHITELIST)
        old_approval_whitelist = list(mod._TELEGRAM_APPROVAL_WHITELIST)
        old_contacts = dict(mod._TELEGRAM_CONTACTS)
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            mod._telegram_call = fake_telegram_call
            mod._TELEGRAM_SEND_WHITELIST = ["-1001234567890"]
            mod._TELEGRAM_APPROVAL_WHITELIST = []
            mod._TELEGRAM_CONTACTS = {"team": "-1001234567890"}
            raw = asyncio.run(mod.bridge_telegram_send("team", "Hallo Telegram"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post
            mod._telegram_call = old_telegram_call
            mod._TELEGRAM_SEND_WHITELIST = old_send_whitelist
            mod._TELEGRAM_APPROVAL_WHITELIST = old_approval_whitelist
            mod._TELEGRAM_CONTACTS = old_contacts

        data = json.loads(raw)
        self.assertEqual(data.get("status"), "sent")
        self.assertTrue(data.get("auto_approved"))
        self.assertEqual(data.get("backend"), "telegram")
        self.assertEqual(captured.get("action"), "send_message")
        self.assertEqual(captured["params"]["to"], "-1001234567890")
        self.assertEqual(captured["params"]["message"], "[CODEX] Hallo Telegram")

    def test_whatsapp_execute_rejects_foreign_approval_owner(self):
        mod = self._mod()

        async def fake_bridge_get(_path):
            return _DummyResponse({
                "status": "approved",
                "agent_id": "other-agent",
                "payload": {"to": "+49123", "message": "Hi"},
            })

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_whatsapp_execute("req-wa"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("Approval gehoert zu Agent", data["error"])
        self.assertEqual(data.get("request_id"), "req-wa")

    def test_whatsapp_send_auto_approved_keeps_media_path(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(_path, **_kwargs):
            return _DummyResponse({"status": "auto_approved", "standing_approval_id": "sa-wa"})

        async def fake_whatsapp_call(action, params):
            captured["action"] = action
            captured["params"] = dict(params)
            return {"ok": True, "text": "sent"}

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        old_whatsapp_call = mod._whatsapp_call
        old_send_whitelist = list(mod._WHATSAPP_SEND_WHITELIST)
        old_approval_whitelist = list(mod._WHATSAPP_APPROVAL_WHITELIST)
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            mod._whatsapp_call = fake_whatsapp_call
            mod._WHATSAPP_SEND_WHITELIST = ["120363000000000000@g.us"]
            mod._WHATSAPP_APPROVAL_WHITELIST = []
            with tempfile.NamedTemporaryFile(suffix=".ogg") as media_file:
                raw = asyncio.run(
                    mod.bridge_whatsapp_send(
                        "120363000000000000@g.us",
                        "Hallo Leo",
                        media_path=media_file.name,
                    )
                )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post
            mod._whatsapp_call = old_whatsapp_call
            mod._WHATSAPP_SEND_WHITELIST = old_send_whitelist
            mod._WHATSAPP_APPROVAL_WHITELIST = old_approval_whitelist

        data = json.loads(raw)
        self.assertEqual(data.get("status"), "sent")
        self.assertTrue(data.get("auto_approved"))
        self.assertEqual(captured.get("action"), "send_message")
        self.assertEqual(captured["params"]["to"], "120363000000000000@g.us")
        self.assertIn("media_path", captured["params"])
        self.assertTrue(captured["params"]["message"].startswith("🟦 [CODEX] Hallo Leo"))


class TestBridgeMcpCatalogFallbacks(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_playwright_command_falls_back_to_catalog_pin(self):
        mod = self._mod()
        with patch.object(mod, "PLAYWRIGHT_MCP_COMMAND", ""), patch.object(
            mod.os.path,
            "exists",
            return_value=False,
        ):
            cmd = mod._playwright_command()

        self.assertEqual(cmd, ["npx", "@playwright/mcp@0.0.68"])

    def test_phone_call_returns_request_id_immediately(self):
        mod = self._mod()

        async def fake_bridge_post(_path, **kwargs):
            return _DummyResponse({"status": "pending_approval", "request_id": "req-phone"})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        old_tasks = dict(mod._pending_phone_call_tasks)
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            mod._pending_phone_call_tasks.clear()
            with patch("bridge_mcp.asyncio.create_task") as create_task:
                def fake_create_task(coro):
                    coro.close()
                    return object()

                create_task.side_effect = fake_create_task
                raw = asyncio.run(mod.bridge_phone_call("+49123"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post
            mod._pending_phone_call_tasks.clear()
            mod._pending_phone_call_tasks.update(old_tasks)

        data = json.loads(raw)
        self.assertEqual(data.get("status"), "pending_approval")
        self.assertEqual(data.get("request_id"), "req-phone")
        self.assertIn("bridge_approval_wait", data.get("message", ""))


class TestBridgeMcpCapabilityLibraryTools(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_capability_library_list_forwards_filters_as_query_params(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"entries": [{"id": "official::openai-docs-mcp"}], "count": 1})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(
                mod.bridge_capability_library_list(
                    query="openai docs",
                    cli="codex",
                    official_vendor="true",
                    limit=5,
                    offset=2,
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 1)
        self.assertEqual(captured["path"], "/capability-library")
        self.assertEqual(captured["kwargs"]["params"]["q"], "openai docs")
        self.assertEqual(captured["kwargs"]["params"]["cli"], "codex")
        self.assertEqual(captured["kwargs"]["params"]["official_vendor"], "true")
        self.assertEqual(captured["kwargs"]["params"]["limit"], 5)
        self.assertEqual(captured["kwargs"]["params"]["offset"], 2)

    def test_capability_library_search_and_recommend_forward_payloads(self):
        mod = self._mod()
        captured: list[tuple[str, dict[str, object]]] = []

        async def fake_bridge_post(path, **kwargs):
            captured.append((path, kwargs))
            if path.endswith("/recommend"):
                return _DummyResponse({"matches": [{"id": "official::openai-docs-mcp"}], "count": 1})
            return _DummyResponse({"entries": [{"id": "official::anthropic-claude-code-hooks"}], "count": 1})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            search_raw = asyncio.run(mod.bridge_capability_library_search("claude hooks", cli="claude_code", limit=3))
            recommend_raw = asyncio.run(
                mod.bridge_capability_library_recommend(
                    task="need official docs",
                    engine="codex",
                    top_k=4,
                    official_vendor_only=True,
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        search_data = json.loads(search_raw)
        recommend_data = json.loads(recommend_raw)
        self.assertEqual(search_data["entries"][0]["id"], "official::anthropic-claude-code-hooks")
        self.assertEqual(recommend_data["matches"][0]["id"], "official::openai-docs-mcp")
        self.assertEqual(captured[0][0], "/capability-library/search")
        self.assertEqual(captured[0][1]["json"]["query"], "claude hooks")
        self.assertEqual(captured[0][1]["json"]["cli"], "claude_code")
        self.assertEqual(captured[0][1]["json"]["limit"], 3)
        self.assertEqual(captured[1][0], "/capability-library/recommend")
        self.assertEqual(captured[1][1]["json"]["engine"], "codex")
        self.assertEqual(captured[1][1]["json"]["top_k"], 4)
        self.assertTrue(captured[1][1]["json"]["official_vendor_only"])


class _EmptyMessageError(Exception):
    pass


class _ExplodingHttpClient:
    async def post(self, *_args, **_kwargs):
        raise _EmptyMessageError()


class TestBridgeMcpDiagnostics(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_memory_index_surfaces_exception_class_when_message_is_empty(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        old_get_http = mod._get_http
        try:
            mod._agent_id = "codex"
            mod._get_http = lambda: _ExplodingHttpClient()
            raw = asyncio.run(mod.bridge_memory_index(text="probe", source="test"))
        finally:
            mod._agent_id = old_agent_id
            mod._get_http = old_get_http

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("EmptyMessageError", data["error"])

    def test_cron_create_surfaces_exception_class_when_message_is_empty(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        old_get_http = mod._get_http
        try:
            mod._agent_id = "codex"
            mod._get_http = lambda: _ExplodingHttpClient()
            raw = asyncio.run(
                mod.bridge_cron_create(
                    name="probe",
                    cron_expression="0 9 * * *",
                    action_type="send_message",
                    recipient="user",
                    message="hello",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._get_http = old_get_http

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("EmptyMessageError", data["error"])


class TestBridgeMcpCreatorTools(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="bridge_mcp_creator_")
        self.sample_video = os.path.join(self.tmpdir, "sample.mp4")
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:duration=2",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            self.sample_video,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _start_file_server(self) -> str:
        handler = functools.partial(SimpleHTTPRequestHandler, directory=self.tmpdir)
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_creator_social_presets_tool_lists_expected_entries(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        try:
            mod._agent_id = "codex"
            raw = asyncio.run(mod.bridge_creator_social_presets())
        finally:
            mod._agent_id = old_agent_id

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertIn("youtube_short", data["presets"])
        self.assertEqual(data["presets"]["square_post"]["aspect_ratio"], "1080:1080")

    def test_creator_package_social_tool_writes_manifest_and_assets(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        try:
            mod._agent_id = "codex"
            raw = asyncio.run(
                mod.bridge_creator_package_social(
                    input_path=self.sample_video,
                    output_dir=self.tmpdir,
                    package_name="mcp_package",
                    start_s=0.0,
                    end_s=1.5,
                    preset_names=["youtube_short", "square_post"],
                    segments=[{"start": 0.0, "end": 1.4, "text": "MCP creator subtitle line."}],
                    burn_subtitles=True,
                    write_sidecar_srt=True,
                    default_metadata={"title": "MCP Title", "hashtags": ["mcp", "creator"]},
                    metadata_by_preset={"square_post": {"caption": "Square MCP caption"}},
                )
            )
        finally:
            mod._agent_id = old_agent_id

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertTrue(os.path.isfile(data["result"]["manifest_path"]))
        self.assertTrue(os.path.isfile(data["result"]["sidecar_srt"]["output_path"]))
        self.assertEqual(len(data["result"]["assets"]), 2)
        self.assertEqual(len(data["result"]["metadata_sidecars"]), 2)
        self.assertTrue(os.path.isfile(data["result"]["assets"][0]["output_path"]))
        self.assertTrue(os.path.isfile(data["result"]["assets"][1]["output_path"]))
        self.assertTrue(os.path.isfile(data["result"]["metadata_sidecars"][0]["path"]))

    def test_creator_url_ingest_tool_downloads_local_http_source(self):
        mod = self._mod()
        file_server_url = self._start_file_server()
        workspace_dir = os.path.join(self.tmpdir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        old_agent_id = mod._agent_id
        try:
            mod._agent_id = "codex"
            raw = asyncio.run(
                mod.bridge_creator_url_ingest(
                    source_url=f"{file_server_url}/sample.mp4",
                    workspace_dir=workspace_dir,
                    transcribe=False,
                )
            )
        finally:
            mod._agent_id = old_agent_id

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["source"]["type"], "url")
        self.assertEqual(data["result"]["download"]["method"], "direct")
        self.assertTrue(os.path.isfile(data["result"]["download"]["local_path"]))


class TestBridgeMcpTaskDonePayload(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_bridge_task_done_nests_evidence_object(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"ok": True})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(
                mod.bridge_task_done(
                    task_id="task-123",
                    result_summary="done",
                    result_code="success",
                    evidence_type="test",
                    evidence_ref="pytest -q",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(captured["path"], "/task/task-123/done")


class TestBridgeMcpCreatorJobTools(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_creator_job_submit_routes_local_ingest_to_async_endpoint(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"job_id": "cj_local", "status": "queued"})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(
                mod.bridge_creator_job_submit(
                    job_type="local_ingest",
                    source={"input_path": "/tmp/source.mp4"},
                    workspace_dir="/tmp/ws",
                    config={"language": "en", "transcribe": False},
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertEqual(data["job_id"], "cj_local")
        self.assertEqual(captured["path"], "/creator/jobs/local-ingest")
        self.assertEqual(captured["kwargs"]["json"]["input_path"], "/tmp/source.mp4")
        self.assertEqual(captured["kwargs"]["json"]["workspace_dir"], "/tmp/ws")
        self.assertFalse(captured["kwargs"]["json"]["transcribe"])

    def test_creator_job_list_uses_public_creator_jobs_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"jobs": [], "count": 0})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_creator_job_list("/tmp/ws", status="failed"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 0)
        self.assertEqual(captured["path"], "/creator/jobs")
        self.assertEqual(captured["kwargs"]["params"], {"workspace_dir": "/tmp/ws", "status": "failed"})

    def test_creator_publish_rejects_nonzero_clip_index_without_clip_path(self):
        mod = self._mod()
        old_agent_id = mod._agent_id
        try:
            mod._agent_id = "codex"
            raw = asyncio.run(
                mod.bridge_creator_publish(
                    source_job_id="cj_source",
                    workspace_dir="/tmp/ws",
                    channels=["youtube"],
                    clip_index=1,
                )
            )
        finally:
            mod._agent_id = old_agent_id

        data = json.loads(raw)
        self.assertIn("clip_index selection is not yet supported", data["error"])

    def test_creator_campaign_status_uses_creator_campaign_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"campaign_id": "cc_123", "status": "draft"})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_creator_campaign_status("cc_123", "/tmp/ws"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["campaign_id"], "cc_123")
        self.assertEqual(captured["path"], "/creator/campaigns/cc_123")
        self.assertEqual(captured["kwargs"]["params"], {"workspace_dir": "/tmp/ws"})

    def test_creator_voices_uses_public_creator_voices_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"voices": [], "count": 0})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_creator_voices())
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 0)
        self.assertEqual(captured["path"], "/creator/voices")

    def test_creator_library_uses_public_creator_library_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"videos": [], "count": 0})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_creator_library("custom_collection"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertEqual(data["count"], 0)
        self.assertEqual(captured["path"], "/creator/library")
        self.assertEqual(captured["kwargs"]["params"], {"collection": "custom_collection"})

    def test_creator_voiceover_preserves_public_argument_order(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_submit(job_type, source, workspace_dir, config):
            captured["job_type"] = job_type
            captured["source"] = source
            captured["workspace_dir"] = workspace_dir
            captured["config"] = config
            return json.dumps({"job_id": "cj_voice", "status": "queued"})

        old_agent_id = mod._agent_id
        old_submit = mod.bridge_creator_job_submit
        try:
            mod._agent_id = "codex"
            mod.bridge_creator_job_submit = fake_submit
            raw = asyncio.run(
                mod.bridge_creator_voiceover(
                    "Bridge Text",
                    "voice_demo",
                    "/tmp/sample.mp4",
                    "/tmp/ws",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod.bridge_creator_job_submit = old_submit

        data = json.loads(raw)
        self.assertEqual(data["job_id"], "cj_voice")
        self.assertEqual(captured["job_type"], "voiceover")
        self.assertEqual(captured["source"], {"video_path": "/tmp/sample.mp4"})
        self.assertEqual(captured["workspace_dir"], "/tmp/ws")
        self.assertEqual(captured["config"], {"text": "Bridge Text", "voice_id": "voice_demo"})

    def test_bridge_task_done_rejects_partial_evidence_fields(self):
        mod = self._mod()

        async def fake_bridge_post(path, **kwargs):
            raise AssertionError("bridge_post must not be called for invalid payload")

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(
                mod.bridge_task_done(
                    task_id="task-123",
                    result_summary="done",
                    result_code="success",
                    evidence_type="test",
                    evidence_ref="",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("evidence_type", data["error"])


class TestBridgeMcpDataTools(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_data_source_register_uses_public_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"source_id": "src_1", "status": "created"})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(mod.bridge_data_source_register("sales", "csv", "/tmp/sales.csv"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertEqual(data["source_id"], "src_1")
        self.assertEqual(captured["path"], "/data/sources")
        self.assertEqual(
            captured["kwargs"]["json"],
            {"name": "sales", "kind": "csv", "location": "/tmp/sales.csv"},
        )

    def test_data_source_ingest_uses_ingest_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"dataset_version_id": "dsv_1", "status": "ingested"})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(mod.bridge_data_source_ingest("src_1", "full"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertEqual(data["dataset_version_id"], "dsv_1")
        self.assertEqual(captured["path"], "/data/sources/src_1/ingest")
        self.assertEqual(captured["kwargs"]["json"], {"profile_mode": "full"})

    def test_data_dataset_profile_uses_profile_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_get(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"columns": [], "sample_rows": []})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw = asyncio.run(mod.bridge_data_dataset_profile("ds_sales", "dsv_1"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data = json.loads(raw)
        self.assertIn("columns", data)
        self.assertEqual(captured["path"], "/data/datasets/ds_sales/profile")
        self.assertEqual(captured["kwargs"]["params"], {"version_id": "dsv_1"})

    def test_data_query_dry_run_uses_public_route(self):
        mod = self._mod()
        captured: dict[str, object] = {}

        async def fake_bridge_post(path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return _DummyResponse({"status": "approved"})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "codex"
            mod._bridge_post = fake_bridge_post
            raw = asyncio.run(mod.bridge_data_query_dry_run("SELECT 1", ["ds_sales"]))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        data = json.loads(raw)
        self.assertEqual(data["status"], "approved")
        self.assertEqual(captured["path"], "/data/query/dry-run")
        self.assertEqual(
            captured["kwargs"]["json"],
            {"sql": "SELECT 1", "allowed_tables": ["ds_sales"]},
        )

    def test_data_run_status_and_evidence_use_public_routes(self):
        mod = self._mod()
        captured: list[tuple[str, dict[str, object]]] = []

        async def fake_bridge_get(path, **kwargs):
            captured.append((path, kwargs))
            if path.endswith("/evidence"):
                return _DummyResponse({"status": "pass"})
            return _DummyResponse({"run_id": "run_1", "status": "completed"})

        old_agent_id = mod._agent_id
        old_bridge_get = mod._bridge_get
        try:
            mod._agent_id = "codex"
            mod._bridge_get = fake_bridge_get
            raw_status = asyncio.run(mod.bridge_data_run_status("run_1"))
            raw_evidence = asyncio.run(mod.bridge_data_run_evidence("run_1"))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_get = old_bridge_get

        data_status = json.loads(raw_status)
        data_evidence = json.loads(raw_evidence)
        self.assertEqual(data_status["status"], "completed")
        self.assertEqual(data_evidence["status"], "pass")
        self.assertEqual(captured[0][0], "/data/runs/run_1")
        self.assertEqual(captured[1][0], "/data/runs/run_1/evidence")


if __name__ == "__main__":
    unittest.main(verbosity=2)
