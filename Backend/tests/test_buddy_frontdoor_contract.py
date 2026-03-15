from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.onboarding_routes as onboarding_mod  # noqa: E402


class TestBuddyFrontdoorContract(unittest.TestCase):
    def setUp(self):
        self._orig_messages = list(srv.MESSAGES)
        self._orig_is_alive = srv.is_session_alive
        self._orig_autostart = srv._auto_start_buddy_agent
        self._orig_append = srv.append_message

    def tearDown(self):
        srv.MESSAGES[:] = self._orig_messages
        srv.is_session_alive = self._orig_is_alive
        srv._auto_start_buddy_agent = self._orig_autostart
        srv.append_message = self._orig_append

    def test_frontdoor_starts_buddy_and_queues_system_ping(self):
        state = {"alive": False, "append_calls": []}

        def fake_is_alive(agent_id: str) -> bool:
            self.assertEqual(agent_id, "buddy")
            return state["alive"]

        def fake_autostart() -> bool:
            state["alive"] = True
            return True

        def fake_append(sender: str, recipient: str, content: str, meta=None, **kwargs):
            state["append_calls"].append({
                "from": sender,
                "to": recipient,
                "content": content,
                "meta": meta or {},
            })
            return {"id": 41, "from": sender, "to": recipient, "content": content, "meta": meta or {}}

        srv.is_session_alive = fake_is_alive
        srv._auto_start_buddy_agent = fake_autostart
        srv.append_message = fake_append

        result = srv._ensure_buddy_frontdoor("susi")

        self.assertEqual(result["status"], "started")
        self.assertTrue(result["alive_after"])
        self.assertTrue(result["started"])
        self.assertTrue(result["queued"])
        self.assertEqual(len(state["append_calls"]), 1)
        self.assertEqual(state["append_calls"][0]["from"], "system")
        self.assertEqual(state["append_calls"][0]["to"], "buddy")
        self.assertEqual(state["append_calls"][0]["meta"]["type"], "buddy_frontdoor")
        self.assertEqual(state["append_calls"][0]["meta"]["user_id"], "susi")

    def test_frontdoor_dedupes_recent_ping_for_same_user(self):
        now = time.time()
        srv.MESSAGES[:] = [{
            "id": 7,
            "from": "system",
            "to": "buddy",
            "content": "[BUDDY_FRONTDOOR] Existing ping",
            "timestamp": srv.utc_now_iso(),
            "meta": {"type": "buddy_frontdoor", "user_id": "susi"},
        }]

        def fake_is_alive(agent_id: str) -> bool:
            self.assertEqual(agent_id, "buddy")
            return True

        def fail_append(*args, **kwargs):
            raise AssertionError("append_message must not be called for a recent duplicate frontdoor ping")

        srv.is_session_alive = fake_is_alive
        srv.append_message = fail_append

        result = srv._ensure_buddy_frontdoor("susi")

        self.assertEqual(result["status"], "already_running")
        self.assertTrue(result["alive_after"])
        self.assertFalse(result["queued"])
        self.assertTrue(result["deduped"])

    def test_server_exposes_onboarding_start_endpoint(self):
        self.assertIs(srv._handle_onboarding_post, onboarding_mod.handle_post)


if __name__ == "__main__":
    unittest.main()
