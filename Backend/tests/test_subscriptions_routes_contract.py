from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.subscriptions_routes as subs_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, payload: dict | None = None):
        self._payload = payload
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self):
        return None if self._payload is None else dict(self._payload)

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestSubscriptionsRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="subscriptions_routes_contract_")
        self._profile_dir = os.path.join(self._tmpdir, "profile")
        os.makedirs(self._profile_dir, exist_ok=True)
        with open(os.path.join(self._profile_dir, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"ok": True}, handle)
        self._team_config = {"agents": [{"id": "codex", "config_dir": ""}], "subscriptions": []}
        self._writes = 0
        subs_mod.init(
            team_config=self._team_config,
            team_config_lock=threading.RLock(),
            build_subscription_response_item_fn=lambda sub, _agents: dict(sub),
            infer_subscription_provider_fn=lambda path, provider="": provider or ("claude" if path.endswith(".claude") else ""),
            atomic_write_team_json_fn=self._atomic_write,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _atomic_write(self) -> None:
        self._writes += 1

    def test_crud_roundtrip(self) -> None:
        create_handler = _DummyHandler({"name": "Slice67", "path": self._profile_dir, "email": "user@example.com"})
        self.assertTrue(subs_mod.handle_post(create_handler, "/subscriptions"))
        create_status, create_body = create_handler.responses[0]
        self.assertEqual(create_status, 201)
        sub_id = create_body["subscription"]["id"]

        get_handler = _DummyHandler()
        self.assertTrue(subs_mod.handle_get(get_handler, "/subscriptions"))
        self.assertEqual(get_handler.responses[0][0], 200)
        self.assertEqual(get_handler.responses[0][1]["subscriptions"][0]["id"], sub_id)

        put_handler = _DummyHandler({"name": "Slice67 Updated", "active": False})
        self.assertTrue(subs_mod.handle_put(put_handler, f"/subscriptions/{sub_id}"))
        self.assertEqual(put_handler.responses[0][0], 200)
        self.assertEqual(put_handler.responses[0][1]["subscription"]["name"], "Slice67 Updated")
        self.assertFalse(put_handler.responses[0][1]["subscription"]["active"])

        delete_handler = _DummyHandler()
        self.assertTrue(subs_mod.handle_delete(delete_handler, f"/subscriptions/{sub_id}"))
        self.assertEqual(delete_handler.responses[0][0], 200)
        self.assertEqual(delete_handler.responses[0][1]["deleted"]["id"], sub_id)
        self.assertEqual(self._writes, 3)

    def test_delete_rejects_assigned_subscription(self) -> None:
        self._team_config["subscriptions"].append({"id": "sub1", "name": "Assigned", "path": self._profile_dir, "active": True})
        self._team_config["agents"][0]["config_dir"] = self._profile_dir

        delete_handler = _DummyHandler()

        self.assertTrue(subs_mod.handle_delete(delete_handler, "/subscriptions/sub1"))
        status, body = delete_handler.responses[0]
        self.assertEqual(status, 409)
        self.assertIn("cannot delete", body["error"])


if __name__ == "__main__":
    unittest.main()
