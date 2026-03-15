from __future__ import annotations

import hashlib
import os
import sys
import threading
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.cli_monitor as mon


class TestCliMonitorDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.broadcasts: list[tuple[str, dict]] = []
        self.registered_agents = {"alpha": {"last_heartbeat": 0}}
        self.agent_rate_limited: dict[str, dict] = {}
        mon._AGENT_OUTPUT_HASHES.clear()
        mon._CLI_STUCK_ALERTED.clear()
        mon._CLI_AUTH_ALERTED.clear()
        mon.init(
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_rate_limited=self.agent_rate_limited,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            check_tmux_session=lambda agent_id: True,
            append_message=self._append_message,
            ws_broadcast=self._ws_broadcast,
            rate_limit_patterns=("usage limit", "rate limit"),
            is_agent_at_prompt=lambda agent_id: False,
        )

    def _append_message(self, sender: str, target: str, message: str) -> None:
        self.messages.append((sender, target, message))

    def _ws_broadcast(self, event_type: str, payload: dict) -> None:
        self.broadcasts.append((event_type, payload))

    def test_tick_resets_hash_on_recent_heartbeat(self) -> None:
        self.registered_agents["alpha"]["last_heartbeat"] = 950.0
        with patch("daemons.cli_monitor.time.time", return_value=1000.0):
            mon._cli_output_monitor_tick()
        self.assertEqual(mon._AGENT_OUTPUT_HASHES["alpha"]["hash"], "")
        self.assertEqual(mon._AGENT_OUTPUT_HASHES["alpha"]["since"], 1000.0)
        self.assertFalse(self.messages)

    def test_tick_detects_auth_prompt_and_broadcasts_once(self) -> None:
        output = "Paste code here to sign in"
        mon._AGENT_OUTPUT_HASHES["alpha"] = {
            "hash": hashlib.sha256(output.encode()).hexdigest(),
            "since": 0.0,
        }
        with patch("daemons.cli_monitor.time.time", return_value=1000.0):
            with patch("daemons.cli_monitor.subprocess.run") as run_mock:
                run_mock.return_value.stdout = output
                mon._cli_output_monitor_tick()
        self.assertTrue(any(target == "user" and "[AUTH-FAILURE] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "agent_auth_failure" for event, _ in self.broadcasts))
        self.assertIn("alpha", mon._CLI_AUTH_ALERTED)

    def test_tick_marks_rate_limited_and_broadcasts(self) -> None:
        output = "Usage limit exceeded"
        mon._AGENT_OUTPUT_HASHES["alpha"] = {
            "hash": hashlib.sha256(output.encode()).hexdigest(),
            "since": 0.0,
        }
        with patch("daemons.cli_monitor.time.time", return_value=1000.0):
            with patch("daemons.cli_monitor.subprocess.run") as run_mock:
                run_mock.return_value.stdout = output
                mon._cli_output_monitor_tick()
        self.assertIn("alpha", self.agent_rate_limited)
        self.assertTrue(any(target == "user" and "[RATE-LIMITED] alpha" in msg for _, target, msg in self.messages))
        self.assertTrue(any(event == "agent_rate_limited" for event, _ in self.broadcasts))

    def test_tick_sends_ctrl_c_on_kill_threshold(self) -> None:
        output = "unchanged output"
        mon._AGENT_OUTPUT_HASHES["alpha"] = {
            "hash": hashlib.sha256(output.encode()).hexdigest(),
            "since": 0.0,
        }

        def fake_run(cmd, *args, **kwargs):
            class Result:
                stdout = output
            if cmd[:3] == ["tmux", "capture-pane", "-t"]:
                return Result()
            return Result()

        with patch("daemons.cli_monitor.time.time", return_value=1000.0):
            with patch("daemons.cli_monitor.subprocess.run", side_effect=fake_run) as run_mock:
                mon._cli_output_monitor_tick()
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertTrue(any(cmd[:4] == ["tmux", "send-keys", "-t", "acw_alpha"] and "C-c" in cmd for cmd in calls))
        self.assertTrue(any(target == "user" and "[AUTO-KILL] alpha" in msg for _, target, msg in self.messages))
        self.assertEqual(mon._AGENT_OUTPUT_HASHES["alpha"]["hash"], "")
