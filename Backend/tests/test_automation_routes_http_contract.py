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

import handlers.automation_routes as routes_mod  # noqa: E402
import server as srv  # noqa: E402


class TestAutomationRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.init(
            get_all_automations_fn=lambda: [{"id": "auto-1", "name": "One"}],
            get_automation_fn=lambda auto_id: {"id": auto_id, "name": "One"} if auto_id == "auto-1" else None,
            get_execution_history_fn=lambda auto_id, limit: [{"exec_id": "exec-1", "automation_id": auto_id}][:limit],
            get_execution_by_id_fn=lambda exec_id: {"exec_id": exec_id, "status": "success"} if exec_id == "exec-1" else None,
            add_automation_fn=lambda data: (data, None),
            update_automation_fn=lambda auto_id, data: {"id": auto_id, **data},
            delete_automation_fn=lambda auto_id: True,
            set_automation_active_fn=lambda auto_id, active: {"id": auto_id, "active": active},
            set_automation_pause_fn=lambda auto_id, paused_until: {"id": auto_id, "paused_until": paused_until},
            check_hierarchy_permission_fn=lambda creator, target: True,
            ws_broadcast_fn=lambda event, payload: None,
            get_scheduler_fn=lambda: None,
            dispatch_webhook_fn=lambda auto_id, payload: {"ok": True, "automation_id": auto_id},
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            get_all_automations_fn=lambda: __import__("automation_engine").get_all_automations(),
            get_automation_fn=lambda auto_id: __import__("automation_engine").get_automation(auto_id),
            get_execution_history_fn=lambda auto_id, limit: __import__("automation_engine").get_execution_history(auto_id, limit),
            get_execution_by_id_fn=lambda exec_id: __import__("automation_engine").get_execution_by_id(exec_id),
            add_automation_fn=lambda data: __import__("automation_engine").add_automation(data),
            update_automation_fn=lambda auto_id, data: __import__("automation_engine").update_automation(auto_id, data),
            delete_automation_fn=lambda auto_id: __import__("automation_engine").delete_automation(auto_id),
            set_automation_active_fn=lambda auto_id, active: __import__("automation_engine").set_automation_active(auto_id, active),
            set_automation_pause_fn=lambda auto_id, paused_until: __import__("automation_engine").set_automation_pause(auto_id, paused_until),
            check_hierarchy_permission_fn=srv._check_hierarchy_permission,
            ws_broadcast_fn=srv.ws_broadcast,
            get_scheduler_fn=lambda: __import__("automation_engine").get_scheduler(),
            dispatch_webhook_fn=lambda auto_id, payload: __import__("automation_engine").dispatch_webhook(auto_id, payload),
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

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_automation_routes_http(self) -> None:
        base_url = self._start_server()

        status, body = self._get(base_url, "/automations")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)

        status, body = self._get(base_url, "/automations/auto-1")
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], "auto-1")

        status, body = self._get(base_url, "/automations/auto-1/history?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["history"][0]["exec_id"], "exec-1")

        status, body = self._get(base_url, "/automations/auto-1/history/exec-1")
        self.assertEqual(status, 200)
        self.assertEqual(body["exec_id"], "exec-1")


if __name__ == "__main__":
    unittest.main()
