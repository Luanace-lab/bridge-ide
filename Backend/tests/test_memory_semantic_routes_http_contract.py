from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestMemorySemanticRoutesHttpContract(unittest.TestCase):
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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_memory_semantic_routes_http(self) -> None:
        base_url = self._start_server()
        with mock.patch(
            "semantic_memory.index_scoped_text",
            return_value={"ok": True, "document_id": "doc-http"},
        ), mock.patch(
            "semantic_memory.search_scope",
            return_value={"ok": True, "matches": [{"document_id": "doc-http"}], "count": 1},
        ), mock.patch(
            "semantic_memory.delete_document",
            return_value={"ok": True, "deleted": 1},
        ):
            index_status, index_body = self._post(
                base_url,
                "/memory/index",
                {
                    "scope_type": "project",
                    "scope_id": "slice73-http",
                    "text": "HTTP semantic route test.",
                    "document_id": "doc-http",
                    "replace_document": True,
                },
            )
            self.assertEqual(index_status, 200)
            self.assertTrue(index_body["ok"])

            search_status, search_body = self._post(
                base_url,
                "/memory/search",
                {"scope_type": "project", "scope_id": "slice73-http", "query": "route test"},
            )
            self.assertEqual(search_status, 200)
            self.assertEqual(search_body["count"], 1)

            delete_status, delete_body = self._post(
                base_url,
                "/memory/delete",
                {"scope_type": "project", "scope_id": "slice73-http", "document_id": "doc-http"},
            )
            self.assertEqual(delete_status, 200)
            self.assertTrue(delete_body["ok"])


if __name__ == "__main__":
    unittest.main()
