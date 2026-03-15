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
    def __init__(self, body: dict | None = None, platform_operator: bool = True) -> None:
        self._body = body or {}
        self._platform_operator = platform_operator
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self) -> dict:
        return dict(self._body)

    def _require_platform_operator(self) -> tuple[bool, str | None, str | None]:
        if self._platform_operator:
            return True, "operator", "buddy"
        self._respond(403, {"error": "platform operator required"})
        return False, None, None

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAgentSetupHomeRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_setup_home_routes_")
        self.team_config = {
            "agents": [
                {
                    "id": "assi",
                    "engine": "claude",
                    "home_dir": os.path.join(self._tmpdir.name, "assi"),
                    "agent_md": "",
                }
            ],
            "subscriptions": [],
        }
        os.makedirs(self.team_config["agents"][0]["home_dir"], exist_ok=True)
        self.persist_calls = 0
        self.sync_calls: list[tuple[str, str]] = []
        self.broadcasts: list[tuple[str, dict]] = []
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
            ws_broadcast_fn=self._broadcast,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: os.path.join(self._tmpdir.name, agent_id),
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=self._persist,
            setup_cli_binaries={"claude": "claude", "codex": "codex", "gemini": "gemini"},
            materialize_agent_setup_home_fn=self._materialize,
            sync_agent_persistent_cli_config_fn=self._sync,
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _persist(self) -> None:
        self.persist_calls += 1

    def _sync(self, agent_id: str, agent_entry: dict) -> None:
        self.sync_calls.append((agent_id, str(agent_entry["engine"])))

    def _broadcast(self, event: str, payload: dict) -> None:
        self.broadcasts.append((event, payload))

    def _materialize(self, agent_id: str, agent_entry: dict, *, engine: str, overwrite: bool) -> dict:
        guide_path = os.path.join(self._tmpdir.name, f"{agent_id}-guide.md")
        instruction_path = os.path.join(self._tmpdir.name, f"{agent_id}-{engine}.md")
        with open(guide_path, "w", encoding="utf-8") as handle:
            handle.write("guide")
        with open(instruction_path, "w", encoding="utf-8") as handle:
            handle.write("instruction")
        return {
            "instruction_path": instruction_path,
            "guide_path": guide_path,
            "created": [instruction_path, guide_path] if overwrite else [instruction_path],
        }

    def test_setup_home_updates_engine_and_agent_md(self) -> None:
        handler = _DummyHandler({"engine": "gemini", "overwrite": True})
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/setup-home"))
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["engine"], "gemini")
        self.assertTrue(body["agent_md"].endswith("assi-gemini.md"))
        self.assertEqual(self.team_config["agents"][0]["engine"], "gemini")
        self.assertEqual(self.team_config["agents"][0]["agent_md"], body["agent_md"])
        self.assertEqual(self.persist_calls, 1)
        self.assertEqual(self.sync_calls, [("assi", "gemini")])
        self.assertEqual(self.broadcasts[0][0], "agent_setup_home_updated")

    def test_setup_home_rejects_unknown_engine(self) -> None:
        handler = _DummyHandler({"engine": "unknown"})
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/setup-home"))
        self.assertEqual(
            handler.responses[0],
            (400, {"error": "engine must be one of ['claude', 'codex', 'gemini']"}),
        )


if __name__ == "__main__":
    unittest.main()
