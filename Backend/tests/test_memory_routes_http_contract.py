from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.memory as memory_mod  # noqa: E402


class TestMemoryRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="memory_routes_http_contract_")
        self._project_path = os.path.join(self._tmpdir, "project")
        os.makedirs(self._project_path, exist_ok=True)
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        memory_mod.init(
            ensure_parent_dir_fn=srv.ensure_parent_dir,
            normalize_path_fn=srv.normalize_path,
            root_dir_fn=lambda: self._tmpdir,
        )
        scaffold = memory_mod.scaffold_agent_memory(self._project_path)
        assert scaffold.get("ok"), scaffold
        write = memory_mod.write_agent_memory(
            self._project_path,
            "codex",
            "agent_private",
            "Slice71 http note.",
            mode="replace",
        )
        assert write.get("ok"), write

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        memory_mod.init(
            ensure_parent_dir_fn=srv.ensure_parent_dir,
            normalize_path_fn=srv.normalize_path,
            root_dir_fn=lambda: srv.ROOT_DIR,
        )
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

    def test_memory_read_status_and_stats_http(self) -> None:
        base_url = self._start_server()
        project_query = urllib.parse.quote(self._project_path, safe="")

        status_code, status_body = self._get(
            base_url,
            f"/memory/status?project_path={project_query}&agent_id=codex&role=backend",
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(status_body["initialized"])
        self.assertIn("constitution", status_body)
        self.assertEqual(status_body["constitution"]["agent_id"], "codex")
        self.assertEqual(status_body["constitution"]["role"], "backend")

        read_code, read_body = self._get(
            base_url,
            f"/memory/read?project_path={project_query}&agent_id=codex&max_tokens=600",
        )
        self.assertEqual(read_code, 200)
        self.assertIn("Slice71 http note.", read_body["packet"])

        with mock.patch("semantic_memory.get_stats", return_value={"count": 7}):
            stats_code, stats_body = self._get(base_url, "/memory/stats?agent_id=codex")
        self.assertEqual(stats_code, 200)
        self.assertEqual(stats_body["count"], 7)


if __name__ == "__main__":
    unittest.main()
