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
import handlers.onboarding_routes as routes_mod  # noqa: E402


class TestOnboardingRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.init(
            strict_auth_getter=lambda: False,
            ensure_buddy_frontdoor_fn=lambda user_id: {"status": "already_running", "user_id": user_id, "started": False},
            get_buddy_frontdoor_status_fn=lambda user_id: {"user_id": user_id, "known_user": False, "buddy_running": False},
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            strict_auth_getter=lambda: srv.BRIDGE_STRICT_AUTH,
            ensure_buddy_frontdoor_fn=srv._ensure_buddy_frontdoor,
            get_buddy_frontdoor_status_fn=srv._get_buddy_frontdoor_status,
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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_onboarding_route_http(self) -> None:
        base_url = self._start_server()
        status, body = self._post(base_url, "/onboarding/start", {"user_id": "slice96-http"})
        self.assertEqual(status, 200)
        self.assertEqual(body["user_id"], "slice96-http")

    def test_onboarding_status_route_http(self) -> None:
        base_url = self._start_server()
        req = urllib.request.Request(f"{base_url}/onboarding/status?user_id=slice97-http")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["user_id"], "slice97-http")


if __name__ == "__main__":
    unittest.main()
