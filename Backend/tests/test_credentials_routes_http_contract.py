from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestCredentialsRoutesHttpContract(unittest.TestCase):
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

    def _request(
        self,
        base_url: str,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            method=method,
            headers=headers or {},
        )
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    @patch("handlers.credentials_routes.credential_store.delete")
    @patch("handlers.credentials_routes.credential_store.store")
    @patch("handlers.credentials_routes.credential_store.get")
    @patch("handlers.credentials_routes.credential_store.list_keys")
    def test_credentials_http_routes(
        self,
        mock_list_keys,
        mock_get,
        mock_store,
        mock_delete,
    ) -> None:
        mock_list_keys.return_value = {"service": "custom", "keys": [{"key": "alpha"}]}
        mock_get.return_value = {"service": "custom", "key": "alpha", "value": "secret"}
        mock_store.return_value = {"service": "custom", "key": "alpha", "stored": True}
        mock_delete.return_value = {"service": "custom", "key": "alpha", "deleted": True}

        base_url = self._start_server()
        headers = {"X-Bridge-Agent": "codex"}

        status, body = self._request(base_url, "GET", "/credentials/custom", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "custom")

        status, body = self._request(base_url, "GET", "/credentials/custom/alpha", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(body["key"], "alpha")

        status, body = self._request(
            base_url,
            "POST",
            "/credentials/custom/alpha",
            payload={"value": "secret"},
            headers=headers,
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["stored"])

        status, body = self._request(base_url, "DELETE", "/credentials/custom/alpha", headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])


if __name__ == "__main__":
    unittest.main()
