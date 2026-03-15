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
import handlers.subscriptions_routes as subs_mod  # noqa: E402


class TestSubscriptionsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="subscriptions_routes_http_contract_")
        self._profile_dir = os.path.join(self._tmpdir, "profile")
        os.makedirs(self._profile_dir, exist_ok=True)
        with open(os.path.join(self._profile_dir, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"ok": True}, handle)

        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_team_config_lock = srv.TEAM_CONFIG_LOCK

        srv.BRIDGE_STRICT_AUTH = False
        srv.TEAM_CONFIG = {"agents": [{"id": "codex", "config_dir": ""}], "subscriptions": []}
        srv.TEAM_CONFIG_LOCK = threading.RLock()
        subs_mod.init(
            team_config=srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            build_subscription_response_item_fn=lambda sub, _agents: dict(sub),
            infer_subscription_provider_fn=srv._infer_subscription_provider,
            atomic_write_team_json_fn=lambda: None,
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.TEAM_CONFIG = self._orig_team_config
        srv.TEAM_CONFIG_LOCK = self._orig_team_config_lock
        subs_mod.init(
            team_config=srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            build_subscription_response_item_fn=srv._build_subscription_response_item,
            infer_subscription_provider_fn=srv._infer_subscription_provider,
            atomic_write_team_json_fn=srv._atomic_write_team_json,
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

    def _request(self, method: str, base_url: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_subscription_crud_http_roundtrip(self) -> None:
        base_url = self._start_server()

        status_create, body_create = self._request(
            "POST",
            base_url,
            "/subscriptions",
            {"name": "Slice67 HTTP", "path": self._profile_dir},
        )
        self.assertEqual(status_create, 201)
        sub_id = body_create["subscription"]["id"]

        status_list, body_list = self._request("GET", base_url, "/subscriptions")
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["subscriptions"][0]["id"], sub_id)

        status_update, body_update = self._request(
            "PUT",
            base_url,
            f"/subscriptions/{sub_id}",
            {"name": "Slice67 HTTP Updated", "active": False},
        )
        self.assertEqual(status_update, 200)
        self.assertEqual(body_update["subscription"]["name"], "Slice67 HTTP Updated")
        self.assertFalse(body_update["subscription"]["active"])

        status_delete, body_delete = self._request("DELETE", base_url, f"/subscriptions/{sub_id}")
        self.assertEqual(status_delete, 200)
        self.assertEqual(body_delete["deleted"]["id"], sub_id)


if __name__ == "__main__":
    unittest.main()
