from __future__ import annotations

import os
import sys
import threading
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.health_monitor as hm


class TestHealthMonitorDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.broadcasts: list[tuple[str, dict]] = []
        self.supervisor_calls = 0
        self.health_payload: dict = {"components": {}}
        self.registered_agents = {
            "alpha": {"last_heartbeat": 1},
            "beta": {"last_heartbeat": 1},
            "ordo": {"last_heartbeat": 1},
        }
        hm._health_prev_status.clear()
        hm._health_last_alert.clear()
        hm._context_last_alert_level.clear()
        hm.init(
            compute_health=lambda: self.health_payload,
            supervisor_check_and_restart=self._supervisor_tick,
            append_message=self._append_message,
            ws_broadcast=self._ws_broadcast,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=self._agent_is_live,
        )

    def _append_message(self, sender: str, target: str, message: str) -> None:
        self.messages.append((sender, target, message))

    def _ws_broadcast(self, event_type: str, payload: dict) -> None:
        self.broadcasts.append((event_type, payload))

    def _supervisor_tick(self) -> None:
        self.supervisor_calls += 1

    def _agent_is_live(self, agent_id: str, *, stale_seconds: float, reg: dict) -> bool:
        return agent_id == "beta"

    def test_health_monitor_tick_alerts_and_calls_supervisor(self) -> None:
        self.health_payload = {
            "components": {
                "watcher": {"status": "warn", "pid": 123},
                "agents": {"alpha": {"status": "warn", "context_pct": 85}},
            }
        }

        hm._health_monitor_tick()

        self.assertEqual(self.supervisor_calls, 1)
        self.assertTrue(any(target == "ordo" and "[WARN] watcher" in msg for _, target, msg in self.messages))
        self.assertTrue(any(target == "alpha" and "[CONTEXT]" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "context_alert" for event, _ in self.broadcasts))

    def test_health_check_component_respects_cooldown_for_same_severity(self) -> None:
        now = 1000.0
        hm._health_check_component("watcher", "warn", {"status": "warn", "pid": 1}, now)
        first_count = len(self.messages)

        hm._health_check_component("watcher", "warn", {"status": "warn", "pid": 1}, now + 5)

        self.assertEqual(first_count, 1)
        self.assertEqual(len(self.messages), 1)

    def test_health_check_component_emits_recovery_and_clears_cooldown(self) -> None:
        hm._health_prev_status["watcher"] = "warn"
        hm._health_last_alert["watcher"] = 50.0

        hm._health_check_component("watcher", "ok", {"status": "ok"}, 100.0)

        self.assertNotIn("watcher", hm._health_last_alert)
        self.assertTrue(any("[RECOVERY] watcher wieder ok" in msg for _, _, msg in self.messages))

    def test_context_threshold_critical_notifies_other_live_agents(self) -> None:
        hm._check_context_thresholds("alpha", 95)

        self.assertEqual(hm._context_last_alert_level["alpha"], 95)
        self.assertTrue(any(target == "ordo" and "[CONTEXT] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(target == "alpha" and "[CONTEXT] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(target == "beta" and "[CONTEXT] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "context_alert" for event, _ in self.broadcasts))
