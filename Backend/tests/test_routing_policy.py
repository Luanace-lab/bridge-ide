from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from routing_policy import derive_aliases, derive_routes  # noqa: E402
import server as srv  # noqa: E402


class TestRoutingPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.team = {
            "agents": [
                {"id": "lead_a", "level": 1},
                {"id": "lead_b", "level": 1},
                {"id": "senior_a1", "level": 2, "reports_to": "lead_a", "extra_routes": ["lead_b"]},
                {"id": "senior_a2", "level": 2, "reports_to": "lead_a"},
                {"id": "worker_a", "level": 3, "reports_to": "senior_a1"},
                {"id": "worker_b", "level": 3, "reports_to": "lead_b"},
            ],
            "teams": [
                {"id": "team_a", "lead": "lead_a", "members": ["senior_a1", "worker_a"]},
            ],
        }

    def test_hierarchy_rules_are_v21_consistent(self) -> None:
        routes = derive_routes(self.team, include_team_routes=False)

        self.assertEqual(routes["user"], {"lead_a", "lead_b", "senior_a1", "senior_a2", "worker_a", "worker_b"})
        self.assertIn("senior_a1", routes["worker_a"])
        self.assertIn("user", routes["worker_a"])
        self.assertNotIn("worker_b", routes["worker_a"])
        self.assertIn("senior_a2", routes["senior_a1"])
        self.assertIn("worker_a", routes["senior_a1"])
        self.assertIn("lead_b", routes["senior_a1"])  # explicit extra_route
        self.assertIn("worker_b", routes["lead_a"])  # L1 can reach all others

    def test_team_routes_are_optional_overlay(self) -> None:
        no_team = derive_routes(self.team, include_team_routes=False)
        with_team = derive_routes(self.team, include_team_routes=True)

        self.assertNotIn("lead_a", no_team["worker_a"])
        self.assertIn("lead_a", with_team["worker_a"])
        self.assertIn("worker_a", with_team["lead_a"])

    def test_alias_derivation_keeps_defaults_and_normalizes(self) -> None:
        team = {
            "agents": [
                {"id": "lead_a", "aliases": ["LeadA", "leiter"]},
            ]
        }
        aliases = derive_aliases(team, default_aliases={"teamlead": "ordo"})
        self.assertEqual(aliases["teamlead"], "ordo")
        self.assertEqual(aliases["leada"], "lead_a")
        self.assertEqual(aliases["leiter"], "lead_a")

    def test_server_helpers_use_shared_routing_policy(self) -> None:
        self.assertEqual(srv.derive_routes(self.team), derive_routes(self.team))
        self.assertEqual(
            srv.derive_allowed_routes(self.team),
            derive_routes(self.team, include_team_routes=False),
        )


if __name__ == "__main__":
    unittest.main()
