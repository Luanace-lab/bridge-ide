from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.automation_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAutomationRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
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

    def test_list_automations_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/automations"))
        self.assertEqual(handler.responses[0][1]["count"], 1)

    def test_single_automation_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/automations/auto-1"))
        self.assertEqual(handler.responses[0][1]["id"], "auto-1")

    def test_history_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/automations/auto-1/history", {"limit": ["1"]}))
        self.assertEqual(handler.responses[0][1]["history"][0]["exec_id"], "exec-1")

    def test_execution_detail_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/automations/auto-1/history/exec-1"))
        self.assertEqual(handler.responses[0][1]["exec_id"], "exec-1")

    def test_missing_execution_returns_404(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/automations/auto-1/history/missing"))
        self.assertEqual(handler.responses[0][0], 404)


if __name__ == "__main__":
    unittest.main()
