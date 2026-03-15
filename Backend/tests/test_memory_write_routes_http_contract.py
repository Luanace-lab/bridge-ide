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
import handlers.memory as memory_mod  # noqa: E402


class TestMemoryWriteRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="memory_write_routes_http_contract_")
        self._project_path = os.path.join(self._tmpdir, "project")
        os.makedirs(self._project_path, exist_ok=True)
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        memory_mod.init(
            ensure_parent_dir_fn=srv.ensure_parent_dir,
            normalize_path_fn=srv.normalize_path,
            root_dir_fn=lambda: self._tmpdir,
        )

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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_memory_write_routes_http(self) -> None:
        base_url = self._start_server()

        scaffold_status, scaffold_body = self._post(
            base_url,
            "/memory/scaffold",
            {"project_path": self._project_path},
        )
        self.assertEqual(scaffold_status, 201)
        self.assertTrue(scaffold_body["ok"])

        write_status, write_body = self._post(
            base_url,
            "/memory/write",
            {
                "project_path": self._project_path,
                "agent_id": "codex",
                "category": "agent_private",
                "content": "Slice72 http note.",
                "mode": "replace",
            },
        )
        self.assertEqual(write_status, 201)
        self.assertTrue(write_body["ok"])

        episode_status, episode_body = self._post(
            base_url,
            "/memory/episode",
            {
                "project_path": self._project_path,
                "agent_id": "codex",
                "summary": "Slice72 http episode.",
                "task": "http route",
            },
        )
        self.assertEqual(episode_status, 201)
        self.assertTrue(episode_body["ok"])

        project_note = os.path.join(self._project_path, ".agent", "project", "PROJECT.md")
        with open(project_note, "w", encoding="utf-8") as handle:
            handle.write("Slice72 migrate http.")

        migrate_status, migrate_body = self._post(
            base_url,
            "/memory/migrate",
            {"project_path": self._project_path},
        )
        self.assertEqual(migrate_status, 200)
        self.assertTrue(migrate_body["ok"])


if __name__ == "__main__":
    unittest.main()
