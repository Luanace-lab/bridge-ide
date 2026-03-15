from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.approvals as approvals_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []
        self.json_body: dict | None = None

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self.json_body


class TestApprovalWriteRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="approval_write_routes_contract_")
        self._orig_requests = dict(approvals_mod.APPROVAL_REQUESTS)
        approvals_mod.APPROVAL_REQUESTS.clear()
        self.messages: list[tuple[tuple, dict]] = []
        self.broadcasts: list[tuple[tuple, dict]] = []
        approvals_mod.init(
            base_dir=self._tmpdir,
            messages_dir=self._tmpdir,
            agent_log_dir=self._tmpdir,
            append_message_fn=self._append_message,
            ws_broadcast_fn=self._broadcast,
            is_management_agent_fn=lambda agent_id: agent_id == "viktor",
            sa_create_allowed_getter=lambda: {"user", "ordo"},
        )
        approvals_mod.APPROVAL_REQUESTS["appr_pending"] = {
            "request_id": "appr_pending",
            "agent_id": "codex",
            "requested_by": "codex",
            "status": "pending",
            "requested_at": "2026-03-15T01:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "payload": {"url": "https://example.com"},
        }

    def tearDown(self) -> None:
        approvals_mod.APPROVAL_REQUESTS.clear()
        approvals_mod.APPROVAL_REQUESTS.update(self._orig_requests)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _append_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))

    def _broadcast(self, *args, **kwargs) -> None:
        self.broadcasts.append((args, kwargs))

    def test_approval_edit_route_merges_payload(self) -> None:
        handler = _DummyHandler()
        handler.json_body = {"decided_by": "user", "payload": {"username": "leo"}}
        self.assertTrue(approvals_mod.handle_post(handler, "/approval/appr_pending/edit"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["payload"]["url"], "https://example.com")
        self.assertEqual(handler.responses[0][1]["payload"]["username"], "leo")
        self.assertEqual(self.messages[0][0][1], "codex")
        self.assertEqual(self.broadcasts[0][0][0], "approval_edited")

    def test_standing_approval_create_and_revoke_routes(self) -> None:
        create_handler = _DummyHandler()
        create_handler.json_body = {
            "created_by": "user",
            "action": "browser_login",
            "agent": "codex",
            "scope": {"target": "slice99.example"},
        }
        self.assertTrue(approvals_mod.handle_post(create_handler, "/standing-approval/create"))
        self.assertEqual(create_handler.responses[0][0], 201)
        sa_id = create_handler.responses[0][1]["standing_approval"]["id"]

        revoke_handler = _DummyHandler()
        self.assertTrue(approvals_mod.handle_post(revoke_handler, f"/standing-approval/{sa_id}/revoke"))
        self.assertEqual(revoke_handler.responses[0], (200, {"ok": True, "sa_id": sa_id, "status": "revoked"}))


if __name__ == "__main__":
    unittest.main()
