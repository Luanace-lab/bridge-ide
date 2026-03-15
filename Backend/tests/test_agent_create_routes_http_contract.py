from __future__ import annotations

import json
import os
import shutil
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


class TestAgentCreateRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="agent_create_http_")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.team_config = {"agents": [{"id": "buddy"}], "subscriptions": []}
        self._reinit(self.team_config, self._tmpdir)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        self._reinit(srv.TEAM_CONFIG, srv.ROOT_DIR)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _reinit(self, team_config: dict, root_dir: str) -> None:
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
            root_dir=root_dir,
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

    def _post(self, base_url: str, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_agent_create_route_http(self) -> None:
        base_url = self._start_server()
        status, body = self._post(
            base_url,
            "/agents/create",
            {"id": "slice106", "role": "reviewer", "project_path": self._tmpdir},
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["agent"]["id"], "slice106")
        self.assertTrue(os.path.exists(os.path.join(self._tmpdir, ".agent_sessions", "slice106", "SOUL.md")))

        bad_req = urllib.request.Request(
            f"{base_url}/agents/create",
            data=json.dumps({"id": "buddy", "role": "reviewer"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        self.assertEqual(exc_info.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
