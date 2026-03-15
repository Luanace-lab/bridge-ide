from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.board_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []
        self.json_body: dict | None = None

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self.json_body


class TestBoardRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        routes_mod.init(
            registered_agents_getter=lambda: {"codex": {"status": "running"}},
            agent_activities_getter=lambda: {"codex": {"description": "active"}},
            current_runtime_overlay_fn=lambda: None,
            runtime_overlay_board_projects_response_fn=lambda overlay: {"projects": []},
        )

    @patch("handlers.board_routes.board_api.get_all_projects")
    def test_board_projects_route(self, mock_get_all_projects) -> None:
        mock_get_all_projects.return_value = {"projects": [{"id": "proj-1"}]}
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/board/projects"))
        self.assertEqual(handler.responses[0][1]["projects"][0]["id"], "proj-1")

    @patch("handlers.board_routes.board_api.get_project")
    def test_single_board_project_route(self, mock_get_project) -> None:
        mock_get_project.return_value = {"project": {"id": "proj-2"}}
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/board/projects/proj-2"))
        self.assertEqual(handler.responses[0][1]["project"]["id"], "proj-2")

    @patch("handlers.board_routes.board_api.get_all_agents")
    @patch("handlers.board_routes.board_api.get_agent_projects")
    def test_board_agents_routes(self, mock_get_agent_projects, mock_get_all_agents) -> None:
        mock_get_all_agents.return_value = {"agents": [{"id": "codex"}]}
        mock_get_agent_projects.return_value = {"agent": {"id": "codex", "projects": []}}

        agents_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(agents_handler, "/board/agents"))
        self.assertEqual(agents_handler.responses[0][1]["agents"][0]["id"], "codex")

        agent_projects_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(agent_projects_handler, "/board/agents/codex/projects"))
        self.assertEqual(agent_projects_handler.responses[0][1]["agent"]["id"], "codex")

    def test_overlay_project_takes_precedence(self) -> None:
        routes_mod.init(
            registered_agents_getter=lambda: {"codex": {"status": "running"}},
            agent_activities_getter=lambda: {},
            current_runtime_overlay_fn=lambda: {"overlay": True},
            runtime_overlay_board_projects_response_fn=lambda overlay: {"projects": [{"id": "overlay-proj"}]},
        )
        with patch("handlers.board_routes.board_api.get_all_projects", return_value={"projects": [{"id": "base-proj"}]}):
            handler = _DummyHandler()
            self.assertTrue(routes_mod.handle_get(handler, "/board/projects"))
            self.assertEqual(handler.responses[0][1]["projects"][0]["id"], "overlay-proj")

    @patch("handlers.board_routes.board_api.create_project")
    def test_board_project_create_accepts_project_id_alias(self, mock_create_project) -> None:
        mock_create_project.return_value = {"ok": True, "project": {"id": "proj-3"}}
        handler = _DummyHandler()
        handler.json_body = {"project_id": "proj-3", "name": "Project Three"}
        self.assertTrue(routes_mod.handle_post(handler, "/board/projects"))
        mock_create_project.assert_called_once_with("proj-3", "Project Three")
        self.assertEqual(handler.responses[0][0], 201)

    @patch("handlers.board_routes.board_api.update_project")
    def test_board_project_update_route(self, mock_update_project) -> None:
        mock_update_project.return_value = {"ok": True, "project": {"id": "proj-3", "name": "Renamed"}}
        handler = _DummyHandler()
        handler.json_body = {"name": "Renamed"}
        self.assertTrue(routes_mod.handle_put(handler, "/board/projects/proj-3"))
        mock_update_project.assert_called_once_with("proj-3", "Renamed")
        self.assertEqual(handler.responses[0][0], 200)

    @patch("handlers.board_routes.board_api.delete_project")
    def test_board_project_delete_route(self, mock_delete_project) -> None:
        mock_delete_project.return_value = {"ok": True, "deleted": "proj-3"}
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_delete(handler, "/board/projects/proj-3"))
        mock_delete_project.assert_called_once_with("proj-3")
        self.assertEqual(handler.responses[0][0], 200)

    @patch("handlers.board_routes.board_api.add_team")
    def test_board_team_create_route(self, mock_add_team) -> None:
        mock_add_team.return_value = {"ok": True, "team": {"id": "team-1"}}
        handler = _DummyHandler()
        handler.json_body = {"id": "team-1", "name": "Team One"}
        self.assertTrue(routes_mod.handle_post(handler, "/board/projects/proj-3/teams"))
        mock_add_team.assert_called_once_with("proj-3", "team-1", "Team One")
        self.assertEqual(handler.responses[0][0], 201)

    @patch("handlers.board_routes.board_api.update_team")
    def test_board_team_update_route(self, mock_update_team) -> None:
        mock_update_team.return_value = {"ok": True, "team": {"id": "team-1", "name": "Team One Renamed"}}
        handler = _DummyHandler()
        handler.json_body = {"name": "Team One Renamed"}
        self.assertTrue(routes_mod.handle_put(handler, "/board/projects/proj-3/teams/team-1"))
        mock_update_team.assert_called_once_with("proj-3", "team-1", "Team One Renamed")
        self.assertEqual(handler.responses[0][0], 200)

    @patch("handlers.board_routes.board_api.delete_team")
    def test_board_team_delete_route(self, mock_delete_team) -> None:
        mock_delete_team.return_value = {"ok": True, "deleted": "team-1"}
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_delete(handler, "/board/projects/proj-3/teams/team-1"))
        mock_delete_team.assert_called_once_with("proj-3", "team-1")
        self.assertEqual(handler.responses[0][0], 200)

    @patch("handlers.board_routes.board_api.add_member")
    def test_board_member_add_route(self, mock_add_member) -> None:
        mock_add_member.return_value = {"ok": True, "team": {"id": "team-1", "members": ["codex"]}}
        handler = _DummyHandler()
        handler.json_body = {"agent_id": "codex"}
        self.assertTrue(routes_mod.handle_post(handler, "/board/projects/proj-3/teams/team-1/members"))
        mock_add_member.assert_called_once_with("proj-3", "team-1", "codex")
        self.assertEqual(handler.responses[0][0], 201)

    @patch("handlers.board_routes.board_api.remove_member")
    def test_board_member_remove_route(self, mock_remove_member) -> None:
        mock_remove_member.return_value = {"ok": True, "team": {"id": "team-1", "members": []}}
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_delete(handler, "/board/projects/proj-3/teams/team-1/members/codex"))
        mock_remove_member.assert_called_once_with("proj-3", "team-1", "codex")
        self.assertEqual(handler.responses[0][0], 200)

    def test_board_projects_limit_query_is_applied(self) -> None:
        with patch(
            "handlers.board_routes.board_api.get_all_projects",
            return_value={"projects": [{"id": "a"}, {"id": "b"}]},
        ):
            handler = _DummyHandler()
            self.assertTrue(routes_mod.handle_get(handler, "/board/projects", {"limit": ["1"]}))
            self.assertEqual(len(handler.responses[0][1]["projects"]), 1)


if __name__ == "__main__":
    unittest.main()
