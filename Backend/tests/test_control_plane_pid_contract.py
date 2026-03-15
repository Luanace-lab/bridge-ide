from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestControlPlanePidContract(unittest.TestCase):
    def test_known_agent_names_excludes_control_plane_pid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for filename in (
                "restart_wrapper.pid",
                "watcher.pid",
                "output_forwarder.pid",
                "server.pid",
                "backend_agent.pid",
                "legacy_worker.pid",
            ):
                with open(os.path.join(tmpdir, filename), "w", encoding="utf-8") as handle:
                    handle.write("123\n")

            with (
                mock.patch.object(srv, "PID_DIR", tmpdir),
                mock.patch.object(srv, "RUNTIME", {"agents": []}),
            ):
                names = srv.known_agent_names()

        self.assertEqual(names, {"backend_agent", "legacy_worker"})


if __name__ == "__main__":
    unittest.main()
