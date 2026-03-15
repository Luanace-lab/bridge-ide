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
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAgentRestartRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_restart_routes_")
        self.home_dir = os.path.join(self._tmpdir.name, "assi")
        os.makedirs(self.home_dir, exist_ok=True)
        self.prompt_file = os.path.join(self._tmpdir.name, "assi_prompt.txt")
        with open(self.prompt_file, "w", encoding="utf-8") as handle:
            handle.write("custom restart prompt")
        self.team_config = {
            "agents": [
                {
                    "id": "assi",
                    "active": True,
                    "home_dir": self.home_dir,
                    "prompt_file": self.prompt_file,
                    "engine": "claude",
                    "description": "Assi role",
                    "config_dir": "/tmp/claude-profile",
                    "mcp_servers": "core",
                    "model": "claude-test",
                    "permissions": {"approval_required": False},
                    "scope": ["repo"],
                    "reports_to": "user",
                },
                {
                    "id": "buddy",
                    "active": False,
                    "home_dir": self.home_dir,
                },
            ],
            "subscriptions": [],
        }
        self.created: list[dict] = []
        self.killed: list[str] = []
        self.alive_ids: set[str] = set()
        self.cleared: list[str] = []
        self.original_clear = agents_mod._clear_agent_runtime_presence
        agents_mod._clear_agent_runtime_presence = self._clear_runtime_presence
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
            frontend_dir=self._tmpdir.name,
            runtime={},
            runtime_lock=threading.Lock(),
            ws_broadcast_fn=lambda *args, **kwargs: None,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: os.path.join(self._tmpdir.name, agent_id),
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=lambda: None,
            bridge_port=9111,
            create_agent_session_fn=self._create_agent_session,
            kill_agent_session_fn=self._kill_agent_session,
            is_session_alive_fn=self._is_session_alive,
        )

    def tearDown(self) -> None:
        agents_mod._clear_agent_runtime_presence = self.original_clear
        self._tmpdir.cleanup()

    def _create_agent_session(self, **kwargs) -> bool:
        self.created.append(dict(kwargs))
        self.alive_ids.add(kwargs["agent_id"])
        return True

    def _kill_agent_session(self, agent_id: str) -> bool:
        self.killed.append(agent_id)
        self.alive_ids.discard(agent_id)
        return True

    def _is_session_alive(self, agent_id: str) -> bool:
        return agent_id in self.alive_ids

    def _clear_runtime_presence(self, agent_id: str) -> None:
        self.cleared.append(agent_id)

    def test_restart_rejects_inactive_disconnected_agent(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/buddy/restart"))
        self.assertEqual(handler.responses[0], (400, {"error": "agent 'buddy' is not active"}))

    def test_restart_returns_not_found_for_unknown_agent(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/ghost/restart"))
        self.assertEqual(handler.responses[0], (404, {"error": "agent 'ghost' not in team.json"}))

    def test_restart_kills_existing_session_and_restarts(self) -> None:
        self.alive_ids.add("assi")
        handler = _DummyHandler()
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/restart"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["action"], "restarted")
        self.assertTrue(handler.responses[0][1]["session_alive"])
        self.assertEqual(self.killed, ["assi"])
        self.assertEqual(self.cleared, ["assi"])
        self.assertEqual(self.created[0]["agent_id"], "assi")
        self.assertEqual(self.created[0]["project_path"], self.home_dir)
        self.assertEqual(self.created[0]["role"], "Assi role")
        self.assertEqual(self.created[0]["bridge_port"], 9111)
        self.assertEqual(self.created[0]["initial_prompt"], "custom restart prompt")


if __name__ == "__main__":
    unittest.main()
