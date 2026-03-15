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

import handlers.agents as agents_mod  # noqa: E402
import server as srv  # noqa: E402


class TestAgentSubscriptionRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.persist_calls = 0
        self.team_config = {
            "agents": [
                {"id": "buddy", "config_dir": "/profiles/sub1", "subscription_id": "sub1"},
                {"id": "assi", "config_dir": "/profiles/sub2"},
            ],
            "subscriptions": [
                {"id": "sub1", "path": "/profiles/sub1"},
                {"id": "sub2", "path": "/profiles/sub2"},
            ],
        }
        self._reinit(self.team_config, self._persist)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        self._reinit(srv.TEAM_CONFIG, srv._atomic_write_team_json)

    def _persist(self) -> None:
        self.persist_calls += 1

    def _reinit(self, team_config: dict, persist_fn) -> None:
        agents_mod.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            agent_busy=srv.AGENT_BUSY,
            session_tokens=srv.SESSION_TOKENS,
            agent_tokens=srv.AGENT_TOKENS,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            team_config=team_config,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
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
            atomic_write_team_json_fn=persist_fn,
        )

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

    def _put(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_agent_subscription_route_http(self) -> None:
        base_url = self._start_server()

        assign_status, assign_body = self._put(base_url, "/agents/assi/subscription", {"subscription_id": "sub2"})
        self.assertEqual(assign_status, 200)
        self.assertEqual(assign_body["subscription_id"], "sub2")

        clear_status, clear_body = self._put(base_url, "/agents/buddy/subscription", {"subscription_id": ""})
        self.assertEqual(clear_status, 200)
        self.assertIsNone(clear_body["subscription_id"])

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._put(base_url, "/agents/ghost/subscription", {"subscription_id": "sub1"})
        self.assertEqual(exc_info.exception.code, 404)
        payload = json.loads(exc_info.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "agent 'ghost' not found in team.json")


if __name__ == "__main__":
    unittest.main()
