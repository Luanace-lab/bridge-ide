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
import handlers.logs_routes as logs_mod  # noqa: E402


class TestLogsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        logs_mod.init(
            parse_non_negative_int_fn=srv.parse_non_negative_int,
            tail_log_fn=lambda name, lines: {
                "name": name,
                "path": f"/tmp/{name}.log",
                "lines": [f"line-{i}" for i in range(lines)],
                "count": lines,
            },
        )

    def tearDown(self) -> None:
        logs_mod.init(
            parse_non_negative_int_fn=srv.parse_non_negative_int,
            tail_log_fn=srv.tail_log,
        )
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

    def test_logs_endpoint_returns_tail_payload(self) -> None:
        base_url = self._start_server()
        status, body = self._get(base_url, "/logs?name=server&lines=3")
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "server")
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["lines"], ["line-0", "line-1", "line-2"])


if __name__ == "__main__":
    unittest.main()
