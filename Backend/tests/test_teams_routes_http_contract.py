from __future__ import annotations

import json
import os
import sys
import threading
import copy
import urllib.request
import unittest
import uuid
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.teams_routes as routes_mod  # noqa: E402
import handlers.teams_routes as routes_mod  # noqa: E402


class TestTeamsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_atomic_write = srv._atomic_write_team_json
        srv.BRIDGE_STRICT_AUTH = False
        srv.TEAM_CONFIG = copy.deepcopy(srv.TEAM_CONFIG)
        srv._atomic_write_team_json = lambda: None
        routes_mod.init(
            team_config_getter=lambda: srv.TEAM_CONFIG,
            team_config_snapshot_fn=srv._team_config_snapshot,
            current_runtime_overlay_fn=lambda: srv._current_runtime_overlay(),
            runtime_overlay_orgchart_response_fn=lambda overlay: srv._runtime_overlay_orgchart_response(overlay),
            runtime_overlay_team_projects_response_fn=lambda overlay: srv._runtime_overlay_team_projects_response(
                overlay
            ),
            runtime_overlay_teams_response_fn=lambda overlay: srv._runtime_overlay_teams_response(overlay),
            runtime_overlay_team_detail_fn=lambda overlay, team_id: srv._runtime_overlay_team_detail(overlay, team_id),
            runtime_overlay_team_context_fn=lambda overlay, agent_id: srv._runtime_overlay_team_context(
                overlay, agent_id
            ),
            registered_agents_getter=lambda: srv.REGISTERED_AGENTS,
            agent_activities_getter=lambda: srv.AGENT_ACTIVITIES,
            agent_connection_status_fn=srv.agent_connection_status,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            atomic_write_team_json_fn=lambda: srv._atomic_write_team_json(),
            utc_now_iso_fn=srv.utc_now_iso,
            ws_broadcast_fn=srv.ws_broadcast,
            notify_team_change_fn=srv._notify_team_change,
            hot_reload_team_config_fn=srv._hot_reload_team_config,
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.TEAM_CONFIG = self._orig_team_config
        srv._atomic_write_team_json = self._orig_atomic_write

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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _put(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_team_read_routes_http(self) -> None:
        base_url = self._start_server()

        orgchart_status, orgchart_body = self._get(base_url, "/team/orgchart")
        self.assertEqual(orgchart_status, 200)
        self.assertIn("agents", orgchart_body)
        self.assertTrue(orgchart_body["agents"])

        projects_status, projects_body = self._get(base_url, "/team/projects")
        self.assertEqual(projects_status, 200)
        self.assertIn("projects", projects_body)

        teams_status, teams_body = self._get(base_url, "/teams")
        self.assertEqual(teams_status, 200)
        self.assertIn("teams", teams_body)
        self.assertTrue(teams_body["teams"])

        team_id = teams_body["teams"][0]["id"]
        team_status, team_body = self._get(base_url, f"/teams/{team_id}")
        self.assertEqual(team_status, 200)
        self.assertEqual(team_body["id"], team_id)

        context_status, context_body = self._get(base_url, "/team/context/codex")
        self.assertEqual(context_status, 200)
        self.assertEqual(context_body["agent_id"], "codex")

        reload_status, reload_body = self._post(base_url, "/team/reload", {})
        self.assertEqual(reload_status, 200)
        self.assertTrue(reload_body["ok"])
        self.assertIn("agents_before", reload_body)
        self.assertIn("agents_after", reload_body)

    def test_team_write_routes_http(self) -> None:
        base_url = self._start_server()
        suffix = uuid.uuid4().hex[:8]
        team_name = f"Slice 85 Team {suffix}"
        team_id = f"slice-85-team-{suffix}"

        created_status, created_body = self._post(
            base_url,
            "/teams",
            {"name": team_name, "lead": "codex", "members": ["buddy"], "scope": "qa"},
        )
        self.assertEqual(created_status, 201)
        self.assertEqual(created_body["team"]["id"], team_id)

        updated_status, updated_body = self._put(
            base_url,
            f"/teams/{team_id}/members",
            {"add": ["user"], "remove": ["buddy"]},
        )
        self.assertEqual(updated_status, 200)
        self.assertEqual(updated_body["team_id"], team_id)
        self.assertIn("user", updated_body["members"])

        deleted_status, deleted_body = self._delete(base_url, f"/teams/{team_id}")
        self.assertEqual(deleted_status, 200)
        self.assertEqual(deleted_body["team_id"], team_id)
        self.assertFalse(deleted_body["active"])


if __name__ == "__main__":
    unittest.main()
