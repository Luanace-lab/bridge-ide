from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import automation_engine as ae


def _clear_state() -> None:
    with ae.AUTOMATION_LOCK:
        ae.AUTOMATIONS.clear()
    ae._PENDING_AUTOMATIONS.clear()
    ae._PENDING_RETRY_COUNT.clear()
    ae._scheduler = None


class TestAutomationContractUplift(unittest.TestCase):
    def setUp(self) -> None:
        _clear_state()

    def tearDown(self) -> None:
        _clear_state()

    def test_add_automation_normalizes_legacy_event_name(self) -> None:
        auto, _ = ae.add_automation({
            "name": "Bug Triage",
            "created_by": "backend",
            "trigger": {"type": "event", "event_type": "task_created"},
            "action": {"type": "send_message", "to": "user", "content": "triage"},
        })

        self.assertIsNotNone(auto)
        self.assertEqual(auto["trigger"]["event_type"], "task.created")

    @patch("automation_engine.log_execution")
    def test_dispatch_event_runs_matching_automation(self, _mock_log_execution) -> None:
        fired: list[str] = []

        def action_cb(auto: dict) -> dict:
            fired.append(auto["id"])
            return {"ok": True}

        ae._scheduler = ae.AutomationScheduler(action_callback=action_cb, check_interval=1)
        auto, _ = ae.add_automation({
            "name": "On Task Created",
            "created_by": "backend",
            "trigger": {"type": "event", "event_type": "task_created"},
            "action": {"type": "send_message", "to": "user", "content": "new task"},
        })

        results = ae.dispatch_event("task.created", {"agent_id": "backend"})

        self.assertEqual(fired, [auto["id"]])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["automation_id"], auto["id"])
        self.assertTrue(results[0]["ok"])

    def test_webhook_trigger_gets_deterministic_path(self) -> None:
        auto, _ = ae.add_automation({
            "name": "Inbound Webhook",
            "created_by": "backend",
            "trigger": {"type": "webhook"},
            "action": {"type": "send_message", "to": "user", "content": "hook"},
        })

        self.assertIsNotNone(auto)
        self.assertEqual(auto["trigger"]["webhook_path"], f"/automations/{auto['id']}/webhook")

    @patch("automation_engine.log_execution")
    def test_condition_trigger_task_overdue_fires(self, _mock_log_execution) -> None:
        fired: list[str] = []

        def action_cb(auto: dict) -> dict:
            fired.append(auto["id"])
            return {"ok": True}

        stale_task = {
            "task_id": "task-1",
            "state": "created",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
            "deadline": None,
            "assigned_to": "backend",
        }
        ae._scheduler = ae.AutomationScheduler(
            action_callback=action_cb,
            check_interval=1,
            condition_context_callback=lambda: {
                "agents": {},
                "tasks": [stale_task],
            },
        )

        auto, _ = ae.add_automation({
            "name": "Overdue Escalation",
            "created_by": "backend",
            "trigger": {"type": "condition", "condition": "task_overdue", "threshold_hours": 24},
            "action": {"type": "send_message", "to": "user", "content": "overdue"},
        })

        ae._scheduler._tick()

        self.assertEqual(fired, [auto["id"]])

    @patch("automation_engine._http_patch")
    def test_execute_action_supports_set_mode(self, mock_patch) -> None:
        mock_patch.return_value = {"ok": True}

        result = ae.execute_action({
            "id": "auto_mode",
            "created_by": "backend",
            "action": {"type": "set_mode", "agent_id": "kai", "mode": "auto"},
        })

        self.assertTrue(result["ok"])
        mock_patch.assert_called_once_with("/agents/kai/mode", {"mode": "auto"})

    @patch("automation_engine._http_webhook")
    def test_execute_action_supports_webhook(self, mock_webhook) -> None:
        mock_webhook.return_value = {"ok": True, "status": 200}

        result = ae.execute_action({
            "id": "auto_hook",
            "created_by": "backend",
            "action": {"type": "webhook", "url": "https://example.test/hook", "method": "POST", "body": "{\"hello\":true}"},
        })

        self.assertTrue(result["ok"])
        mock_webhook.assert_called_once_with(
            "https://example.test/hook",
            method="POST",
            body="{\"hello\":true}",
            headers=None,
        )

    @patch("automation_engine._action_send_message")
    @patch("automation_engine._action_set_mode")
    def test_execute_action_supports_chain(self, mock_set_mode, mock_send_message) -> None:
        mock_set_mode.return_value = {"ok": True}
        mock_send_message.return_value = {"ok": True}

        result = ae.execute_action({
            "id": "auto_chain",
            "created_by": "backend",
            "action": {
                "type": "chain",
                "actions": [
                    {"type": "set_mode", "agent_id": "kai", "mode": "auto"},
                    {"type": "send_message", "to": "kai", "content": "work now"},
                ],
            },
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["executed"], 2)
        mock_set_mode.assert_called_once()
        mock_send_message.assert_called_once()

    @patch("automation_engine._http_post")
    def test_send_message_action_respects_explicit_sender(self, mock_post) -> None:
        mock_post.return_value = {"ok": True}

        result = ae.execute_action({
            "id": "auto_send",
            "created_by": "codex_3",
            "action": {
                "type": "send_message",
                "from": "system",
                "to": "codex_3",
                "content": "scheduled prompt",
            },
        })

        self.assertTrue(result["ok"])
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        self.assertEqual(payload["from"], "system")
        self.assertEqual(payload["meta"]["automation_created_by"], "codex_3")

    @patch("urllib.request.urlopen")
    @patch("automation_engine.build_bridge_auth_headers")
    def test_http_request_merges_bridge_auth_headers(self, mock_headers, mock_urlopen) -> None:
        mock_headers.return_value = {
            "Content-Type": "application/json",
            "X-Bridge-Agent": "automation_engine",
            "X-Bridge-Token": "user-token",
        }
        response = MagicMock()
        response.read.return_value = b'{"ok": true}'
        mock_urlopen.return_value.__enter__.return_value = response

        result = ae._http_request("POST", "/send", {"from": "system", "to": "codex", "content": "ok"})

        self.assertTrue(result["ok"])
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.headers.get("X-bridge-token"), "user-token")
        self.assertEqual(request.headers.get("X-bridge-agent"), "automation_engine")


if __name__ == "__main__":
    unittest.main()
