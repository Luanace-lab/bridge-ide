from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.agents as agents_mod  # noqa: E402


class TestAgentWarnMemoryRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.health_map = {
            "codex": {"healthy": False, "warning": "context bridge stale"},
            "buddy": {"healthy": True},
            "ghost": {"error": "agent not found"},
        }
        agents_mod.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            agent_busy=srv.AGENT_BUSY,
            session_tokens=srv.SESSION_TOKENS,
            agent_tokens=srv.AGENT_TOKENS,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            team_config=srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            frontend_dir=srv.FRONTEND_DIR,
            runtime=srv.RUNTIME,
            runtime_lock=srv.RUNTIME_LOCK,
            ws_broadcast_fn=srv.ws_broadcast,
            notify_teamlead_crashed_fn=srv._notify_teamlead_agent_crashed,
            tmux_session_for_fn=srv._tmux_session_for,
            tmux_session_name_exists_fn=srv._tmux_session_name_exists,
            runtime_layout_from_state_fn=srv._runtime_layout_from_state,
            get_agent_home_dir_fn=srv._get_agent_home_dir,
            check_agent_memory_health_fn=self._check_memory_health,
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=srv._atomic_write_team_json,
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        agents_mod.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            agent_busy=srv.AGENT_BUSY,
            session_tokens=srv.SESSION_TOKENS,
            agent_tokens=srv.AGENT_TOKENS,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            team_config=srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            frontend_dir=srv.FRONTEND_DIR,
            runtime=srv.RUNTIME,
            runtime_lock=srv.RUNTIME_LOCK,
            ws_broadcast_fn=srv.ws_broadcast,
            notify_teamlead_crashed_fn=srv._notify_teamlead_agent_crashed,
            tmux_session_for_fn=srv._tmux_session_for,
            tmux_session_name_exists_fn=srv._tmux_session_name_exists,
            runtime_layout_from_state_fn=srv._runtime_layout_from_state,
            get_agent_home_dir_fn=srv._get_agent_home_dir,
            check_agent_memory_health_fn=srv._check_agent_memory_health,
            append_message_fn=srv.append_message,
            atomic_write_team_json_fn=srv._atomic_write_team_json,
        )

    def _check_memory_health(self, agent_id: str) -> dict[str, object]:
        return dict(self.health_map.get(agent_id, {"error": "agent not found"}))

    def _start_server(self) -> str:
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

    def _post(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_warn_memory_route_http(self) -> None:
        base_url = self._start_server()

        warn_status, warn_body = self._post(base_url, "/agents/codex/warn-memory")
        self.assertEqual(warn_status, 200)
        self.assertTrue(warn_body["warned"])

        ok_status, ok_body = self._post(base_url, "/agents/buddy/warn-memory")
        self.assertEqual(ok_status, 200)
        self.assertFalse(ok_body["warned"])

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._post(base_url, "/agents/ghost/warn-memory")
        self.assertEqual(exc_info.exception.code, 404)
        payload = json.loads(exc_info.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "agent not found")


if __name__ == "__main__":
    unittest.main()
