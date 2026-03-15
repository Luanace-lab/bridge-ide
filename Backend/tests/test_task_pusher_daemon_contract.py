from __future__ import annotations

import os
import sys
import threading
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.task_pusher as tp


class TestTaskPusherDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str, dict | None]] = []
        self.saved_states: list[tuple[str, dict[str, object]]] = []
        self.graceful_pending = False
        self.system_shutdown_active = False
        self.registered_agents = {
            "alpha": {"last_heartbeat": 1},
            "beta": {"last_heartbeat": 1},
        }
        self.tasks: dict[str, dict[str, object]] = {}
        self.agent_states: dict[str, dict[str, object]] = {}
        tp.init(
            graceful_shutdown_pending=lambda: self.graceful_pending,
            system_shutdown_active=lambda: self.system_shutdown_active,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=self._agent_is_live,
            task_lock=threading.Lock(),
            tasks=self.tasks,
            load_agent_state=self._load_agent_state,
            save_agent_state=self._save_agent_state,
            append_message=self._append_message,
        )

    def _agent_is_live(self, agent_id: str, *, stale_seconds: float, reg: dict) -> bool:
        return agent_id == "alpha"

    def _load_agent_state(self, agent_id: str) -> dict[str, object]:
        return dict(self.agent_states.get(agent_id, {}))

    def _save_agent_state(self, agent_id: str, updates: dict[str, object]) -> None:
        current = dict(self.agent_states.get(agent_id, {}))
        current.update(updates)
        self.agent_states[agent_id] = current
        self.saved_states.append((agent_id, dict(updates)))

    def _append_message(
        self,
        sender: str,
        target: str,
        content: str,
        meta: dict | None = None,
    ) -> None:
        self.messages.append((sender, target, content, meta))

    def test_tick_skips_when_graceful_shutdown_is_pending(self) -> None:
        self.graceful_pending = True
        self.tasks["t1"] = {
            "task_id": "t1",
            "assigned_to": "alpha",
            "state": "created",
        }

        pushed = tp._task_pusher_tick()

        self.assertEqual(pushed, [])
        self.assertEqual(self.messages, [])
        self.assertEqual(self.saved_states, [])

    def test_tick_skips_when_system_shutdown_is_active(self) -> None:
        self.system_shutdown_active = True
        self.tasks["t1"] = {
            "task_id": "t1",
            "assigned_to": "alpha",
            "state": "created",
        }

        pushed = tp._task_pusher_tick()

        self.assertEqual(pushed, [])
        self.assertEqual(self.messages, [])
        self.assertEqual(self.saved_states, [])

    def test_tick_pushes_created_task_only_to_live_assignee(self) -> None:
        self.tasks["t1"] = {
            "task_id": "t1",
            "assigned_to": "alpha",
            "state": "created",
            "title": "Fix runtime regression",
            "description": "Inspect and repair the runtime overlay restore path.",
            "created_by": "buddy",
        }
        self.tasks["t2"] = {
            "task_id": "t2",
            "assigned_to": "beta",
            "state": "created",
            "title": "Should stay quiet",
            "description": "Offline assignee must not receive a push.",
            "created_by": "buddy",
        }

        pushed = tp._task_pusher_tick()

        self.assertEqual(pushed, ["t1"])
        self.assertEqual(self.saved_states, [])
        self.assertEqual(len(self.messages), 1)
        sender, target, content, meta = self.messages[0]
        self.assertEqual(sender, "system")
        self.assertEqual(target, "alpha")
        self.assertIn("[AUTO-CLAIM REQUIRED]", content)
        self.assertIn("Fix runtime regression", content)
        self.assertEqual(meta, {"type": "auto_claim_push", "task_id": "t1"})

    def test_tick_escalates_standby_agent_before_pushing_task(self) -> None:
        self.agent_states["alpha"] = {"mode": "standby"}
        self.tasks["t1"] = {
            "task_id": "t1",
            "assigned_to": "alpha",
            "state": "created",
            "title": "Take ownership",
            "description": "Claim and process the task.",
            "created_by": "lead",
        }

        pushed = tp._task_pusher_tick()

        self.assertEqual(pushed, ["t1"])
        self.assertEqual(self.saved_states, [("alpha", {"mode": "normal"})])
        self.assertEqual(self.agent_states["alpha"]["mode"], "normal")
        self.assertEqual(len(self.messages), 2)
        first_sender, first_target, first_content, first_meta = self.messages[0]
        self.assertEqual((first_sender, first_target), ("system", "alpha"))
        self.assertIn("[MODE CHANGE]", first_content)
        self.assertEqual(first_meta, {"type": "mode_change", "mode": "normal"})
        second_sender, second_target, second_content, second_meta = self.messages[1]
        self.assertEqual((second_sender, second_target), ("system", "alpha"))
        self.assertIn("[AUTO-CLAIM REQUIRED]", second_content)
        self.assertEqual(second_meta, {"type": "auto_claim_push", "task_id": "t1"})
