from __future__ import annotations

import os
import sys
import threading
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server_message_audience as mod


class TestServerMessageAudienceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.team_config = {
            "agents": [
                {"id": "ordo", "level": 1, "active": True},
                {"id": "viktor", "level": 1, "active": False},
                {"id": "codex", "level": 2, "active": True},
                {"id": "backend", "level": 2, "active": False},
            ]
        }
        self.registered_agents = {
            "ordo": {"ok": True},
            "codex": {"ok": True},
            "backend": {"ok": True},
        }
        self.live_ids = {"ordo", "codex"}
        self.team_members = {"bridge": {"ordo", "codex", "backend"}}

        def _agent_is_live(agent_id: str, stale_seconds: float = 120.0, reg=None) -> bool:
            return agent_id in self.live_ids

        def _get_team_members(team_id: str) -> set[str]:
            return set(self.team_members.get(team_id, set()))

        def _is_management_agent(agent_id: str) -> bool:
            for agent in self.team_config["agents"]:
                if agent["id"] != agent_id:
                    continue
                return bool(agent.get("active", False)) and int(agent.get("level", 99)) <= 1
            return False

        mod.init(
            team_config_getter=lambda: self.team_config,
            registered_agents_getter=lambda: self.registered_agents,
            agent_state_lock=threading.Lock(),
            agent_is_live_fn=_agent_is_live,
            get_team_members_fn=_get_team_members,
            is_management_agent_fn=_is_management_agent,
        )

    def test_configured_all_managers_only_returns_active_management_agents(self) -> None:
        self.assertEqual(mod.resolve_configured_targets("all_managers"), ["ordo"])

    def test_live_all_managers_excludes_live_non_manager_agents(self) -> None:
        self.assertEqual(mod.resolve_live_targets("all_managers"), ["ordo"])

    def test_live_all_includes_live_agents_except_sender(self) -> None:
        self.assertEqual(mod.resolve_live_targets("all", sender="codex"), ["ordo"])

    def test_leads_only_returns_level_one_active_agents(self) -> None:
        self.assertEqual(mod.resolve_configured_targets("leads"), ["ordo"])

    def test_team_targets_only_include_active_members_and_sender_is_excluded(self) -> None:
        self.assertEqual(mod.resolve_configured_targets("team:bridge", sender="codex"), ["ordo"])


if __name__ == "__main__":
    unittest.main()
