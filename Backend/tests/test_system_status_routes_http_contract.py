from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.system_status_routes as routes_mod  # noqa: E402


class TestSystemStatusRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="system_status_routes_http_contract_")
        pids_dir = os.path.join(self._tmpdir, "Backend", "pids")
        os.makedirs(pids_dir, exist_ok=True)
        pid = os.getpid()
        for name in ("restart_wrapper.pid", "watcher.pid", "output_forwarder.pid"):
            with open(os.path.join(pids_dir, name), "w", encoding="utf-8") as handle:
                handle.write(str(pid))
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.init(
            restart_state_getter=lambda: {
                "phase": "warn",
                "started_at": "2099-01-01T00:00:00+00:00",
                "reason": "http-contract",
                "checkpoints": {"codex": {"status": "warned"}},
                "warn_seconds": 60,
                "stop_seconds": 30,
                "agents_mode": "restart",
            },
            restart_lock=threading.RLock(),
            graceful_shutdown_getter=lambda: {
                "acked_agents": {"codex"},
                "expected_agents": {"codex", "buddy"},
            },
            graceful_shutdown_lock=threading.RLock(),
            system_status_getter=lambda: {"mode": "normal"},
            start_ts_getter=lambda: 0.0,
            team_config_getter=lambda: {"agents": [{"id": "codex", "active": True, "engine": "codex"}]},
            registered_agents_getter=lambda: {"codex": {"ok": True}},
            agent_is_live_fn=lambda agent_id: agent_id == "codex",
            root_dir_fn=lambda: self._tmpdir,
            active_agent_ids_getter=lambda: {"codex", "buddy"},
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            restart_state_getter=lambda: srv.RESTART_STATE,
            restart_lock=srv.RESTART_LOCK,
            graceful_shutdown_getter=lambda: srv._GRACEFUL_SHUTDOWN,
            graceful_shutdown_lock=srv._GRACEFUL_SHUTDOWN_LOCK,
            system_status_getter=lambda: srv._SYSTEM_STATUS,
            start_ts_getter=lambda: srv.START_TS,
            team_config_getter=lambda: srv.TEAM_CONFIG,
            registered_agents_getter=lambda: srv.REGISTERED_AGENTS,
            agent_is_live_fn=lambda agent_id: srv._agent_is_live(agent_id, stale_seconds=120.0),
            root_dir_fn=lambda: srv.ROOT_DIR,
            active_agent_ids_getter=lambda: srv._get_active_agent_ids(),
        )
        shutil.rmtree(self._tmpdir, ignore_errors=True)

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

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_system_status_routes_http(self) -> None:
        base_url = self._start_server()
        restart_status, restart_body = self._get(base_url, "/server/restart-status")
        self.assertEqual(restart_status, 200)
        self.assertEqual(restart_body["reason"], "http-contract")

        system_status, system_body = self._get(base_url, "/system/status")
        self.assertEqual(system_status, 200)
        self.assertEqual(system_body["system"]["mode"], "normal")

        shutdown_status, shutdown_body = self._get(base_url, "/system/shutdown-status")
        self.assertEqual(shutdown_status, 200)
        self.assertIn("buddy", shutdown_body["graceful_shutdown"]["missing_agents"])

        with mock.patch("handlers.system_status_routes.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            platform_status, platform_body = self._get(base_url, "/platform/status")
        self.assertEqual(platform_status, 200)
        self.assertEqual(platform_body["agents"][0]["id"], "codex")


if __name__ == "__main__":
    unittest.main()
