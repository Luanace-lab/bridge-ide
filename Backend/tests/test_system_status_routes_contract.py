from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.system_status_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestSystemStatusRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="system_status_routes_contract_")
        pids_dir = os.path.join(self._tmpdir, "Backend", "pids")
        os.makedirs(pids_dir, exist_ok=True)
        pid = os.getpid()
        for name in ("restart_wrapper.pid", "watcher.pid", "output_forwarder.pid"):
            with open(os.path.join(pids_dir, name), "w", encoding="utf-8") as handle:
                handle.write(str(pid))
        routes_mod.init(
            restart_state_getter=lambda: {
                "phase": "warn",
                "started_at": "2099-01-01T00:00:00+00:00",
                "reason": "contract",
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
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_restart_system_and_platform_status(self) -> None:
        restart_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(restart_handler, "/server/restart-status", {}))
        self.assertEqual(restart_handler.responses[0][0], 200)
        self.assertIn("missing_checkpoints", restart_handler.responses[0][1])

        system_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(system_handler, "/system/status", {}))
        self.assertEqual(system_handler.responses[0][1]["system"]["mode"], "normal")

        shutdown_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(shutdown_handler, "/system/shutdown-status", {}))
        self.assertIn("buddy", shutdown_handler.responses[0][1]["graceful_shutdown"]["missing_agents"])

        platform_handler = _DummyHandler()
        with mock.patch("handlers.system_status_routes.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            self.assertTrue(routes_mod.handle_get(platform_handler, "/platform/status", {}))
        self.assertEqual(platform_handler.responses[0][0], 200)
        self.assertEqual(platform_handler.responses[0][1]["agents"][0]["id"], "codex")


if __name__ == "__main__":
    unittest.main()
