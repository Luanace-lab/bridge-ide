from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.automation_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, body: dict | None = None, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestAutomationWriteRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
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
        self.events: list[tuple[str, dict]] = []

        def add_automation(data: dict) -> tuple[dict | None, str | None]:
            auto_id = str(data.get("id", f"auto-{len(self.state) + 1}"))
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

        def update_automation(auto_id: str, updates: dict) -> dict | None:
            current = self.state.get(auto_id)
            if current is None:
                return None
            current.update(updates)
            return current

        def delete_automation(auto_id: str) -> bool:
            return self.state.pop(auto_id, None) is not None

        def set_automation_active(auto_id: str, active: bool) -> dict | None:
            current = self.state.get(auto_id)
            if current is None:
                return None
            current["active"] = active
            return current

        def set_automation_pause(auto_id: str, paused_until: str | None) -> dict | None:
            current = self.state.get(auto_id)
            if current is None:
                return None
            current["paused_until"] = paused_until
            return current

        class _Scheduler:
            def __init__(self) -> None:
                self._action_callback = lambda auto: {"ok": True, "echo": auto["id"]}
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
            update_automation_fn=update_automation,
            delete_automation_fn=delete_automation,
            set_automation_active_fn=set_automation_active,
            set_automation_pause_fn=set_automation_pause,
            check_hierarchy_permission_fn=lambda creator, target: creator == "manager" and target == "worker",
            ws_broadcast_fn=lambda event, payload: self.events.append((event, payload)),
            get_scheduler_fn=lambda: self.scheduler,
            dispatch_webhook_fn=lambda auto_id, payload: {"ok": True, "automation_id": auto_id, "payload": payload},
        )

    def test_create_route_creates_automation(self) -> None:
        handler = _DummyHandler({
            "name": "Auto Two",
            "created_by": "backend",
            "trigger": {"type": "event", "event_type": "task.created"},
            "action": {"type": "send_message", "to": "user", "content": "ok"},
        })
        self.assertTrue(routes_mod.handle_post(handler, "/automations"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertIn("automation_created", [event for event, _ in self.events])

    def test_create_route_rejects_hierarchy_violation(self) -> None:
        handler = _DummyHandler({
            "name": "Auto Two",
            "created_by": "backend",
            "trigger": {"type": "event", "event_type": "task.created"},
            "action": {"type": "create_task", "assigned_to": "worker"},
        })
        self.assertTrue(routes_mod.handle_post(handler, "/automations"))
        self.assertEqual(handler.responses[0][0], 403)

    def test_patch_active_route_updates_state(self) -> None:
        handler = _DummyHandler({"active": False})
        self.assertTrue(routes_mod.handle_patch(handler, "/automations/auto-1/active"))
        self.assertEqual(handler.responses[0][1]["automation"]["active"], False)

    def test_patch_pause_route_updates_state(self) -> None:
        handler = _DummyHandler({"paused_until": "2099-01-01T00:00:00Z"})
        self.assertTrue(routes_mod.handle_patch(handler, "/automations/auto-1/pause"))
        self.assertEqual(handler.responses[0][1]["automation"]["paused_until"], "2099-01-01T00:00:00Z")

    def test_put_route_updates_automation(self) -> None:
        handler = _DummyHandler({
            "name": "Updated",
            "action": {"type": "send_message", "to": "user", "content": "changed"},
        })
        self.assertTrue(routes_mod.handle_put(handler, "/automations/auto-1"))
        self.assertEqual(handler.responses[0][1]["automation"]["name"], "Updated")

    def test_delete_route_respects_creator(self) -> None:
        handler = _DummyHandler(headers={"X-Bridge-Agent": "backend"})
        self.assertTrue(routes_mod.handle_delete(handler, "/automations/auto-1"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertNotIn("auto-1", self.state)

    def test_run_route_triggers_scheduler_callback(self) -> None:
        handler = _DummyHandler()
        routes_mod.handle_run(handler, "auto-1")
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(self.scheduler.updates[0][:2], ("auto-1", "success"))

    def test_webhook_route_requires_object_payload(self) -> None:
        handler = _DummyHandler(body=["bad"])
        handler.headers["Content-Length"] = "2"
        routes_mod.handle_webhook(handler, "auto-1")
        self.assertEqual(handler.responses[0][0], 400)


if __name__ == "__main__":
    unittest.main()
