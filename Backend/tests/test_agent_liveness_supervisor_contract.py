from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import agent_liveness_supervisor as sup  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.runtime_agent_ids = ["codex", "claude"]
        self.agent_payloads: dict[str, dict] = {}
        self.activity_payloads: dict[str, dict] = {}
        self.start_calls: list[str] = []

    def get_runtime_agent_ids(self) -> list[str]:
        return list(self.runtime_agent_ids)

    def get_agent(self, agent_id: str) -> dict:
        return dict(self.agent_payloads[agent_id])

    def get_activity(self, agent_id: str) -> dict:
        return dict(self.activity_payloads.get(agent_id, {"activities": []}))

    def start_or_nudge(self, agent_id: str) -> dict:
        self.start_calls.append(agent_id)
        return {"ok": True, "agent_id": agent_id, "status": "nudged"}


class TestActivityAge(unittest.TestCase):
    def test_activity_age_uses_newest_timestamp(self) -> None:
        payload = {
            "activities": [
                {"timestamp": "2026-03-12T09:00:00+00:00"},
                {"timestamp": "2026-03-12T09:00:30+00:00"},
            ]
        }
        newest = sup._parse_timestamp("2026-03-12T09:00:30+00:00")
        self.assertIsNotNone(newest)
        age = sup._activity_age_seconds(payload, now_ts=float(newest.timestamp() + 30.0))
        self.assertEqual(age, 30.0)

    def test_activity_age_returns_none_for_missing_entries(self) -> None:
        self.assertIsNone(sup._activity_age_seconds({"activities": []}, now_ts=10.0))


class TestDecisionLogic(unittest.TestCase):
    def _snapshot(self, **overrides: object) -> sup.AgentSnapshot:
        baseline = {
            "agent_id": "codex",
            "status": "waiting",
            "online": True,
            "tmux_alive": True,
            "last_heartbeat_age": 30.0,
            "last_activity_age": None,
        }
        baseline.update(overrides)
        return sup.AgentSnapshot(**baseline)

    def test_healthy_agent_stays_healthy(self) -> None:
        action = sup.decide_agent_action(
            self._snapshot(),
            stale_seconds=120.0,
            cooldown_seconds=300.0,
            now_ts=1000.0,
            last_action_at=None,
        )
        self.assertEqual(action, "healthy")

    def test_stale_heartbeat_triggers_start_or_nudge(self) -> None:
        action = sup.decide_agent_action(
            self._snapshot(last_heartbeat_age=121.0),
            stale_seconds=120.0,
            cooldown_seconds=300.0,
            now_ts=1000.0,
            last_action_at=None,
        )
        self.assertEqual(action, "start_or_nudge")

    def test_disconnected_agent_triggers_start_or_nudge(self) -> None:
        action = sup.decide_agent_action(
            self._snapshot(status="disconnected", tmux_alive=False),
            stale_seconds=120.0,
            cooldown_seconds=300.0,
            now_ts=1000.0,
            last_action_at=None,
        )
        self.assertEqual(action, "start_or_nudge")

    def test_cooldown_prevents_repeat_action(self) -> None:
        action = sup.decide_agent_action(
            self._snapshot(status="disconnected", tmux_alive=False),
            stale_seconds=120.0,
            cooldown_seconds=300.0,
            now_ts=1000.0,
            last_action_at=900.0,
        )
        self.assertEqual(action, "cooldown")


class TestSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.client.agent_payloads["codex"] = {
            "status": "waiting",
            "online": True,
            "tmux_alive": True,
            "last_heartbeat_age": 45.0,
        }
        self.client.agent_payloads["claude"] = {
            "status": "disconnected",
            "online": False,
            "tmux_alive": False,
            "last_heartbeat_age": 305.0,
        }

    def test_run_once_only_calls_start_for_unhealthy_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            supervisor = sup.AgentLivenessSupervisor(
                self.client,
                stale_seconds=120.0,
                cooldown_seconds=300.0,
                log_file=Path(tmpdir) / "supervisor.log",
            )
            results = supervisor.run_once(["codex", "claude"], now_ts=1000.0)
        self.assertEqual(len(results), 2)
        self.assertEqual(self.client.start_calls, ["claude"])
        actions = {entry["agent_id"]: entry["action"] for entry in results}
        self.assertEqual(actions["codex"], "healthy")
        self.assertEqual(actions["claude"], "start_or_nudge")

    def test_run_once_records_cooldown_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            supervisor = sup.AgentLivenessSupervisor(
                self.client,
                stale_seconds=120.0,
                cooldown_seconds=300.0,
                log_file=Path(tmpdir) / "supervisor.log",
            )
            supervisor.run_once(["claude"], now_ts=1000.0)
            results = supervisor.run_once(["claude"], now_ts=1100.0)
        self.assertEqual(self.client.start_calls, ["claude"])
        self.assertEqual(results[0]["action"], "cooldown")


class TestHelpers(unittest.TestCase):
    def test_resolve_agent_ids_prefers_explicit_args(self) -> None:
        client = FakeClient()
        resolved = sup._resolve_agent_ids(client, [" codex ", "", "claude"])
        self.assertEqual(resolved, ["codex", "claude"])

    def test_resolve_agent_ids_falls_back_to_runtime(self) -> None:
        client = FakeClient()
        self.assertEqual(sup._resolve_agent_ids(client, []), ["codex", "claude"])

    def test_acquire_pid_lock_reuses_stale_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_file = Path(tmpdir) / "guard.pid"
            pid_file.write_text("999999", encoding="utf-8")
            with mock.patch.object(sup, "_pid_is_alive", return_value=False):
                path, acquired = sup.acquire_pid_lock(pid_file)
            self.assertTrue(acquired)
            self.assertEqual(path, pid_file)
            self.assertEqual(pid_file.read_text(encoding="utf-8").strip(), str(os.getpid()))

    def test_acquire_pid_lock_blocks_live_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_file = Path(tmpdir) / "guard.pid"
            pid_file.write_text("12345", encoding="utf-8")
            with mock.patch.object(sup, "_pid_is_alive", return_value=True):
                _path, acquired = sup.acquire_pid_lock(pid_file)
            self.assertFalse(acquired)


if __name__ == "__main__":
    unittest.main()
