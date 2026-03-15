from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import Mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.distillation as dist


class TestDistillationDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.shutdown_active = False
        self.registered_agents = {
            "codex": {"agent_id": "codex"},
            "claude": {"agent_id": "claude"},
            "ghost": None,
        }
        self.append_message = Mock()

        def is_live(agent_id: str, *, stale_seconds: float, reg: object) -> bool:
            del stale_seconds, reg
            return agent_id != "claude"

        dist.init(
            system_shutdown_active=lambda: self.shutdown_active,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=is_live,
            append_message=self.append_message,
        )

    def test_tick_skips_when_system_shutdown_is_active(self) -> None:
        self.shutdown_active = True

        online = dist._distillation_tick()

        self.assertEqual(online, [])
        self.append_message.assert_not_called()

    def test_tick_sends_prompt_only_to_live_registered_agents(self) -> None:
        online = dist._distillation_tick()

        self.assertEqual(online, ["codex"])
        self.append_message.assert_called_once()
        args, kwargs = self.append_message.call_args
        self.assertEqual(args[:3], ("system", "codex", dist._DISTILLATION_PROMPT))
        self.assertEqual(kwargs["meta"], {"type": "distillation_trigger"})

    def test_tick_swallows_append_errors_and_continues(self) -> None:
        self.registered_agents["alpha"] = {"agent_id": "alpha"}

        def is_live(agent_id: str, *, stale_seconds: float, reg: object) -> bool:
            del stale_seconds, reg
            return agent_id in {"codex", "alpha"}

        calls: list[str] = []

        def append_message(_sender: str, agent_id: str, _content: str, **_kwargs: object) -> None:
            calls.append(agent_id)
            if agent_id == "codex":
                raise RuntimeError("boom")

        dist.init(
            system_shutdown_active=lambda: False,
            agent_state_lock=threading.Lock(),
            registered_agents=self.registered_agents,
            agent_is_live=is_live,
            append_message=append_message,
        )

        online = dist._distillation_tick()

        self.assertEqual(online, ["codex", "alpha"])
        self.assertEqual(calls, ["codex", "alpha"])
