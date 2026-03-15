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


class TestProjectsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="projects_routes_http_contract_")
        self._orig_root_dir = srv.ROOT_DIR
        self._orig_projects_base_dir = srv.PROJECTS_BASE_DIR
        self._project_path = os.path.join(self._tmpdir, "alpha")
        os.makedirs(os.path.join(self._project_path, ".bridge"), exist_ok=True)
        with open(os.path.join(self._project_path, "PROJECT.md"), "w", encoding="utf-8") as handle:
            handle.write("Alpha project notes")
        with open(os.path.join(self._project_path, ".bridge", "tags.json"), "w", encoding="utf-8") as handle:
            json.dump(["bridge", "alpha"], handle)
        srv.ROOT_DIR = self._tmpdir
        srv.PROJECTS_BASE_DIR = self._tmpdir

    def tearDown(self) -> None:
        srv.ROOT_DIR = self._orig_root_dir
        srv.PROJECTS_BASE_DIR = self._orig_projects_base_dir
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

    def test_projects_list_open_and_context_endpoints(self) -> None:
        base_url = self._start_server()

        status_projects, body_projects = self._get(base_url, f"/projects?base_dir={self._tmpdir}")
        self.assertEqual(status_projects, 200)
        self.assertEqual(body_projects["count"], 1)
        self.assertEqual(body_projects["projects"][0]["name"], "alpha")

        status_open, body_open = self._get(base_url, f"/projects/open?project_path={self._project_path}")
        self.assertEqual(status_open, 200)
        self.assertTrue(body_open["ok"])
        self.assertEqual(body_open["name"], "alpha")
        self.assertEqual(body_open["notes"], "Alpha project notes")
        self.assertEqual(body_open["tags"], ["bridge", "alpha"])

        status_context, body_context = self._get(base_url, f"/context?project_path={self._project_path}")
        self.assertEqual(status_context, 200)
        self.assertEqual(body_context["project_path"], self._project_path)
        self.assertIn("codex", body_context)
        self.assertIn("claude", body_context)


if __name__ == "__main__":
    unittest.main()
