from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.restart_wake as restart_wake


class TestRestartWakeDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.team_config: dict | None = {"agents": []}
        self.agent_last_nudge: dict[str, float] = {}
        self.append_message = mock.Mock()
        self.ws_broadcast = mock.Mock()
        self.create_agent_session = mock.Mock(return_value=True)
        self.nudge_idle_agent = mock.Mock(return_value=True)

    def tearDown(self) -> None:
        import server as srv

        restart_wake.init(
            team_config_getter=lambda: srv.TEAM_CONFIG,
            team_config_lock_getter=lambda: srv.TEAM_CONFIG_LOCK,
            is_session_alive=lambda agent_id: srv.is_session_alive(agent_id),
            tmux_session_for=lambda agent_id: srv._tmux_session_for(agent_id),
            is_agent_at_prompt_inline=lambda agent_id: srv._is_agent_at_prompt_inline(agent_id),
            nudge_idle_agent=lambda agent_id, reason: srv._nudge_idle_agent(agent_id, reason),
            agent_last_nudge_getter=lambda: srv._AGENT_LAST_NUDGE,
            role_description_for=lambda agent_conf, fallback="": srv._role_description_for(agent_conf, fallback=fallback),
            team_members_for=lambda agent_id: srv._team_members_for(agent_id),
            create_agent_session=lambda **kwargs: srv.create_agent_session(**kwargs),
            port_getter=lambda: srv.PORT,
            append_message=lambda *args, **kwargs: srv.append_message(*args, **kwargs),
            ws_broadcast=lambda event_type, payload: srv.ws_broadcast(event_type, payload),
        )

    def _init(self, **overrides: object) -> None:
        cfg = {
            "team_config_getter": lambda: self.team_config,
            "team_config_lock_getter": lambda: threading.Lock(),
            "is_session_alive": lambda _agent_id: False,
            "tmux_session_for": lambda agent_id: f"acw_{agent_id}",
            "is_agent_at_prompt_inline": lambda _agent_id: False,
            "nudge_idle_agent": self.nudge_idle_agent,
            "agent_last_nudge_getter": lambda: self.agent_last_nudge,
            "role_description_for": lambda agent_conf, fallback="": str(agent_conf.get("description", fallback)).strip() or fallback,
            "team_members_for": lambda _agent_id: [],
            "create_agent_session": self.create_agent_session,
            "port_getter": lambda: 9111,
            "append_message": self.append_message,
            "ws_broadcast": self.ws_broadcast,
        }
        cfg.update(overrides)
        restart_wake.init(**cfg)

    def test_restart_wake_skips_when_team_config_missing(self) -> None:
        self.team_config = None
        self._init()

        restart_wake._restart_wake_phase()

        self.create_agent_session.assert_not_called()
        self.append_message.assert_not_called()
        self.ws_broadcast.assert_not_called()

    def test_restart_wake_reapplies_browser_false_before_nudge(self) -> None:
        self.team_config = {
            "agents": [{"id": "alpha", "active": True, "home_dir": "/tmp/alpha"}],
        }
        calls: list[list[str]] = []
        self._init(
            is_session_alive=lambda _agent_id: True,
            is_agent_at_prompt_inline=lambda _agent_id: True,
        )

        def _mock_run(cmd, **_kwargs):
            calls.append(cmd)
            return mock.MagicMock(returncode=0)

        with mock.patch("subprocess.run", side_effect=_mock_run):
            restart_wake._restart_wake_phase()

        self.assertTrue(any("set-environment" in cmd and "BROWSER" in cmd for cmd in calls))
        self.nudge_idle_agent.assert_called_once_with("alpha", "wake_phase")
        self.assertIn("alpha", self.agent_last_nudge)
        self.append_message.assert_called_once()
        self.ws_broadcast.assert_called_once()

    def test_restart_wake_starts_missing_active_agent_from_team_config(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            prompt_file = os.path.join(home_dir, "PROMPT.md")
            with open(prompt_file, "w", encoding="utf-8") as handle:
                handle.write("Resume bridge.")
            self.team_config = {
                "agents": [{
                    "id": "beta",
                    "active": True,
                    "home_dir": home_dir,
                    "prompt_file": prompt_file,
                    "engine": "claude",
                    "config_dir": "/tmp/profile",
                    "description": "Bridge Beta",
                    "mcp_servers": "bridge",
                    "model": "sonnet",
                    "permissions": "default",
                    "scope": "project",
                    "reports_to": "user",
                }],
            }
            self._init(
                team_members_for=lambda _agent_id: [{"id": "buddy", "role": "concierge"}],
            )

            restart_wake._restart_wake_phase()

        self.create_agent_session.assert_called_once()
        kwargs = self.create_agent_session.call_args.kwargs
        self.assertEqual(kwargs["agent_id"], "beta")
        self.assertEqual(kwargs["bridge_port"], 9111)
        self.assertEqual(kwargs["team_members"], [{"id": "buddy", "role": "concierge"}])
        self.assertEqual(kwargs["initial_prompt"], "Resume bridge.")
        self.assertEqual(kwargs["role_description"], "Bridge Beta")
        self.append_message.assert_called_once()
        self.ws_broadcast.assert_called_once()

    def test_start_restart_wake_thread_uses_expected_name_and_target(self) -> None:
        self._init()
        created: list[dict[str, object]] = []

        class FakeThread:
            def __init__(self, *, target, daemon, name):
                created.append({"target": target, "daemon": daemon, "name": name, "started": False})

            def start(self):
                created[-1]["started"] = True

        with mock.patch("threading.Thread", FakeThread):
            restart_wake._start_restart_wake_thread()

        self.assertEqual(len(created), 1)
        self.assertIs(created[0]["target"], restart_wake._delayed_restart_wake)
        self.assertEqual(created[0]["name"], "restart-wake")
        self.assertIs(created[0]["daemon"], True)
        self.assertIs(created[0]["started"], True)

    def test_restart_wake_enabled_reads_wrapper_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRIDGE_SERVER_WAKE_ON_START", None)
            self.assertFalse(restart_wake._restart_wake_enabled())

        with mock.patch.dict(os.environ, {"BRIDGE_SERVER_WAKE_ON_START": "1"}, clear=False):
            self.assertTrue(restart_wake._restart_wake_enabled())


if __name__ == "__main__":
    unittest.main()
