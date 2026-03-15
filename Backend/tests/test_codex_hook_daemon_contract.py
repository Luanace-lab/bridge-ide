from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.codex_hook as hook


class TestCodexHookDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        hook._CODEX_HOOK_COOLDOWN.clear()
        self.team_config = {
            "agents": [
                {"id": "codex", "engine": "codex", "active": True},
                {"id": "claude", "engine": "claude", "active": True},
            ]
        }
        self.messages = []
        self.tasks = {}
        self.cursors = {"codex": 0}
        self.shutdown_pending = False
        self.shutdown_active = False
        hook.init(
            graceful_shutdown_pending=lambda: self.shutdown_pending,
            system_shutdown_active=lambda: self.shutdown_active,
            team_config_getter=lambda: self.team_config,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            msg_lock=DummyLock(),
            cursors=self.cursors,
            messages=self.messages,
            task_lock=DummyLock(),
            tasks=self.tasks,
        )

    def test_tick_skips_when_shutdown_pending(self) -> None:
        self.shutdown_pending = True
        self.assertEqual(hook._codex_hook_tick(), [])

    def test_tick_skips_when_system_shutdown_active(self) -> None:
        self.shutdown_active = True
        self.assertEqual(hook._codex_hook_tick(), [])

    def test_tick_injects_when_codex_has_unread_message_and_is_not_busy(self) -> None:
        self.messages = [{"to": "codex", "from": "user", "content": "ping"}]
        hook.init(
            graceful_shutdown_pending=lambda: self.shutdown_pending,
            system_shutdown_active=lambda: self.shutdown_active,
            team_config_getter=lambda: self.team_config,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            msg_lock=DummyLock(),
            cursors=self.cursors,
            messages=self.messages,
            task_lock=DummyLock(),
            tasks=self.tasks,
        )

        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)

            class Result:
                returncode = 0
                stdout = "ready"

            if cmd[:3] == ["tmux", "capture-pane", "-t"]:
                return Result()
            return Result()

        with patch("daemons.codex_hook.subprocess.run", side_effect=fake_run):
            injected = hook._codex_hook_tick()

        self.assertEqual(injected, ["codex"])
        self.assertTrue(any(cmd[:5] == ["tmux", "send-keys", "-t", "acw_codex", "-l"] for cmd in calls))

    def test_tick_respects_cooldown(self) -> None:
        hook._CODEX_HOOK_COOLDOWN["codex"] = time.time()
        self.messages = [{"to": "codex", "from": "user", "content": "ping"}]
        hook.init(
            graceful_shutdown_pending=lambda: self.shutdown_pending,
            system_shutdown_active=lambda: self.shutdown_active,
            team_config_getter=lambda: self.team_config,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            msg_lock=DummyLock(),
            cursors=self.cursors,
            messages=self.messages,
            task_lock=DummyLock(),
            tasks=self.tasks,
        )

        with patch("daemons.codex_hook.subprocess.run") as run_mock:
            injected = hook._codex_hook_tick()

        self.assertEqual(injected, [])
        self.assertFalse(run_mock.called)

    def test_tick_skips_busy_agent(self) -> None:
        self.tasks = {"t1": {"state": "created", "assigned_to": "codex"}}
        hook.init(
            graceful_shutdown_pending=lambda: self.shutdown_pending,
            system_shutdown_active=lambda: self.shutdown_active,
            team_config_getter=lambda: self.team_config,
            tmux_session_for=lambda agent_id: f"acw_{agent_id}",
            msg_lock=DummyLock(),
            cursors=self.cursors,
            messages=self.messages,
            task_lock=DummyLock(),
            tasks=self.tasks,
        )

        def fake_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = "thinking hard"
            return Result()

        with patch("daemons.codex_hook.subprocess.run", side_effect=fake_run) as run_mock:
            injected = hook._codex_hook_tick()

        self.assertEqual(injected, [])
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertFalse(any(cmd[:5] == ["tmux", "send-keys", "-t", "acw_codex", "-l"] for cmd in calls))


class DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
