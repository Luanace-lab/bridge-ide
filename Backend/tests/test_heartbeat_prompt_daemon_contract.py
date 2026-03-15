from __future__ import annotations

import os
import sys
import threading
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.heartbeat_prompt as hb


class TestHeartbeatPromptDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str, dict | None]] = []
        self.graceful_shutdown = {"pending": False}
        self.system_status = {"shutdown_active": False}
        self.registered_agents = {
            "alpha": {"last_heartbeat": 1},
            "beta": {"last_heartbeat": 1},
        }
        hb.init(
            graceful_shutdown_lock=threading.Lock(),
            graceful_shutdown=self.graceful_shutdown,
            system_status=self.system_status,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=self._agent_is_live,
            append_message=self._append_message,
        )

    def _agent_is_live(self, agent_id: str, *, stale_seconds: float, reg: dict) -> bool:
        return agent_id == "alpha"

    def _append_message(self, sender: str, target: str, content: str, meta: dict | None = None) -> None:
        self.messages.append((sender, target, content, meta))

    def test_tick_skips_when_graceful_shutdown_pending(self) -> None:
        self.graceful_shutdown["pending"] = True
        sent = hb._heartbeat_prompt_tick()
        self.assertEqual(sent, [])
        self.assertEqual(self.messages, [])

    def test_tick_skips_when_system_shutdown_is_active(self) -> None:
        self.system_status["shutdown_active"] = True
        sent = hb._heartbeat_prompt_tick()
        self.assertEqual(sent, [])
        self.assertEqual(self.messages, [])

    def test_tick_sends_only_to_live_agents(self) -> None:
        sent = hb._heartbeat_prompt_tick()
        self.assertEqual(sent, ["alpha"])
        self.assertEqual(len(self.messages), 1)
        sender, target, content, meta = self.messages[0]
        self.assertEqual(sender, "system")
        self.assertEqual(target, "alpha")
        self.assertIn("[HEARTBEAT_CHECK]", content)
        self.assertIn("NUR an system", content)
        self.assertIn("NICHT an user", content)
        self.assertEqual(meta, {"type": "heartbeat_check"})
