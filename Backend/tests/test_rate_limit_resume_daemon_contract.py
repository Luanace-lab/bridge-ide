from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.rate_limit_resume as rl


class TestRateLimitResumeDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.broadcasts: list[tuple[str, dict]] = []
        self.restarts: list[str] = []
        self.registered_agents = {"alpha": {"last_heartbeat": 0}}
        self.agent_rate_limited = {
            "alpha": {"since": 100.0, "last_resume_attempt": 0.0, "resume_attempts": 0}
        }
        rl.init(
            agent_state_lock=threading.Lock(),
            agent_rate_limited=self.agent_rate_limited,
            registered_agents=self.registered_agents,
            agent_is_live=self._agent_is_live,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            check_tmux_session=self._check_tmux_session,
            start_agent_from_conf=self._start_agent_from_conf,
            append_message=self._append_message,
            ws_broadcast=self._ws_broadcast,
        )
        self._alive = False
        self._tmux_alive = True
        self._restart_success = True

    def _append_message(self, sender: str, target: str, message: str) -> None:
        self.messages.append((sender, target, message))

    def _ws_broadcast(self, event_type: str, payload: dict) -> None:
        self.broadcasts.append((event_type, payload))

    def _agent_is_live(self, agent_id: str, *, stale_seconds: float, reg: dict) -> bool:
        return self._alive

    def _check_tmux_session(self, agent_id: str) -> bool:
        return self._tmux_alive

    def _start_agent_from_conf(self, agent_id: str) -> bool:
        self.restarts.append(agent_id)
        return self._restart_success

    def test_tick_clears_rate_limit_on_fresh_heartbeat(self) -> None:
        self._alive = True

        with patch("daemons.rate_limit_resume.time.time", return_value=2000.0):
            rl._rate_limit_resume_tick()

        self.assertNotIn("alpha", self.agent_rate_limited)
        self.assertTrue(any(target == "user" and "[RATE-LIMIT CLEARED] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "agent_rate_limit_cleared" for event, _ in self.broadcasts))
        self.assertFalse(self.restarts)

    def test_tick_restarts_agent_when_tmux_session_is_gone(self) -> None:
        self._tmux_alive = False

        with patch("daemons.rate_limit_resume.time.time", return_value=2000.0):
            rl._rate_limit_resume_tick()

        self.assertEqual(self.restarts, ["alpha"])
        self.assertNotIn("alpha", self.agent_rate_limited)
        self.assertTrue(any(target == "user" and "[RATE-LIMIT RESUMED] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "agent_rate_limit_cleared" for event, _ in self.broadcasts))

    def test_tick_readds_rate_limit_when_restart_fails(self) -> None:
        self._tmux_alive = False
        self._restart_success = False

        with patch("daemons.rate_limit_resume.time.time", return_value=2000.0):
            rl._rate_limit_resume_tick()

        self.assertEqual(self.restarts, ["alpha"])
        self.assertIn("alpha", self.agent_rate_limited)
        self.assertEqual(self.agent_rate_limited["alpha"]["last_resume_attempt"], 2000.0)
        self.assertEqual(self.agent_rate_limited["alpha"]["resume_attempts"], 1)

    def test_tick_injects_resume_prompt_into_live_session(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            class Result:
                returncode = 0
            return Result()

        with patch("daemons.rate_limit_resume.time.time", return_value=2000.0):
            with patch("daemons.rate_limit_resume.subprocess.run", side_effect=fake_run):
                rl._rate_limit_resume_tick()

        self.assertEqual(self.agent_rate_limited["alpha"]["last_resume_attempt"], 2000.0)
        self.assertEqual(self.agent_rate_limited["alpha"]["resume_attempts"], 1)
        self.assertTrue(any(cmd[:4] == ["tmux", "send-keys", "-t", "acw_alpha"] for cmd in calls))

    def test_tick_respects_backoff_before_next_attempt(self) -> None:
        self.agent_rate_limited["alpha"]["last_resume_attempt"] = 1900.0
        self.agent_rate_limited["alpha"]["resume_attempts"] = 0

        with patch("daemons.rate_limit_resume.time.time", return_value=2000.0):
            with patch("daemons.rate_limit_resume.subprocess.run") as run_mock:
                rl._rate_limit_resume_tick()

        self.assertFalse(run_mock.called)
        self.assertFalse(self.restarts)
        self.assertEqual(self.agent_rate_limited["alpha"]["last_resume_attempt"], 1900.0)
        self.assertEqual(self.agent_rate_limited["alpha"]["resume_attempts"], 0)
