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
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self) -> dict | None:
        return self._body

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAgentSubscriptionRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self.persist_calls = 0
        self.team_config = {
            "agents": [
                {"id": "buddy", "config_dir": "/profiles/sub1", "subscription_id": "sub1"},
                {"id": "assi", "config_dir": "/profiles/sub2"},
            ],
            "subscriptions": [
                {"id": "sub1", "path": "/profiles/sub1"},
                {"id": "sub2", "path": "/profiles/sub2"},
            ],
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
            team_config=self.team_config,
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
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=self._persist,
        )

    def _persist(self) -> None:
        self.persist_calls += 1

    def test_assigns_subscription_to_agent(self) -> None:
        handler = _DummyHandler({"subscription_id": "sub2"})
        self.assertTrue(agents_mod.handle_put(handler, "/agents/assi/subscription"))
        self.assertEqual(
            handler.responses[0],
            (200, {"ok": True, "agent_id": "assi", "subscription_id": "sub2", "config_dir": "/profiles/sub2"}),
        )
        self.assertEqual(self.team_config["agents"][1]["config_dir"], "/profiles/sub2")
        self.assertEqual(self.team_config["agents"][1]["subscription_id"], "sub2")
        self.assertEqual(self.persist_calls, 1)

    def test_clears_subscription_when_empty(self) -> None:
        handler = _DummyHandler({"subscription_id": ""})
        self.assertTrue(agents_mod.handle_put(handler, "/agents/buddy/subscription"))
        self.assertEqual(
            handler.responses[0],
            (200, {"ok": True, "agent_id": "buddy", "subscription_id": None, "config_dir": ""}),
        )
        self.assertEqual(self.team_config["agents"][0]["config_dir"], "")
        self.assertNotIn("subscription_id", self.team_config["agents"][0])
        self.assertEqual(self.persist_calls, 1)

    def test_returns_not_found_for_unknown_subscription(self) -> None:
        handler = _DummyHandler({"subscription_id": "missing"})
        self.assertTrue(agents_mod.handle_put(handler, "/agents/assi/subscription"))
        self.assertEqual(handler.responses[0], (404, {"error": "subscription 'missing' not found"}))
        self.assertEqual(self.persist_calls, 0)

    def test_rolls_back_assignment_when_persist_fails(self) -> None:
        def fail_persist() -> None:
            raise OSError("disk full")

        agents_mod.init(
            registered_agents={},
            agent_last_seen={},
            agent_busy={},
            session_tokens={},
            agent_tokens={},
            agent_state_lock=threading.Lock(),
            tasks={},
            task_lock=threading.Lock(),
            team_config=self.team_config,
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
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=fail_persist,
        )
        handler = _DummyHandler({"subscription_id": "sub2"})
        self.assertTrue(agents_mod.handle_put(handler, "/agents/buddy/subscription"))
        self.assertEqual(handler.responses[0], (500, {"error": "failed to persist: disk full"}))
        self.assertEqual(self.team_config["agents"][0]["config_dir"], "/profiles/sub1")
        self.assertEqual(self.team_config["agents"][0]["subscription_id"], "sub1")


if __name__ == "__main__":
    unittest.main()
