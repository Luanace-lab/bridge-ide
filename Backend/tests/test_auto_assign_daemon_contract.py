from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.auto_assign as aa


class TestAutoAssignDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str, dict | None]] = []
        self.persist_calls = 0
        self.graceful_pending = False
        self.system_shutdown_active = False
        self.live_agents = {"alpha", "beta"}
        self.registered_agents = {
            "alpha": {"role": "backend engineer", "last_heartbeat": 1},
            "beta": {"role": "marketing writer", "last_heartbeat": 1},
        }
        self.agent_states: dict[str, dict[str, object]] = {}
        self.agent_activities: dict[str, dict[str, object]] = {}
        self.tasks: dict[str, dict[str, object]] = {}
        aa.init(
            graceful_shutdown_pending=lambda: self.graceful_pending,
            system_shutdown_active=lambda: self.system_shutdown_active,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=self._agent_is_live,
            load_agent_state=self._load_agent_state,
            agent_activities=self.agent_activities,
            task_lock=threading.Lock(),
            tasks=self.tasks,
            persist_tasks=self._persist_tasks,
            append_message=self._append_message,
        )

    def _agent_is_live(self, agent_id: str, *, stale_seconds: float, reg: dict) -> bool:
        return agent_id in self.live_agents

    def _load_agent_state(self, agent_id: str) -> dict[str, object]:
        return dict(self.agent_states.get(agent_id, {}))

    def _persist_tasks(self) -> None:
        self.persist_calls += 1

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
            "state": "created",
            "assigned_to": "",
            "description": "backend runtime fix",
            "labels": ["backend"],
        }

        assigned = aa._auto_assign_tick()

        self.assertEqual(assigned, [])
        self.assertEqual(self.persist_calls, 0)
        self.assertEqual(self.messages, [])

    def test_tick_assigns_matching_task_to_idle_agent(self) -> None:
        self.tasks["t1"] = {
            "task_id": "t1",
            "state": "created",
            "assigned_to": "",
            "title": "Fix runtime regression",
            "description": "Investigate backend runtime overlay issue.",
            "labels": ["backend", "runtime"],
        }

        assigned = aa._auto_assign_tick()

        self.assertEqual(assigned, ["t1"])
        self.assertEqual(self.tasks["t1"]["assigned_to"], "alpha")
        self.assertEqual(self.persist_calls, 1)
        self.assertEqual(len(self.messages), 1)
        sender, target, content, meta = self.messages[0]
        self.assertEqual((sender, target), ("system", "alpha"))
        self.assertIn("[AUTO-ASSIGNED]", content)
        self.assertIn("Fix runtime regression", content)
        self.assertEqual(meta, {"type": "auto_assign", "task_id": "t1"})

    def test_tick_skips_recently_active_agent(self) -> None:
        self.agent_activities["alpha"] = {
            "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        }
        self.tasks["t1"] = {
            "task_id": "t1",
            "state": "created",
            "assigned_to": "",
            "title": "Fix runtime regression",
            "description": "Investigate backend runtime overlay issue.",
            "labels": ["backend"],
        }

        assigned = aa._auto_assign_tick()

        self.assertEqual(assigned, [])
        self.assertEqual(self.tasks["t1"]["assigned_to"], "")
        self.assertEqual(self.persist_calls, 0)
        self.assertEqual(self.messages, [])

    def test_tick_assigns_at_most_one_task_per_idle_agent_per_pass(self) -> None:
        self.live_agents = {"alpha"}
        self.tasks["t1"] = {
            "task_id": "t1",
            "state": "created",
            "assigned_to": "",
            "title": "First backend fix",
            "description": "Investigate backend runtime overlay issue.",
            "labels": ["backend"],
        }
        self.tasks["t2"] = {
            "task_id": "t2",
            "state": "created",
            "assigned_to": "",
            "title": "Second backend fix",
            "description": "Investigate backend health regression.",
            "labels": ["backend"],
        }

        assigned = aa._auto_assign_tick()

        self.assertEqual(assigned, ["t1"])
        self.assertEqual(self.tasks["t1"]["assigned_to"], "alpha")
        self.assertEqual(self.tasks["t2"]["assigned_to"], "")
        self.assertEqual(self.persist_calls, 1)

    def test_tick_skips_agents_not_in_auto_or_normal_mode(self) -> None:
        self.agent_states["alpha"] = {"mode": "standby"}
        self.tasks["t1"] = {
            "task_id": "t1",
            "state": "created",
            "assigned_to": "",
            "title": "Fix runtime regression",
            "description": "Investigate backend runtime overlay issue.",
            "labels": ["backend"],
        }

        assigned = aa._auto_assign_tick()

        self.assertEqual(assigned, [])
        self.assertEqual(self.tasks["t1"]["assigned_to"], "")
        self.assertEqual(self.persist_calls, 0)
        self.assertEqual(self.messages, [])
