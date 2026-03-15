from __future__ import annotations

import os
import sys
import tempfile
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


class TestAgentCreateRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_create_routes_")
        self.root_dir = self._tmpdir.name
        self.team_config = {"agents": [{"id": "buddy"}], "subscriptions": []}
        self.persist_calls = 0
        self.events: list[tuple[str, dict]] = []
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
            team_config_getter_fn=lambda: self.team_config,
            frontend_dir=self.root_dir,
            runtime={},
            runtime_lock=threading.Lock(),
            ws_broadcast_fn=self._broadcast,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: os.path.join(self.root_dir, ".agent_sessions", agent_id),
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=self._persist,
            root_dir=self.root_dir,
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _persist(self) -> None:
        self.persist_calls += 1

    def _broadcast(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

    def test_creates_agent_and_materializes_home(self) -> None:
        handler = _DummyHandler(
            {
                "id": "slice106",
                "role": "reviewer",
                "description": "Review agent",
                "project_path": self.root_dir,
                "scope": ["notes"],
                "skills": ["bridge-agent-core"],
                "active": False,
            }
        )
        self.assertTrue(agents_mod.handle_post(handler, "/agents/create"))
        self.assertEqual(handler.responses[0][0], 201)
        agent = handler.responses[0][1]["agent"]
        self.assertEqual(agent["id"], "slice106")
        self.assertEqual(agent["home_dir"], os.path.join(self.root_dir, ".agent_sessions", "slice106"))
        self.assertTrue(os.path.exists(os.path.join(agent["home_dir"], "SOUL.md")))
        self.assertTrue(os.path.isdir(os.path.join(agent["home_dir"], "notes")))
        self.assertEqual(self.persist_calls, 1)
        self.assertEqual(self.events[-1][0], "agent_created")

    def test_rejects_project_path_outside_root(self) -> None:
        outside_root = tempfile.mkdtemp(prefix="agent_create_outside_")
        self.addCleanup(lambda: os.path.isdir(outside_root) and os.rmdir(outside_root))
        handler = _DummyHandler(
            {
                "id": "slice106",
                "role": "reviewer",
                "project_path": outside_root,
            }
        )
        self.assertTrue(agents_mod.handle_post(handler, "/agents/create"))
        self.assertEqual(handler.responses[0], (400, {"error": "project_path must be within project root"}))

    def test_rejects_duplicate_agent(self) -> None:
        handler = _DummyHandler({"id": "buddy", "role": "reviewer"})
        self.assertTrue(agents_mod.handle_post(handler, "/agents/create"))
        self.assertEqual(handler.responses[0], (409, {"error": "agent 'buddy' already exists"}))


if __name__ == "__main__":
    unittest.main()
