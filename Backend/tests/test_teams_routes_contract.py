from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.teams_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []
        self.json_body: dict | None = None

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self.json_body


def _team_snapshot() -> dict:
    return {
        "agents": [
            {
                "id": "codex",
                "name": "Codex",
                "role": "senior",
                "description": "Senior coder",
                "skills": ["ship"],
                "permissions": {"write": True},
                "reports_to": "user",
                "level": 2,
                "active": True,
            },
            {
                "id": "buddy",
                "name": "Buddy",
                "role": "companion",
                "skills": ["chat"],
                "active": True,
            },
        ],
        "teams": [
            {"id": "bridge-team", "name": "Bridge Team", "lead": "codex", "members": ["buddy"], "active": True},
            {"id": "inactive-team", "name": "Inactive", "lead": "", "members": [], "active": False},
        ],
        "projects": [
            {
                "id": "bridge",
                "name": "BRIDGE",
                "path": "/tmp/bridge",
                "description": "Bridge project",
                "team_ids": ["bridge-team"],
                "scope_labels": {"core": ["Backend"]},
                "created_at": "2026-03-15T00:00:00+00:00",
            }
        ],
    }


class TestTeamsRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self.team_config = _team_snapshot()
        self.persist_calls = 0
        self.broadcasts: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, str, list[str]]] = []
        routes_mod.init(
            team_config_getter=lambda: self.team_config,
            team_config_snapshot_fn=lambda: _team_snapshot(),
            current_runtime_overlay_fn=lambda: None,
            runtime_overlay_orgchart_response_fn=lambda overlay: {"agents": []},
            runtime_overlay_team_projects_response_fn=lambda overlay: {"projects": []},
            runtime_overlay_teams_response_fn=lambda overlay: {"teams": []},
            runtime_overlay_team_detail_fn=lambda overlay, team_id: None,
            runtime_overlay_team_context_fn=lambda overlay, agent_id: None,
            registered_agents_getter=lambda: {"codex": {"context_pct": 84}, "buddy": {"context_pct": 55}},
            agent_activities_getter=lambda: {"codex": {"timestamp": "2026-03-15T01:00:00+00:00", "description": "refactoring"}},
            agent_connection_status_fn=lambda agent_id: "online" if agent_id == "codex" else "waiting",
            team_config_lock=threading.Lock(),
            atomic_write_team_json_fn=self._persist,
            utc_now_iso_fn=lambda: "2026-03-15T03:00:00+00:00",
            ws_broadcast_fn=self._broadcast,
            notify_team_change_fn=self._notify,
            hot_reload_team_config_fn=lambda: {"ok": True, "source": "reload"},
        )

    def _persist(self) -> None:
        self.persist_calls += 1

    def _broadcast(self, event: str, payload: dict) -> None:
        self.broadcasts.append((event, payload))

    def _notify(self, event_type: str, details: str, *, affected_agents: list[str]) -> None:
        self.notifications.append((event_type, details, list(affected_agents)))

    def test_team_projects_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/team/projects"))
        payload = handler.responses[0][1]
        self.assertEqual(payload["projects"][0]["id"], "bridge")
        self.assertEqual(payload["projects"][0]["teams"][0]["members"][0]["id"], "buddy")

    def test_team_orgchart_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/team/orgchart"))
        payload = handler.responses[0][1]
        self.assertEqual(payload["owner"]["status"], "online")
        self.assertEqual(payload["agents"][0]["id"], "codex")
        self.assertIn("active", payload["agents"][0])
        self.assertIn("online", payload["agents"][0])
        self.assertIn("auto_start", payload["agents"][0])

    def test_teams_route_hides_inactive_by_default(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/teams"))
        teams = handler.responses[0][1]["teams"]
        self.assertEqual([team["id"] for team in teams], ["bridge-team"])

    def test_teams_route_can_include_inactive(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/teams", {"include_inactive": ["true"]}))
        teams = handler.responses[0][1]["teams"]
        self.assertEqual({team["id"] for team in teams}, {"bridge-team", "inactive-team"})

    def test_team_detail_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/teams/bridge-team"))
        payload = handler.responses[0][1]
        self.assertEqual(payload["id"], "bridge-team")
        self.assertEqual(payload["members"][0]["id"], "buddy")
        self.assertEqual(payload["members"][1]["context_pct"], 84)

    def test_team_context_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/team/context/codex"))
        payload = handler.responses[0][1]
        self.assertEqual(payload["agent_id"], "codex")
        self.assertEqual(payload["team"]["id"], "bridge-team")
        self.assertEqual(payload["teammates"][0]["id"], "buddy")

    def test_overlay_detail_fallback_when_team_not_in_snapshot(self) -> None:
        routes_mod.init(
            team_config_getter=lambda: None,
            team_config_snapshot_fn=lambda: None,
            current_runtime_overlay_fn=lambda: {"overlay": True},
            runtime_overlay_orgchart_response_fn=lambda overlay: {"agents": [{"id": "runtime-agent"}]},
            runtime_overlay_team_projects_response_fn=lambda overlay: {"projects": []},
            runtime_overlay_teams_response_fn=lambda overlay: {"teams": []},
            runtime_overlay_team_detail_fn=lambda overlay, team_id: {"id": team_id, "members": []},
            runtime_overlay_team_context_fn=lambda overlay, agent_id: {"agent": {"id": agent_id}, "team": {}, "teammates": []},
            registered_agents_getter=lambda: {},
            agent_activities_getter=lambda: {},
            agent_connection_status_fn=lambda agent_id: "offline",
            team_config_lock=threading.Lock(),
            atomic_write_team_json_fn=lambda: None,
            utc_now_iso_fn=lambda: "2026-03-15T03:00:00+00:00",
            ws_broadcast_fn=lambda event, payload: None,
            notify_team_change_fn=lambda event_type, details, *, affected_agents: None,
            hot_reload_team_config_fn=lambda: {"ok": True, "source": "overlay"},
        )
        detail_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(detail_handler, "/teams/runtime-team"))
        self.assertEqual(detail_handler.responses[0][1]["id"], "runtime-team")

        context_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(context_handler, "/team/context/runtime-agent"))
        self.assertEqual(context_handler.responses[0][1]["agent"]["id"], "runtime-agent")

    def test_team_create_route(self) -> None:
        handler = _DummyHandler()
        handler.json_body = {"name": "Slice 85 Team", "lead": "codex", "members": ["buddy"], "scope": "qa"}
        self.assertTrue(routes_mod.handle_post(handler, "/teams"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertEqual(self.team_config["teams"][-1]["id"], "slice-85-team")
        self.assertEqual(self.persist_calls, 1)
        self.assertEqual(self.broadcasts[-1][0], "team_created")

    def test_team_reload_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_post(handler, "/team/reload"))
        self.assertEqual(handler.responses[0], (200, {"ok": True, "source": "reload"}))

    def test_team_member_update_route(self) -> None:
        handler = _DummyHandler()
        handler.json_body = {"add": ["newbie"], "remove": ["buddy"]}
        self.assertTrue(routes_mod.handle_put(handler, "/teams/bridge-team/members"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["members"], ["newbie"])
        self.assertEqual(self.broadcasts[-1][0], "team_updated")
        self.assertEqual(self.notifications[-1][0], "team_members_changed")

    def test_team_delete_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_delete(handler, "/teams/bridge-team"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertFalse(self.team_config["teams"][0]["active"])
        self.assertEqual(self.broadcasts[-1][0], "team_deleted")
        self.assertEqual(self.notifications[-1][0], "team_deleted")

    @patch("handlers.teams_routes.print")
    def test_duplicate_team_create_conflict(self, _mock_print: object) -> None:
        handler = _DummyHandler()
        handler.json_body = {"name": "Bridge Team", "lead": "codex"}
        self.assertTrue(routes_mod.handle_post(handler, "/teams"))
        self.assertEqual(handler.responses[0][0], 409)


if __name__ == "__main__":
    unittest.main()
