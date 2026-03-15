from __future__ import annotations

import os
import sys
import threading
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.agents as agents_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAgentWarnMemoryRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self.messages: list[tuple[tuple, dict]] = []
        self.health_map = {
            "codex": {"healthy": False, "warning": "context bridge stale"},
            "buddy": {"healthy": True},
            "ghost": {"error": "agent not found"},
        }
        agents_mod.init(
            registered_agents={},
            agent_last_seen={},
            agent_busy={},
            session_tokens={},
            agent_tokens={},
            agent_state_lock=threading.Lock(),
            tasks={},
            task_lock=threading.Lock(),
            team_config={},
            team_config_lock=threading.Lock(),
            frontend_dir="/tmp",
            runtime={},
            runtime_lock=threading.Lock(),
            ws_broadcast_fn=lambda *args, **kwargs: None,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: f"/tmp/{agent_id}",
            check_agent_memory_health_fn=self._check_memory_health,
            append_message_fn=self._append_message,
            atomic_write_team_json_fn=lambda: None,
        )

    def _check_memory_health(self, agent_id: str) -> dict[str, object]:
        return dict(self.health_map.get(agent_id, {"error": "agent not found"}))

    def _append_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))

    def test_warn_memory_route_sends_warning_when_unhealthy(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/codex/warn-memory"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertTrue(handler.responses[0][1]["warned"])
        self.assertEqual(self.messages[0][0][1], "codex")

    def test_warn_memory_route_short_circuits_when_healthy(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/buddy/warn-memory"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertFalse(handler.responses[0][1]["warned"])
        self.assertEqual(self.messages, [])

    def test_warn_memory_route_returns_not_found_when_health_check_errors(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/ghost/warn-memory"))
        self.assertEqual(handler.responses[0], (404, {"error": "agent not found"}))


if __name__ == "__main__":
    unittest.main()
