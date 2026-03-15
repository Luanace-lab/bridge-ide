from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import start_agents  # noqa: E402


class TestStartAgentsContract(unittest.TestCase):
    def test_load_auto_start_agents_requires_active_and_auto_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            team_path = Path(tmpdir) / "team.json"
            team_path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {"id": "codex", "active": True, "auto_start": True},
                            {"id": "viktor", "active": True, "auto_start": False},
                            {"id": "backend", "active": False, "auto_start": True},
                            {"id": "", "active": True, "auto_start": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(start_agents, "BRIDGE_DIR", Path(tmpdir)):
                agents = start_agents._load_auto_start_agents()

        self.assertEqual([agent["id"] for agent in agents], ["codex"])

    def test_main_fails_closed_when_runtime_is_unconfigured(self) -> None:
        with (
            mock.patch.object(start_agents, "_runtime_is_configured", return_value=(False, "runtime not configured")),
            mock.patch.object(start_agents, "_load_auto_start_agents", return_value=[{"id": "codex"}]),
        ):
            self.assertEqual(start_agents.main(), 1)

    def test_main_returns_nonzero_when_any_agent_fails(self) -> None:
        agents = [{"id": "codex"}, {"id": "claude"}]
        with (
            mock.patch.object(start_agents, "_runtime_is_configured", return_value=(True, "")),
            mock.patch.object(start_agents, "_load_auto_start_agents", return_value=agents),
            mock.patch.object(start_agents, "_is_agent_running", side_effect=[False, False]),
            mock.patch.object(start_agents, "_start_via_api", side_effect=[True, False]),
            mock.patch.object(start_agents.time, "sleep"),
        ):
            self.assertEqual(start_agents.main(), 1)

    def test_main_returns_zero_when_agents_are_started_or_already_running(self) -> None:
        agents = [{"id": "codex"}, {"id": "claude"}]
        with (
            mock.patch.object(start_agents, "_runtime_is_configured", return_value=(True, "")),
            mock.patch.object(start_agents, "_load_auto_start_agents", return_value=agents),
            mock.patch.object(start_agents, "_is_agent_running", side_effect=[False, True]),
            mock.patch.object(start_agents, "_start_via_api", return_value=True),
            mock.patch.object(start_agents.time, "sleep"),
        ):
            self.assertEqual(start_agents.main(), 0)


if __name__ == "__main__":
    unittest.main()
