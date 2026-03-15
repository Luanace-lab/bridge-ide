from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
import unittest
import uuid
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestBoardRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict

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

    def test_board_routes_http(self) -> None:
        base_url = self._start_server()
        suffix = uuid.uuid4().hex[:8]
        project_id = f"board-http-proj-{suffix}"
        team_id = f"board-http-team-{suffix}"

        projects_status, projects_body = self._get(base_url, "/board/projects")
        self.assertEqual(projects_status, 200)
        self.assertIn("projects", projects_body)
        limited_status, limited_body = self._get(base_url, "/board/projects?limit=1")
        self.assertEqual(limited_status, 200)
        self.assertLessEqual(len(limited_body["projects"]), 1)

        agents_status, agents_body = self._get(base_url, "/board/agents")
        self.assertEqual(agents_status, 200)
        self.assertIn("agents", agents_body)

        created_status, created_body = self._post(
            base_url,
            "/board/projects",
            {"project_id": project_id, "name": "Board HTTP Project"},
        )
        self.assertEqual(created_status, 201)
        self.assertEqual(created_body["project"]["id"], project_id)
        updated_status, updated_body = self._put(
            base_url,
            f"/board/projects/{project_id}",
            {"name": "Board HTTP Project Renamed"},
        )
        self.assertEqual(updated_status, 200)
        self.assertEqual(updated_body["project"]["name"], "Board HTTP Project Renamed")
        team_created_status, team_created_body = self._post(
            base_url,
            f"/board/projects/{project_id}/teams",
            {"id": team_id, "name": "Board HTTP Team"},
        )
        self.assertEqual(team_created_status, 201)
        self.assertEqual(team_created_body["team"]["id"], team_id)
        team_updated_status, team_updated_body = self._put(
            base_url,
            f"/board/projects/{project_id}/teams/{team_id}",
            {"name": "Board HTTP Team Renamed"},
        )
        self.assertEqual(team_updated_status, 200)
        self.assertEqual(team_updated_body["team"]["name"], "Board HTTP Team Renamed")
        member_added_status, member_added_body = self._post(
            base_url,
            f"/board/projects/{project_id}/teams/{team_id}/members",
            {"agent_id": "codex"},
        )
        self.assertEqual(member_added_status, 201)
        self.assertEqual(member_added_body["agent_id"], "codex")
        self.assertEqual(member_added_body["team_id"], team_id)
        member_deleted_status, member_deleted_body = self._delete(
            base_url,
            f"/board/projects/{project_id}/teams/{team_id}/members/codex",
        )
        self.assertEqual(member_deleted_status, 200)
        self.assertEqual(member_deleted_body["removed"], "codex")
        team_deleted_status, team_deleted_body = self._delete(
            base_url,
            f"/board/projects/{project_id}/teams/{team_id}",
        )
        self.assertEqual(team_deleted_status, 200)
        self.assertEqual(team_deleted_body["deleted"], team_id)
        deleted_status, deleted_body = self._delete(base_url, f"/board/projects/{project_id}")
        self.assertEqual(deleted_status, 200)
        self.assertEqual(deleted_body["deleted"], project_id)
