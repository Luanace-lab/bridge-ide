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


class TestAutomationWriteRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.state: dict[str, dict] = {
            "auto-1": {
                "id": "auto-1",
                "name": "One",
                "created_by": "backend",
                "active": True,
                "paused_until": None,
                "trigger": {"type": "event", "event_type": "task.created"},
                "action": {"type": "send_message", "to": "user", "content": "hi"},
                "options": {},
            }
        }

        def add_automation(data: dict) -> tuple[dict | None, str | None]:
            auto_id = str(data.get("id", "auto-2"))
            if auto_id in self.state:
                return None, "duplicate"
            automation = {
                "id": auto_id,
                "name": data["name"],
                "created_by": data["created_by"],
                "active": data.get("active", True),
                "paused_until": data.get("paused_until"),
                "trigger": data["trigger"],
                "action": data["action"],
                "options": data.get("options", {}),
            }
            self.state[auto_id] = automation
            return automation, None

        class _Scheduler:
            def __init__(self) -> None:
                self._action_callback = lambda auto: {"ok": True, "id": auto["id"]}
                self.updates: list[tuple[str, str, str | None]] = []

            def _update_after_run(self, auto_id: str, status: str, error: str | None = None) -> None:
                self.updates.append((auto_id, status, error))

        self.scheduler = _Scheduler()

        routes_mod.init(
            get_all_automations_fn=lambda: list(self.state.values()),
            get_automation_fn=lambda auto_id: self.state.get(auto_id),
            get_execution_history_fn=lambda auto_id, limit: [],
            get_execution_by_id_fn=lambda exec_id: None,
            add_automation_fn=add_automation,
            update_automation_fn=lambda auto_id, updates: self.state[auto_id] | updates if auto_id in self.state else None,
            delete_automation_fn=lambda auto_id: self.state.pop(auto_id, None) is not None,
            set_automation_active_fn=lambda auto_id, active: (self.state[auto_id].update({"active": active}) or self.state[auto_id]) if auto_id in self.state else None,
            set_automation_pause_fn=lambda auto_id, paused_until: (self.state[auto_id].update({"paused_until": paused_until}) or self.state[auto_id]) if auto_id in self.state else None,
            check_hierarchy_permission_fn=lambda creator, target: creator == "manager" and target == "worker",
            ws_broadcast_fn=lambda event, payload: None,
            get_scheduler_fn=lambda: self.scheduler,
            dispatch_webhook_fn=lambda auto_id, payload: {"ok": True, "automation_id": auto_id, "payload": payload},
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

    def _request(self, base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_automation_write_routes_http(self) -> None:
        base_url = self._start_server()

        status, body = self._request(base_url, "POST", "/automations", {
            "name": "Two",
            "created_by": "backend",
            "trigger": {"type": "event", "event_type": "task.created"},
            "action": {"type": "send_message", "to": "user", "content": "hi"},
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["automation"]["name"], "Two")

        status, body = self._request(base_url, "PATCH", "/automations/auto-1/active", {"active": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["automation"]["active"])

        status, body = self._request(base_url, "PATCH", "/automations/auto-1/pause", {"paused_until": "2099-01-01T00:00:00Z"})
        self.assertEqual(status, 200)
        self.assertEqual(body["automation"]["paused_until"], "2099-01-01T00:00:00Z")

        status, body = self._request(base_url, "PUT", "/automations/auto-1", {
            "name": "Updated",
            "action": {"type": "send_message", "to": "user", "content": "changed"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["automation"]["name"], "Updated")

        status, body = self._request(base_url, "DELETE", "/automations/auto-1")
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])

    def test_automation_run_and_webhook_http(self) -> None:
        base_url = self._start_server()

        status, body = self._request(base_url, "POST", "/automations/auto-1/run")
        self.assertEqual(status, 200)
        self.assertEqual(body["automation_id"], "auto-1")

        status, body = self._request(base_url, "POST", "/automations/auto-1/webhook", {"hello": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["automation_id"], "auto-1")


if __name__ == "__main__":
    unittest.main()
