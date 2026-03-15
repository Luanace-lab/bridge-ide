from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.agents as agents_mod  # noqa: E402
import server as srv  # noqa: E402


class TestAgentSetupHomeRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_setup_home_http_")
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_tokens = dict(srv.SESSION_TOKENS)
        self._orig_atomic_write = srv._atomic_write_team_json
        self._orig_sync = srv._sync_agent_persistent_cli_config
        self.team_config = {
            "agents": [
                {
                    "id": "assi",
                    "name": "Assi",
                    "role": "reviewer",
                    "description": "HTTP setup-home test agent",
                    "engine": "claude",
                    "home_dir": os.path.join(self._tmpdir.name, "assi"),
                    "agent_md": "",
                },
                {
                    "id": "buddy",
                    "name": "Buddy",
                    "role": "concierge",
                    "description": "platform operator",
                    "engine": "claude",
                    "home_dir": os.path.join(self._tmpdir.name, "buddy"),
                    "agent_md": "",
                },
            ],
            "subscriptions": [],
        }
        os.makedirs(self.team_config["agents"][0]["home_dir"], exist_ok=True)
        os.makedirs(self.team_config["agents"][1]["home_dir"], exist_ok=True)
        srv.TEAM_CONFIG = self.team_config
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS["buddy-token"] = "buddy"
        self.sync_calls: list[tuple[str, str]] = []
        srv._atomic_write_team_json = lambda: None
        srv._sync_agent_persistent_cli_config = lambda aid, entry: self.sync_calls.append((aid, str(entry["engine"])))
        self._reinit_agents()

    def tearDown(self) -> None:
        srv.TEAM_CONFIG = self._orig_team_config
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_tokens)
        srv._atomic_write_team_json = self._orig_atomic_write
        srv._sync_agent_persistent_cli_config = self._orig_sync
        self._reinit_agents()
        self._tmpdir.cleanup()

    def _reinit_agents(self) -> None:
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
            team_config_getter_fn=lambda: srv.TEAM_CONFIG,
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
            atomic_write_team_json_fn=lambda: srv._atomic_write_team_json(),
            setup_cli_binaries=srv._SETUP_CLI_BINARIES,
            materialize_agent_setup_home_fn=lambda *args, **kwargs: srv._materialize_agent_setup_home(*args, **kwargs),
            sync_agent_persistent_cli_config_fn=lambda aid, entry: srv._sync_agent_persistent_cli_config(aid, entry),
            root_dir=srv.ROOT_DIR,
            bridge_port=srv.PORT,
            create_agent_session_fn=srv.create_agent_session,
            kill_agent_session_fn=srv.kill_agent_session,
            is_session_alive_fn=srv.is_session_alive,
        )

    def _start_server(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_setup_home_route_http(self) -> None:
        base_url = self._start_server()
        req = urllib.request.Request(
            f"{base_url}/agents/assi/setup-home",
            data=json.dumps({"engine": "gemini", "overwrite": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Token": "buddy-token"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["engine"], "gemini")
        self.assertTrue(body["agent_md"].endswith("GEMINI.md"))
        self.assertEqual(self.team_config["agents"][0]["engine"], "gemini")
        self.assertEqual(self.sync_calls, [("assi", "gemini")])


if __name__ == "__main__":
    unittest.main()
