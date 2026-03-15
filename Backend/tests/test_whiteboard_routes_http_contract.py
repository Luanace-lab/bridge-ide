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
import handlers.whiteboard as whiteboard_mod  # noqa: E402


class TestWhiteboardRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="whiteboard_routes_http_contract_")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_whiteboard = srv.WHITEBOARD
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_lock = srv.WHITEBOARD_LOCK
        self._broadcasts: list[tuple[str, dict]] = []

        srv.BRIDGE_STRICT_AUTH = False
        srv.WHITEBOARD = {}
        srv.WHITEBOARD_LOCK = threading.RLock()
        srv.TEAM_CONFIG = {"agents": [{"id": "codex", "name": "Codex"}]}
        whiteboard_mod.init(
            whiteboard=srv.WHITEBOARD,
            whiteboard_lock=srv.WHITEBOARD_LOCK,
            team_config=srv.TEAM_CONFIG,
            base_dir=self._tmpdir,
            agent_log_dir=self._tmpdir,
            whiteboard_valid_types=srv.WHITEBOARD_VALID_TYPES,
            ws_broadcast_fn=lambda event, payload: self._broadcasts.append((event, payload)),
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.WHITEBOARD = self._orig_whiteboard
        srv.WHITEBOARD_LOCK = self._orig_lock
        srv.TEAM_CONFIG = self._orig_team_config
        whiteboard_mod.init(
            whiteboard=srv.WHITEBOARD,
            whiteboard_lock=srv.WHITEBOARD_LOCK,
            team_config=srv.TEAM_CONFIG,
            base_dir=srv.BASE_DIR,
            agent_log_dir=srv.AGENT_LOG_DIR,
            whiteboard_valid_types=srv.WHITEBOARD_VALID_TYPES,
            ws_broadcast_fn=srv.ws_broadcast,
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

    def _post(self, base_url: str, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_whiteboard_get_post_alias_and_delete(self) -> None:
        base_url = self._start_server()

        status_post, body_post = self._post(
            base_url,
            "/whiteboard",
            {"agent_id": "codex", "type": "status", "content": "Slice66 live", "priority": 2},
        )
        self.assertEqual(status_post, 200)
        entry_id = body_post["entry"]["id"]

        status_alias, body_alias = self._post(
            base_url,
            "/whiteboard/post",
            {"agent_id": "codex", "type": "bogus", "content": "Alias"},
        )
        self.assertEqual(status_alias, 200)
        self.assertEqual(body_alias["entry"]["type"], "status")

        status_get, body_get = self._get(base_url, "/whiteboard?agent=codex&priority=2")
        self.assertEqual(status_get, 200)
        self.assertGreaterEqual(body_get["count"], 1)
        self.assertEqual(body_get["entries"][0]["agent_id"], "codex")

        status_delete, body_delete = self._delete(base_url, f"/whiteboard/{entry_id}")
        self.assertEqual(status_delete, 200)
        self.assertEqual(body_delete["deleted"]["id"], entry_id)
        self.assertGreaterEqual(len(self._broadcasts), 3)


if __name__ == "__main__":
    unittest.main()
