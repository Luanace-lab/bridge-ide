from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.git_lock_routes as routes_mod  # noqa: E402


class TestGitLockRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.saved_locks: list[dict] | None = None
        routes_mod.init(
            git_locks_file="/tmp/git_locks_http.json",
            acquire_lock_fn=lambda path, branch, agent, instance_id: {
                "ok": True,
                "branch": branch,
                "agent_id": agent,
                "instance_id": instance_id,
                "path": path,
            },
            release_lock_fn=lambda path, branch, agent: {
                "ok": True,
                "released": branch,
                "agent_id": agent,
                "path": path,
            },
            load_locks_fn=lambda _path: [{"branch": "feature/http", "agent_id": "codex"}],
            save_locks_fn=lambda _path, locks: setattr(self, "saved_locks", locks),
            is_management_agent_fn=lambda agent_id: agent_id == "ordo",
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            git_locks_file=srv._GIT_LOCKS_FILE,
            acquire_lock_fn=srv._gc_acquire_lock,
            release_lock_fn=srv._gc_release_lock,
            load_locks_fn=srv._gc_load_locks,
            save_locks_fn=srv._gc_save_locks,
            is_management_agent_fn=srv._is_management_agent,
        )

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

    def _request(self, base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-Bridge-Agent": "codex"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_git_lock_http_routes(self) -> None:
        base_url = self._start_server()

        status, body = self._request(base_url, "GET", "/git/locks")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)

        status, body = self._request(base_url, "POST", "/git/lock", {"branch": "feature/http", "instance_id": "inst"})
        self.assertEqual(status, 200)
        self.assertEqual(body["agent_id"], "codex")

        status, body = self._request(base_url, "DELETE", "/git/lock", {"branch": "feature/http"})
        self.assertEqual(status, 200)
        self.assertEqual(body["released"], "feature/http")


if __name__ == "__main__":
    unittest.main()
