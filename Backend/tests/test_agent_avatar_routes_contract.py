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
    def __init__(self, parts: list[dict] | None = None) -> None:
        self._parts = parts or []
        self.responses: list[tuple[int, dict]] = []

    def _parse_multipart(self) -> list[dict]:
        return list(self._parts)

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestAgentAvatarRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_avatar_routes_")
        self.frontend_dir = self._tmpdir.name
        self.team_config = {
            "agents": [
                {"id": "assi"},
                {"id": "buddy", "avatar_url": "/avatars/buddy.png"},
            ],
            "subscriptions": [],
        }
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
            frontend_dir=self.frontend_dir,
            runtime={},
            runtime_lock=threading.Lock(),
            ws_broadcast_fn=self._broadcast,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: f"/tmp/{agent_id}",
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=self._persist,
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _persist(self) -> None:
        self.persist_calls += 1

    def _broadcast(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

    def test_uploads_avatar_and_updates_team_config(self) -> None:
        handler = _DummyHandler(
            [{"name": "avatar", "filename": "assi.png", "data": b"png-bytes"}]
        )
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/avatar"))
        self.assertEqual(
            handler.responses[0],
            (200, {"ok": True, "agent_id": "assi", "avatar_url": "/avatars/assi.png"}),
        )
        avatar_path = os.path.join(self.frontend_dir, "avatars", "assi.png")
        self.assertTrue(os.path.exists(avatar_path))
        self.assertEqual(self.team_config["agents"][0]["avatar_url"], "/avatars/assi.png")
        self.assertEqual(self.persist_calls, 1)
        self.assertEqual(self.events[0][0], "agent_updated")

    def test_rejects_missing_avatar_part(self) -> None:
        handler = _DummyHandler([{"name": "other", "filename": "x.png", "data": b"x"}])
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/avatar"))
        self.assertEqual(handler.responses[0], (400, {"error": "missing 'avatar' field with filename"}))

    def test_rejects_unsupported_extension(self) -> None:
        handler = _DummyHandler([{"name": "avatar", "filename": "assi.gif", "data": b"gif"}])
        self.assertTrue(agents_mod.handle_post(handler, "/agents/assi/avatar"))
        self.assertEqual(
            handler.responses[0],
            (400, {"error": "unsupported format '.gif'. Allowed: png, jpg, jpeg, webp"}),
        )

    def test_restores_previous_avatar_when_persist_fails(self) -> None:
        avatars_dir = os.path.join(self.frontend_dir, "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        avatar_path = os.path.join(avatars_dir, "buddy.png")
        with open(avatar_path, "wb") as handle:
            handle.write(b"old-bytes")

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
            frontend_dir=self.frontend_dir,
            runtime={},
            runtime_lock=threading.Lock(),
            ws_broadcast_fn=self._broadcast,
            notify_teamlead_crashed_fn=lambda *args, **kwargs: None,
            tmux_session_for_fn=lambda agent_id: f"acw_{agent_id}",
            tmux_session_name_exists_fn=lambda session: False,
            runtime_layout_from_state_fn=lambda runtime: [],
            get_agent_home_dir_fn=lambda agent_id: f"/tmp/{agent_id}",
            check_agent_memory_health_fn=lambda agent_id: {"healthy": True},
            append_message_fn=lambda *args, **kwargs: None,
            atomic_write_team_json_fn=fail_persist,
        )
        handler = _DummyHandler([{"name": "avatar", "filename": "buddy.png", "data": b"new-bytes"}])
        self.assertTrue(agents_mod.handle_post(handler, "/agents/buddy/avatar"))
        self.assertEqual(handler.responses[0], (500, {"error": "failed to persist: disk full"}))
        self.assertEqual(self.team_config["agents"][1]["avatar_url"], "/avatars/buddy.png")
        with open(avatar_path, "rb") as handle:
            self.assertEqual(handle.read(), b"old-bytes")


if __name__ == "__main__":
    unittest.main()
