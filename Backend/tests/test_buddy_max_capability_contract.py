from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DummyAuthHandler:
    def __init__(self, token: str):
        self.headers = {"X-Bridge-Token": token}
        self.response_code = None
        self.response_payload = None

    _extract_auth_token = srv.BridgeHandler._extract_auth_token
    _resolve_auth_identity = srv.BridgeHandler._resolve_auth_identity
    _require_authenticated = srv.BridgeHandler._require_authenticated

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload


class TestBuddyPlatformOperatorAuth(unittest.TestCase):
    def setUp(self):
        self._orig_tokens = dict(srv.SESSION_TOKENS)

    def tearDown(self):
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_tokens)

    def test_platform_operator_helper_accepts_buddy_agent_token(self):
        handler = _DummyAuthHandler("buddy-token")
        srv.SESSION_TOKENS["buddy-token"] = "buddy"

        ok, role, identity = srv.BridgeHandler._require_platform_operator(handler)

        self.assertTrue(ok)
        self.assertEqual(role, "agent")
        self.assertEqual(identity, "buddy")
        self.assertIsNone(handler.response_code)

    def test_platform_operator_helper_rejects_non_operator_agent_token(self):
        handler = _DummyAuthHandler("codex-token")
        srv.SESSION_TOKENS["codex-token"] = "codex"

        ok, role, identity = srv.BridgeHandler._require_platform_operator(handler)

        self.assertFalse(ok)
        self.assertEqual(role, "agent")
        self.assertEqual(identity, "codex")
        self.assertEqual(handler.response_code, 403)
        self.assertIn("platform operator", handler.response_payload["error"])


class TestBuddyMaxCapabilityMcpTools(unittest.TestCase):
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            self.skipTest(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_buddy_orchestration_tools_post_to_platform_contracts(self):
        mod = self._mod()
        calls: list[tuple[str, dict]] = []

        async def fake_bridge_post(path, **kwargs):
            calls.append((path, kwargs))
            return _DummyResponse({"ok": True, "path": path})

        old_agent_id = mod._agent_id
        old_bridge_post = mod._bridge_post
        try:
            mod._agent_id = "buddy"
            mod._bridge_post = fake_bridge_post

            raw_project = asyncio.run(mod.bridge_project_create({"project_name": "Demo"}))
            raw_runtime = asyncio.run(mod.bridge_runtime_configure({"project_path": "/tmp/demo"}))
            raw_stop = asyncio.run(mod.bridge_runtime_stop())
            raw_agent = asyncio.run(mod.bridge_agent_start("kai"))
            raw_compile = asyncio.run(mod.bridge_workflow_compile({"name": "Compile Probe"}))
            raw_deploy = asyncio.run(mod.bridge_workflow_deploy({"name": "Deploy Probe"}, activate=False))
            raw_template = asyncio.run(mod.bridge_workflow_deploy_template("daily-report", {"channel": "ops"}))
        finally:
            mod._agent_id = old_agent_id
            mod._bridge_post = old_bridge_post

        self.assertEqual(json.loads(raw_project)["path"], "/projects/create")
        self.assertEqual(json.loads(raw_runtime)["path"], "/runtime/configure")
        self.assertEqual(json.loads(raw_stop)["path"], "/runtime/stop")
        self.assertEqual(json.loads(raw_agent)["path"], "/agents/kai/start")
        self.assertEqual(json.loads(raw_compile)["path"], "/workflows/compile")
        self.assertEqual(json.loads(raw_deploy)["path"], "/workflows/deploy")
        self.assertEqual(json.loads(raw_template)["path"], "/workflows/deploy-template")

        self.assertEqual(calls[0], ("/projects/create", {"json": {"project_name": "Demo"}}))
        self.assertEqual(calls[1], ("/runtime/configure", {"json": {"project_path": "/tmp/demo"}}))
        self.assertEqual(calls[2], ("/runtime/stop", {"json": {}}))
        self.assertEqual(calls[3], ("/agents/kai/start", {"json": {"from": "buddy"}}))
        self.assertEqual(calls[4], ("/workflows/compile", {"json": {"definition": {"name": "Compile Probe"}}}))
        self.assertEqual(
            calls[5],
            ("/workflows/deploy", {"json": {"definition": {"name": "Deploy Probe"}, "activate": False}}),
        )
        self.assertEqual(
            calls[6],
            ("/workflows/deploy-template", {"json": {"template_id": "daily-report", "variables": {"channel": "ops"}}}),
        )


class TestBuddyCapabilityBreadth(unittest.TestCase):
    def test_buddy_team_config_requests_all_mcps(self):
        buddy_conf = next(
            (agent for agent in srv.TEAM_CONFIG.get("agents", []) if agent.get("id") == "buddy"),
            None,
        )
        self.assertIsNotNone(buddy_conf)
        self.assertEqual(str(buddy_conf.get("mcp_servers", "")).strip(), "all")

    def test_auto_start_buddy_passes_all_mcps_to_session_creation(self):
        calls: list[dict] = []
        old_create_agent_session = srv.create_agent_session
        old_is_session_alive = srv.is_session_alive
        old_team_config = srv.TEAM_CONFIG
        try:
            patched_team = json.loads(json.dumps(srv.TEAM_CONFIG))
            for agent in patched_team.get("agents", []):
                if agent.get("id") == "buddy":
                    agent["active"] = True
                    break
            srv.TEAM_CONFIG = patched_team

            def fake_create_agent_session(**kwargs):
                calls.append(kwargs)

            def fake_is_session_alive(agent_id: str):
                if agent_id == "buddy":
                    return bool(calls)
                return False

            srv.create_agent_session = fake_create_agent_session
            srv.is_session_alive = fake_is_session_alive

            ok = srv._auto_start_buddy_agent()
        finally:
            srv.create_agent_session = old_create_agent_session
            srv.is_session_alive = old_is_session_alive
            srv.TEAM_CONFIG = old_team_config

        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["agent_id"], "buddy")
        self.assertEqual(calls[0]["mcp_servers"], "all")


class TestBuddyRuntimeEndpoints(unittest.TestCase):
    def setUp(self):
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_tokens = dict(srv.SESSION_TOKENS)
        self._orig_runtime = dict(srv.RUNTIME)
        self._orig_stop_known_agents = srv.stop_known_agents
        self._orig_persist_runtime_overlay = srv._persist_runtime_overlay
        self._orig_reset_team_lead_state = srv.reset_team_lead_state
        self._orig_ws_broadcast = srv.ws_broadcast
        self._orig_runtime_snapshot = srv.runtime_snapshot
        self._orig_is_session_alive = srv.is_session_alive
        self._orig_current_runtime_agent_ids = srv.current_runtime_agent_ids
        self._orig_start_agent_from_conf = srv._start_agent_from_conf
        self._orig_auto_restart_agent = srv._auto_restart_agent
        self._orig_is_agent_at_oauth_prompt = srv._is_agent_at_oauth_prompt
        self._orig_is_agent_at_prompt_inline = srv._is_agent_at_prompt_inline
        self._orig_nudge_idle_agent = srv._nudge_idle_agent
        self._orig_update_agent_status = srv.update_agent_status
        self._orig_detect_available_engines = srv._detect_available_engines
        self._orig_validate_project_path = srv.validate_project_path
        self._orig_resolve_team_lead_scope_file = srv.resolve_team_lead_scope_file
        self._orig_pair_mode_of = srv.pair_mode_of
        self._orig_resolve_runtime_specs = srv.resolve_runtime_specs
        self._orig_build_runtime_agent_profiles = srv._build_runtime_agent_profiles
        self._orig_build_runtime_overlay = srv._build_runtime_overlay
        self._orig_kill_agent_session = srv.kill_agent_session
        self._orig_open_agent_sessions = srv.open_agent_sessions
        self._orig_wait_for_agent_registration = srv._wait_for_agent_registration
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def tearDown(self):
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_tokens)
        srv.RUNTIME.clear()
        srv.RUNTIME.update(self._orig_runtime)
        srv.stop_known_agents = self._orig_stop_known_agents
        srv._persist_runtime_overlay = self._orig_persist_runtime_overlay
        srv.reset_team_lead_state = self._orig_reset_team_lead_state
        srv.ws_broadcast = self._orig_ws_broadcast
        srv.runtime_snapshot = self._orig_runtime_snapshot
        srv.is_session_alive = self._orig_is_session_alive
        srv.current_runtime_agent_ids = self._orig_current_runtime_agent_ids
        srv._start_agent_from_conf = self._orig_start_agent_from_conf
        srv._auto_restart_agent = self._orig_auto_restart_agent
        srv._is_agent_at_oauth_prompt = self._orig_is_agent_at_oauth_prompt
        srv._is_agent_at_prompt_inline = self._orig_is_agent_at_prompt_inline
        srv._nudge_idle_agent = self._orig_nudge_idle_agent
        srv.update_agent_status = self._orig_update_agent_status
        srv._detect_available_engines = self._orig_detect_available_engines
        srv.validate_project_path = self._orig_validate_project_path
        srv.resolve_team_lead_scope_file = self._orig_resolve_team_lead_scope_file
        srv.pair_mode_of = self._orig_pair_mode_of
        srv.resolve_runtime_specs = self._orig_resolve_runtime_specs
        srv._build_runtime_agent_profiles = self._orig_build_runtime_agent_profiles
        srv._build_runtime_overlay = self._orig_build_runtime_overlay
        srv.kill_agent_session = self._orig_kill_agent_session
        srv.open_agent_sessions = self._orig_open_agent_sessions
        srv._wait_for_agent_registration = self._orig_wait_for_agent_registration

    def _start_server(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict, token: str):
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Token": token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_runtime_stop_accepts_buddy_and_rejects_non_operator_agent(self):
        srv.BRIDGE_STRICT_AUTH = True
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS["buddy-token"] = "buddy"
        srv.SESSION_TOKENS["codex-token"] = "codex"
        srv.stop_known_agents = lambda: []
        srv._persist_runtime_overlay = lambda _overlay: None
        srv.reset_team_lead_state = lambda _reason: None
        srv.ws_broadcast = lambda *_args, **_kwargs: None
        srv.runtime_snapshot = lambda: {"project_name": "", "agent_profiles": []}

        base_url = self._start_server()

        status_ok, payload_ok = self._post(base_url, "/runtime/stop", {}, "buddy-token")
        self.assertEqual(status_ok, 200)
        self.assertTrue(payload_ok["ok"])

        with self.assertRaises(urllib.error.HTTPError) as denied:
            self._post(base_url, "/runtime/stop", {}, "codex-token")
        self.assertEqual(denied.exception.code, 403)

    def test_runtime_configure_accepts_buddy_and_rejects_non_operator_agent(self):
        srv.BRIDGE_STRICT_AUTH = True
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS["buddy-token"] = "buddy"
        srv.SESSION_TOKENS["codex-token"] = "codex"
        project_dir = self._tmpdir.name

        srv._detect_available_engines = lambda: {"codex", "claude"}
        srv.validate_project_path = lambda raw, _base: str(raw or project_dir)
        srv.resolve_team_lead_scope_file = lambda project_path, _scope: os.path.join(project_path, "TEAMLEAD_SCOPE.md")
        srv.pair_mode_of = lambda _a, _b: "codex_claude"
        srv.resolve_runtime_specs = lambda *_args, **_kwargs: [{"id": "agent_alpha"}]
        srv._build_runtime_agent_profiles = (
            lambda _data, _layout, project_name, project_path: [{"id": "agent_alpha", "project_name": project_name, "project_path": project_path}]
        )
        srv._build_runtime_overlay = (
            lambda project_name, project_path, agent_profiles: {
                "project_name": project_name,
                "project_path": project_path,
                "agent_profiles": agent_profiles,
            }
        )
        srv.stop_known_agents = lambda: []
        srv.kill_agent_session = lambda _agent_id: None
        srv.open_agent_sessions = lambda _config: [{"id": "agent_alpha", "alive": True}]
        def fake_wait_for_agent_registration(agent_ids, _timeout):
            for agent_id in agent_ids:
                srv.REGISTERED_AGENTS[agent_id] = {"role": "runtime-agent"}
            return True
        srv._wait_for_agent_registration = fake_wait_for_agent_registration
        srv._persist_runtime_overlay = lambda _overlay: None
        srv.reset_team_lead_state = lambda _reason: None
        srv.ws_broadcast = lambda *_args, **_kwargs: None
        srv.runtime_snapshot = lambda: {"project_name": "Demo", "agent_profiles": [{"id": "agent_alpha"}]}
        srv.is_session_alive = lambda _agent_id: True

        base_url = self._start_server()
        payload = {
            "project_name": "Demo",
            "project_path": project_dir,
            "agent_a_engine": "codex",
            "agent_b_engine": "claude",
            "team_lead_engine": "codex",
            "team_lead_enabled": False,
            "team_lead_cli_enabled": False,
        }

        status_ok, body_ok = self._post(base_url, "/runtime/configure", payload, "buddy-token")
        self.assertEqual(status_ok, 200)
        self.assertTrue(body_ok["ok"])
        self.assertEqual(body_ok["runtime"]["project_name"], "Demo")

        with self.assertRaises(urllib.error.HTTPError) as denied:
            self._post(base_url, "/runtime/configure", payload, "codex-token")
        self.assertEqual(denied.exception.code, 403)

    def test_runtime_configure_returns_500_when_runtime_reset_raises(self):
        srv.BRIDGE_STRICT_AUTH = False
        project_dir = self._tmpdir.name

        srv._detect_available_engines = lambda: {"codex", "claude"}
        srv.validate_project_path = lambda raw, _base: str(raw or project_dir)
        srv.resolve_team_lead_scope_file = lambda project_path, _scope: os.path.join(project_path, "TEAMLEAD_SCOPE.md")
        srv.pair_mode_of = lambda _a, _b: "codex_claude"
        srv.resolve_runtime_specs = lambda *_args, **_kwargs: [{"id": "agent_alpha"}]
        srv._build_runtime_agent_profiles = (
            lambda _data, _layout, project_name, project_path: [{"id": "agent_alpha", "project_name": project_name, "project_path": project_path}]
        )
        srv._build_runtime_overlay = (
            lambda project_name, project_path, agent_profiles: {
                "project_name": project_name,
                "project_path": project_path,
                "agent_profiles": agent_profiles,
            }
        )
        srv.stop_known_agents = lambda: []

        def boom(_agent_id):
            raise RuntimeError("tmux reset failed")

        srv.kill_agent_session = boom
        srv.open_agent_sessions = lambda _config: [{"id": "agent_alpha"}]
        srv._wait_for_agent_registration = lambda _agent_ids, _timeout: None
        srv._persist_runtime_overlay = lambda _overlay: None
        srv.reset_team_lead_state = lambda _reason: None
        srv.ws_broadcast = lambda *_args, **_kwargs: None
        srv.runtime_snapshot = lambda: {"project_name": "Demo", "agent_profiles": [{"id": "agent_alpha"}]}

        base_url = self._start_server()
        payload = {
            "project_name": "Demo",
            "project_path": project_dir,
            "agent_a_engine": "codex",
            "agent_b_engine": "claude",
            "team_lead_engine": "codex",
            "team_lead_enabled": False,
            "team_lead_cli_enabled": False,
        }

        with self.assertRaises(urllib.error.HTTPError) as failed:
            self._post(base_url, "/runtime/configure", payload, "")
        self.assertEqual(failed.exception.code, 500)
        body = json.loads(failed.exception.read().decode("utf-8"))
        self.assertIn("failed to reset runtime", body["error"])

    def test_runtime_configure_returns_500_when_runtime_profile_build_raises(self):
        srv.BRIDGE_STRICT_AUTH = False
        project_dir = self._tmpdir.name

        srv._detect_available_engines = lambda: {"codex", "claude"}
        srv.validate_project_path = lambda raw, _base: str(raw or project_dir)
        srv.resolve_team_lead_scope_file = lambda project_path, _scope: os.path.join(project_path, "TEAMLEAD_SCOPE.md")
        srv.pair_mode_of = lambda _a, _b: "codex_claude"
        srv.resolve_runtime_specs = lambda *_args, **_kwargs: [{"id": "agent_alpha"}]

        def boom_profiles(*_args, **_kwargs):
            raise RuntimeError("runtime profile build failed")

        srv._build_runtime_agent_profiles = boom_profiles

        base_url = self._start_server()
        payload = {
            "project_name": "Demo",
            "project_path": project_dir,
            "agent_a_engine": "codex",
            "agent_b_engine": "claude",
            "team_lead_engine": "codex",
            "team_lead_enabled": False,
            "team_lead_cli_enabled": False,
        }

        with self.assertRaises(urllib.error.HTTPError) as failed:
            self._post(base_url, "/runtime/configure", payload, "")
        self.assertEqual(failed.exception.code, 500)
        body = json.loads(failed.exception.read().decode("utf-8"))
        self.assertIn("failed to build runtime config", body["error"])

    def test_runtime_configure_catches_unexpected_prepare_error(self):
        srv.BRIDGE_STRICT_AUTH = False
        project_dir = self._tmpdir.name

        def boom_engines():
            raise RuntimeError("engine probe failed")

        srv._detect_available_engines = boom_engines
        srv.validate_project_path = lambda raw, _base: str(raw or project_dir)

        base_url = self._start_server()
        payload = {
            "project_name": "Demo",
            "project_path": project_dir,
            "agent_a_engine": "codex",
            "agent_b_engine": "claude",
            "team_lead_engine": "codex",
            "team_lead_enabled": False,
            "team_lead_cli_enabled": False,
        }

        with self.assertRaises(urllib.error.HTTPError) as failed:
            self._post(base_url, "/runtime/configure", payload, "")
        self.assertEqual(failed.exception.code, 500)
        body = json.loads(failed.exception.read().decode("utf-8"))
        self.assertIn("runtime configure unexpected failure", body["error"])

    def test_agent_start_accepts_buddy_and_rejects_non_operator_agent(self):
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS["buddy-token"] = "buddy"
        srv.SESSION_TOKENS["codex-token"] = "codex"
        srv.is_session_alive = lambda _agent_id: False
        srv.current_runtime_agent_ids = lambda: set()
        srv._start_agent_from_conf = lambda _agent_id: True
        srv._auto_restart_agent = lambda _agent_id: True
        srv._is_agent_at_oauth_prompt = lambda _agent_id: False
        srv._is_agent_at_prompt_inline = lambda _agent_id: False
        srv._nudge_idle_agent = lambda *_args, **_kwargs: None
        srv.update_agent_status = lambda _agent_id: None

        base_url = self._start_server()

        status_ok, payload_ok = self._post(base_url, "/agents/kai/start", {"from": "buddy"}, "buddy-token")
        self.assertEqual(status_ok, 200)
        self.assertTrue(payload_ok["ok"])
        self.assertEqual(payload_ok["status"], "starting")

        with self.assertRaises(urllib.error.HTTPError) as denied:
            self._post(base_url, "/agents/kai/start", {"from": "codex"}, "codex-token")
        self.assertEqual(denied.exception.code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
