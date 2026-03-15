from __future__ import annotations

import json
import os
import sys
import tempfile
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


class TestAgentRestartRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_restart_http_")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.home_dir = os.path.join(self._tmpdir.name, "assi")
        os.makedirs(self.home_dir, exist_ok=True)
        self.prompt_file = os.path.join(self._tmpdir.name, "assi_prompt.txt")
        with open(self.prompt_file, "w", encoding="utf-8") as handle:
            handle.write("http restart prompt")
        self.team_config = {
            "agents": [
                {
                    "id": "assi",
                    "active": True,
                    "home_dir": self.home_dir,
                    "prompt_file": self.prompt_file,
                    "engine": "claude",
                    "description": "HTTP Assi",
                    "reports_to": "user",
                },
                {
                    "id": "buddy",
                    "active": False,
                    "home_dir": self.home_dir,
                },
            ],
            "subscriptions": [],
        }
        self.created: list[dict] = []
        self.alive_ids: set[str] = set()
        self.cleared: list[str] = []
        self.original_clear = agents_mod._clear_agent_runtime_presence
        agents_mod._clear_agent_runtime_presence = self._clear_runtime_presence
        self._reinit(self.team_config)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        agents_mod._clear_agent_runtime_presence = self.original_clear
        self._reinit(srv.TEAM_CONFIG)
        self._tmpdir.cleanup()

    def _create_agent_session(self, **kwargs) -> bool:
        self.created.append(dict(kwargs))
        self.alive_ids.add(kwargs["agent_id"])
        return True

    def _kill_agent_session(self, agent_id: str) -> bool:
        self.alive_ids.discard(agent_id)
        return True

    def _is_session_alive(self, agent_id: str) -> bool:
        return agent_id in self.alive_ids

    def _clear_runtime_presence(self, agent_id: str) -> None:
        self.cleared.append(agent_id)

    def _reinit(self, team_config: dict) -> None:
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
            team_config_getter_fn=lambda: team_config,
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
            atomic_write_team_json_fn=lambda: None,
            bridge_port=9111,
            create_agent_session_fn=self._create_agent_session,
            kill_agent_session_fn=self._kill_agent_session,
            is_session_alive_fn=self._is_session_alive,
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

    def test_restart_route_http(self) -> None:
        base_url = self._start_server()

        req = urllib.request.Request(f"{base_url}/agents/assi/restart", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["action"], "started")
        self.assertTrue(body["session_alive"])
        self.assertEqual(self.created[0]["initial_prompt"], "http restart prompt")

        inactive_req = urllib.request.Request(f"{base_url}/agents/buddy/restart", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(inactive_req, timeout=5)
        self.assertEqual(exc_info.exception.code, 400)
        err = json.loads(exc_info.exception.read().decode("utf-8"))
        self.assertEqual(err["error"], "agent 'buddy' is not active")


if __name__ == "__main__":
    unittest.main()
