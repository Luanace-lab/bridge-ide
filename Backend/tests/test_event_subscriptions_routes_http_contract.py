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
import handlers.event_subscriptions_routes as event_subs_mod  # noqa: E402


class TestEventSubscriptionsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self._subs: list[dict] = []

        def list_subscriptions(*, created_by=None):
            if created_by:
                return [sub for sub in self._subs if sub.get("created_by") == created_by]
            return list(self._subs)

        def subscribe(*, event_type, webhook_url, created_by, filter_rules, label):
            sub = {
                "id": f"http-sub-{len(self._subs)+1}",
                "event_type": event_type,
                "webhook_url": webhook_url,
                "created_by": created_by,
                "filter": filter_rules,
                "label": label,
            }
            self._subs.append(sub)
            return sub

        def unsubscribe(sub_id: str) -> bool:
            for idx, sub in enumerate(self._subs):
                if sub["id"] == sub_id:
                    self._subs.pop(idx)
                    return True
            return False

        event_subs_mod.init(
            list_subscriptions_fn=list_subscriptions,
            subscribe_fn=subscribe,
            unsubscribe_fn=unsubscribe,
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        event_subs_mod.init(
            list_subscriptions_fn=srv.event_bus.list_subscriptions,
            subscribe_fn=srv.event_bus.subscribe,
            unsubscribe_fn=srv.event_bus.unsubscribe,
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

    def _request(self, method: str, base_url: str, path: str, payload: dict | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        data = None
        final_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            final_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{base_url}{path}", data=data, headers=final_headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_event_subscription_crud_http_roundtrip(self) -> None:
        base_url = self._start_server()
        headers = {"X-Bridge-Agent": "user"}

        status_post, body_post = self._request(
            "POST",
            base_url,
            "/events/subscribe",
            {"event_type": "task.created", "webhook_url": "http://127.0.0.1:65535/slice68", "label": "slice68"},
            headers=headers,
        )
        self.assertEqual(status_post, 201)
        sub_id = body_post["subscription"]["id"]

        status_get, body_get = self._request("GET", base_url, "/events/subscriptions", headers=headers)
        self.assertEqual(status_get, 200)
        self.assertEqual(body_get["subscriptions"][0]["id"], sub_id)

        status_delete, body_delete = self._request("DELETE", base_url, f"/events/subscriptions/{sub_id}", headers=headers)
        self.assertEqual(status_delete, 200)
        self.assertEqual(body_delete["deleted"], sub_id)


if __name__ == "__main__":
    unittest.main()
