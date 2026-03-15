from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import Mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.agent_health as health


class TestAgentHealthDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.now = time.time()
        self.registered_agents: dict[str, dict] = {}
        self.agent_busy: dict[str, bool] = {}
        self.agent_last_seen: dict[str, float] = {}
        self.agent_last_restart: dict[str, float] = {}
        self.agent_auth_blocked: set[str] = set()
        self.agent_oauth_failures: dict[str, object] = {}
        self.agent_last_auto_register: dict[str, float] = {}
        self.agent_last_nudge: dict[str, float] = {}
        self.cursors: dict[str, int] = {}
        self.grace_tokens: dict[str, tuple[object, float]] = {}
        self.append_message = Mock()
        self.auto_restart_agent = Mock(return_value=True)
        self.start_agent_from_conf = Mock(return_value=True)
        self.send_health_alert = Mock()
        self.plan_mode_rescue_check = Mock(return_value=False)
        self.seed_phantom_agent_registration = Mock()
        self.nudge_idle_agent = Mock(return_value=True)
        self.update_agent_status = Mock()

    def _init(self, **overrides: object) -> None:
        cfg = {
            "system_shutdown_active": lambda: False,
            "current_runtime_slot_map": lambda: {},
            "load_agents_conf": lambda: {},
            "team_config_getter": lambda: {},
            "all_tmux_agent_ids": lambda: set(),
            "agent_state_lock": threading.Lock(),
            "registered_agents": self.registered_agents,
            "agent_busy": self.agent_busy,
            "agent_last_seen": self.agent_last_seen,
            "is_session_alive": lambda _agent_id: False,
            "get_agent_engine": lambda _agent_id: "claude",
            "check_codex_health": lambda _agent_id: {"crashed": False, "detail": ""},
            "auto_restart_agents": lambda: True,
            "agent_last_restart": self.agent_last_restart,
            "restart_cooldown": lambda: 60.0,
            "auto_restart_agent": self.auto_restart_agent,
            "start_agent_from_conf": self.start_agent_from_conf,
            "send_health_alert": self.send_health_alert,
            "is_agent_at_oauth_prompt": lambda _agent_id: False,
            "agent_auth_blocked": self.agent_auth_blocked,
            "agent_oauth_failures": self.agent_oauth_failures,
            "append_message": self.append_message,
            "plan_mode_rescue_check": self.plan_mode_rescue_check,
            "agent_last_auto_register": self.agent_last_auto_register,
            "auto_register_cooldown": lambda: 60.0,
            "runtime_profile_capabilities": lambda _agent_id: ["bridge"],
            "seed_phantom_agent_registration": self.seed_phantom_agent_registration,
            "agent_last_nudge": self.agent_last_nudge,
            "nudge_cooldown": lambda: 60.0,
            "message_cond": threading.Condition(),
            "cursors": self.cursors,
            "messages_for_agent": lambda _cursor, _agent_id: [],
            "is_agent_at_prompt_inline": lambda _agent_id: False,
            "classify_agent_interactive_blocker": lambda _agent_id: {},
            "nudge_idle_agent": self.nudge_idle_agent,
            "update_agent_status": self.update_agent_status,
            "auto_cleanup_agents": lambda _ttl: None,
            "grace_tokens": self.grace_tokens,
        }
        cfg.update(overrides)
        health.init(**cfg)

    def test_tick_skips_when_shutdown_active(self) -> None:
        self._init(system_shutdown_active=lambda: True)

        counter = health._agent_health_tick(0)

        self.assertEqual(counter, 0)
        self.append_message.assert_not_called()
        self.update_agent_status.assert_not_called()

    def test_tick_restarts_crashed_codex_session(self) -> None:
        self.registered_agents["codex"] = {"last_heartbeat": self.now}
        self._init(
            load_agents_conf=lambda: {"codex": {"prompt_file": "x"}},
            all_tmux_agent_ids=lambda: {"codex"},
            is_session_alive=lambda _agent_id: True,
            get_agent_engine=lambda _agent_id: "codex",
            check_codex_health=lambda _agent_id: {"crashed": True, "detail": "panic"},
        )

        counter = health._agent_health_tick(0)

        self.assertEqual(counter, 1)
        self.append_message.assert_called()
        self.auto_restart_agent.assert_called_once_with("codex")
        self.update_agent_status.assert_called_once_with("codex")

    def test_tick_phantom_registers_alive_unregistered_agent(self) -> None:
        self._init(
            current_runtime_slot_map=lambda: {"alpha": "worker"},
            load_agents_conf=lambda: {"alpha": {"prompt_file": "x"}},
            all_tmux_agent_ids=lambda: {"alpha"},
            is_session_alive=lambda _agent_id: True,
        )

        counter = health._agent_health_tick(0)

        self.assertEqual(counter, 1)
        self.seed_phantom_agent_registration.assert_called_once()
        args = self.seed_phantom_agent_registration.call_args.kwargs
        self.assertEqual(args["role"], "worker")
        self.assertEqual(args["capabilities"], ["bridge"])
        self.assertIn("alpha", self.agent_last_auto_register)

    def test_tick_nudges_prompted_agent_with_pending_messages(self) -> None:
        self.registered_agents["alpha"] = {"last_heartbeat": self.now}
        self._init(
            load_agents_conf=lambda: {"alpha": {"prompt_file": "x"}},
            all_tmux_agent_ids=lambda: {"alpha"},
            is_session_alive=lambda _agent_id: True,
            messages_for_agent=lambda _cursor, _agent_id: [{"id": 1}],
            is_agent_at_prompt_inline=lambda _agent_id: True,
            classify_agent_interactive_blocker=lambda _agent_id: {},
            nudge_idle_agent=self.nudge_idle_agent,
        )

        counter = health._agent_health_tick(0)

        self.assertEqual(counter, 1)
        self.nudge_idle_agent.assert_called_once_with("alpha", "health_checker")
        self.assertIn("alpha", self.agent_last_nudge)
