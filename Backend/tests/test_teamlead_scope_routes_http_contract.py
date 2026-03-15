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


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestTeamleadScopeRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="teamlead_scope_routes_http_contract_")
        self._orig_projects_base_dir = srv.PROJECTS_BASE_DIR
        self._orig_runtime = srv.RUNTIME
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._project_path = os.path.join(self._tmpdir, "alpha")
        os.makedirs(self._project_path, exist_ok=True)
        srv.PROJECTS_BASE_DIR = self._tmpdir
        srv.RUNTIME = {
            "project_path": self._project_path,
            "team_lead_scope_file": os.path.join(self._project_path, "teamlead.md"),
        }
        srv.BRIDGE_STRICT_AUTH = False

    def tearDown(self) -> None:
        srv.PROJECTS_BASE_DIR = self._orig_projects_base_dir
        srv.RUNTIME = self._orig_runtime
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_teamlead_scope_get_and_post_endpoints(self) -> None:
        base_url = self._start_server()
        scope_file = os.path.join(self._project_path, ".bridge", "scope", "lead.md")

        status_write, body_write = self._post(
            base_url,
            "/teamlead/scope",
            {
                "project_path": self._project_path,
                "scope_file": scope_file,
                "content": "Scope contract body",
            },
        )
        self.assertEqual(status_write, 200)
        self.assertTrue(body_write["ok"])
        self.assertEqual(body_write["scope_file"], scope_file)

        status_read, body_read = self._get(
            base_url,
            f"/teamlead/scope?project_path={self._project_path}&path={scope_file}",
        )
        self.assertEqual(status_read, 200)
        self.assertTrue(body_read["exists"])
        self.assertEqual(body_read["content"], "Scope contract body")


if __name__ == "__main__":
    unittest.main()
