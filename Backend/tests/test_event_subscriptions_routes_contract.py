from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.event_subscriptions_routes as event_subs_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, payload: dict | None = None, headers: dict[str, str] | None = None):
        self._payload = payload
        self.headers = headers or {}
        self.responses: list[tuple[int, dict]] = []

    def _parse_json_body(self):
        return self._payload

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestEventSubscriptionsRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._subs: list[dict] = []

        def list_subscriptions(*, created_by=None):
            if created_by:
                return [sub for sub in self._subs if sub.get("created_by") == created_by]
            return list(self._subs)

        def subscribe(*, event_type, webhook_url, created_by, filter_rules, label):
            sub = {
                "id": f"sub-{len(self._subs)+1}",
                "event_type": event_type,
                "webhook_url": webhook_url,
                "created_by": created_by,
                "filter": filter_rules,
                "label": label,
            }
            self._subs.append(sub)
            return sub

        def unsubscribe(sub_id: str) -> bool:
            for idx, sub in enumerate(self._subs):
                if sub["id"] == sub_id:
                    self._subs.pop(idx)
                    return True
            return False

        event_subs_mod.init(
            list_subscriptions_fn=list_subscriptions,
            subscribe_fn=subscribe,
            unsubscribe_fn=unsubscribe,
        )

    def test_crud_roundtrip(self) -> None:
        post_handler = _DummyHandler(
            payload={"event_type": "task.created", "webhook_url": "http://example.invalid/hook", "label": "Slice68"},
            headers={"X-Bridge-Agent": "user"},
        )
        self.assertTrue(event_subs_mod.handle_post(post_handler, "/events/subscribe"))
        self.assertEqual(post_handler.responses[0][0], 201)
        sub_id = post_handler.responses[0][1]["subscription"]["id"]

        get_handler = _DummyHandler(headers={"X-Bridge-Agent": "user"})
        self.assertTrue(event_subs_mod.handle_get(get_handler, "/events/subscriptions"))
        self.assertEqual(get_handler.responses[0][0], 200)
        self.assertEqual(get_handler.responses[0][1]["subscriptions"][0]["id"], sub_id)

        delete_handler = _DummyHandler()
        self.assertTrue(event_subs_mod.handle_delete(delete_handler, f"/events/subscriptions/{sub_id}"))
        self.assertEqual(delete_handler.responses[0][0], 200)
        self.assertEqual(delete_handler.responses[0][1]["deleted"], sub_id)

    def test_post_rejects_non_dict_filter(self) -> None:
        handler = _DummyHandler(payload={"event_type": "task.created", "webhook_url": "http://example.invalid/hook", "filter": []})
        self.assertTrue(event_subs_mod.handle_post(handler, "/events/subscribe"))
        self.assertEqual(handler.responses[0][0], 400)
        self.assertIn("filter must be a dict", handler.responses[0][1]["error"])


if __name__ == "__main__":
    unittest.main()
