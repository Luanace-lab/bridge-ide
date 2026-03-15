from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestAgentStartContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_strict_auth = srv.BRIDGE_STRICT_AUTH
        self._orig_is_session_alive = srv.is_session_alive
        self._orig_current_runtime_agent_ids = srv.current_runtime_agent_ids
        self._orig_start_agent_from_conf = srv._start_agent_from_conf
        self._orig_load_agents_conf = srv._load_agents_conf
        self._orig_auto_restart_agent = srv._auto_restart_agent
        self._orig_check_tmux_session = srv._check_tmux_session
        self._orig_agent_runtime_blocker = srv._agent_runtime_blocker

        srv.BRIDGE_STRICT_AUTH = False
        srv.is_session_alive = lambda _agent_id: False
        srv.current_runtime_agent_ids = lambda: []
        srv._auto_restart_agent = lambda _agent_id: False
        srv._check_tmux_session = lambda _agent_id: False
        srv._agent_runtime_blocker = lambda _agent_id: {}

    def tearDown(self) -> None:
        srv.TEAM_CONFIG = self._orig_team_config
        srv.BRIDGE_STRICT_AUTH = self._orig_strict_auth
        srv.is_session_alive = self._orig_is_session_alive
        srv.current_runtime_agent_ids = self._orig_current_runtime_agent_ids
        srv._start_agent_from_conf = self._orig_start_agent_from_conf
        srv._load_agents_conf = self._orig_load_agents_conf
        srv._auto_restart_agent = self._orig_auto_restart_agent
        srv._check_tmux_session = self._orig_check_tmux_session
        srv._agent_runtime_blocker = self._orig_agent_runtime_blocker

    def _start_server(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_start_endpoint_returns_500_for_configured_agent_start_failure(self) -> None:
        srv.TEAM_CONFIG = {"agents": [{"id": "codex", "home_dir": "/tmp/codex"}]}
        srv._load_agents_conf = lambda: {}
        srv._start_agent_from_conf = lambda _agent_id: False

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/agents/codex/start", {"from": "system"})

        self.assertEqual(raised.exception.code, 500)
        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(body["error"], "failed to start configured agent: codex")

    def test_start_endpoint_returns_404_only_for_unknown_agent(self) -> None:
        srv.TEAM_CONFIG = {"agents": []}
        srv._load_agents_conf = lambda: {}
        srv._start_agent_from_conf = lambda _agent_id: False

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/agents/missing/start", {"from": "system"})

        self.assertEqual(raised.exception.code, 404)
        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(body["error"], "agent missing not found in team.json or agents.conf")

    def test_start_endpoint_treats_concurrent_tmux_race_as_already_running(self) -> None:
        srv.TEAM_CONFIG = {
            "agents": [{"id": "buddy", "home_dir": "/tmp/buddy", "description": "Buddy concierge"}]
        }
        srv._load_agents_conf = lambda: {}
        srv._start_agent_from_conf = lambda _agent_id: False
        srv._check_tmux_session = lambda _agent_id: _agent_id == "buddy"

        base_url = self._start_server()
        status, body = self._post(base_url, "/agents/buddy/start", {"from": "system"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "already_running")
        self.assertIn("concurrent start", body["message"])

    def test_start_endpoint_surfaces_manual_setup_required_for_running_agent(self) -> None:
        srv.TEAM_CONFIG = {"agents": [{"id": "claude", "home_dir": "/tmp/claude"}]}
        srv.is_session_alive = lambda agent_id: agent_id == "claude"
        srv._agent_runtime_blocker = lambda agent_id: (
            {
                "reason": "manual_setup_required",
                "detail": "Claude Code first-run setup requires a manual theme selection in the session.",
            }
            if agent_id == "claude"
            else {}
        )

        base_url = self._start_server()
        status, body = self._post(base_url, "/agents/claude/start", {"from": "system"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "manual_setup_required")
        self.assertIn("theme selection", body["message"])

    def test_start_endpoint_surfaces_auth_blocked_without_force_restart(self) -> None:
        srv.TEAM_CONFIG = {"agents": [{"id": "claude", "home_dir": "/tmp/claude"}]}
        srv.is_session_alive = lambda agent_id: agent_id == "claude"
        srv._agent_runtime_blocker = lambda agent_id: (
            {
                "reason": "login_required",
                "detail": "Claude Code is waiting for official login confirmation in the session.",
            }
            if agent_id == "claude"
            else {}
        )
        srv._auto_restart_agent = lambda _agent_id: self.fail("oauth prompt must not trigger auto-restart")

        base_url = self._start_server()
        status, body = self._post(base_url, "/agents/claude/start", {"from": "system"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "auth_blocked")
        self.assertIn("login confirmation", body["message"])

    def test_start_endpoint_surfaces_usage_limit_reached_without_force_restart(self) -> None:
        srv.TEAM_CONFIG = {"agents": [{"id": "claude", "home_dir": "/tmp/claude"}]}
        srv.is_session_alive = lambda agent_id: agent_id == "claude"
        srv._agent_runtime_blocker = lambda agent_id: (
            {
                "reason": "usage_limit_reached",
                "detail": "You've hit your limit · resets Mar 16, 2am (Europe/Berlin)",
            }
            if agent_id == "claude"
            else {}
        )
        srv._auto_restart_agent = lambda _agent_id: self.fail("usage limit must not trigger auto-restart")

        base_url = self._start_server()
        status, body = self._post(base_url, "/agents/claude/start", {"from": "system"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "usage_limit_reached")
        self.assertIn("You've hit your limit", body["message"])

    def test_start_endpoint_force_restarts_stale_running_session(self) -> None:
        now_ts = 2_000.0
        srv.TEAM_CONFIG = {"agents": [{"id": "codex", "home_dir": "/tmp/codex"}]}
        srv.is_session_alive = lambda agent_id: agent_id == "codex"
        srv.REGISTERED_AGENTS["codex"] = {
            "role": "Agent A",
            "engine": "codex",
            "registered_at": "2026-03-14T00:00:00+00:00",
            "last_heartbeat": now_ts - 120.0,
            "last_heartbeat_iso": "2026-03-14T00:00:00+00:00",
        }
        srv.AGENT_LAST_SEEN["codex"] = now_ts - 120.0
        restart_calls: list[str] = []
        srv._auto_restart_agent = lambda agent_id: restart_calls.append(agent_id) or True

        base_url = self._start_server()
        with mock.patch("server.time.time", return_value=now_ts):
            status, body = self._post(base_url, "/agents/codex/start", {"from": "system"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "force_restarted")
        self.assertEqual(restart_calls, ["codex"])


if __name__ == "__main__":
    unittest.main()
