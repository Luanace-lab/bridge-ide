from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.git_lock_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, *, headers: dict[str, str] | None = None, body: dict | None = None) -> None:
        self.headers = headers or {}
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestGitLockRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_locks: list[dict] | None = None
        routes_mod.init(
            git_locks_file="/tmp/git_locks.json",
            acquire_lock_fn=lambda path, branch, agent, instance_id: {
                "ok": True,
                "branch": branch,
                "agent_id": agent,
                "instance_id": instance_id,
                "path": path,
            },
            release_lock_fn=lambda path, branch, agent: {
                "ok": True,
                "released": branch,
                "agent_id": agent,
                "path": path,
            },
            load_locks_fn=lambda _path: [{"branch": "feature/test", "agent_id": "other"}],
            save_locks_fn=lambda _path, locks: setattr(self, "saved_locks", locks),
            is_management_agent_fn=lambda agent_id: agent_id == "ordo",
        )

    def test_get_route(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/git/locks"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["count"], 1)

    def test_post_route(self) -> None:
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"}, body={"branch": "feature/test", "instance_id": "inst"})
        self.assertTrue(routes_mod.handle_post(handler, "/git/lock"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["agent_id"], "codex")

    def test_post_identity_mismatch_rejected(self) -> None:
        handler = _DummyHandler(
            headers={"X-Bridge-Agent": "codex"},
            body={"branch": "feature/test", "agent_id": "other"},
        )
        self.assertTrue(routes_mod.handle_post(handler, "/git/lock"))
        self.assertEqual(handler.responses[0][0], 403)

    def test_delete_route(self) -> None:
        handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"}, body={"branch": "feature/test"})
        self.assertTrue(routes_mod.handle_delete(handler, "/git/lock"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["released"], "feature/test")

    def test_delete_management_override(self) -> None:
        routes_mod.init(
            git_locks_file="/tmp/git_locks.json",
            acquire_lock_fn=None,
            release_lock_fn=lambda _path, _branch, _agent: {"ok": False, "error": "not_owner"},
            load_locks_fn=lambda _path: [{"branch": "feature/test", "agent_id": "other"}],
            save_locks_fn=lambda _path, locks: setattr(self, "saved_locks", locks),
            is_management_agent_fn=lambda agent_id: agent_id == "ordo",
        )
        handler = _DummyHandler(headers={"X-Bridge-Agent": "ordo"}, body={"branch": "feature/test"})
        self.assertTrue(routes_mod.handle_delete(handler, "/git/lock"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(self.saved_locks, [])


if __name__ == "__main__":
    unittest.main()
