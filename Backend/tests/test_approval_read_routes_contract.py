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
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestApprovalReadRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="approval_read_routes_contract_")
        self._orig_requests = dict(approvals_mod.APPROVAL_REQUESTS)
        approvals_mod.APPROVAL_REQUESTS.clear()
        approvals_mod.init(
            base_dir=self._tmpdir,
            messages_dir=self._tmpdir,
            agent_log_dir=self._tmpdir,
            append_message_fn=lambda *args, **kwargs: None,
            ws_broadcast_fn=lambda *args, **kwargs: None,
            is_management_agent_fn=lambda agent_id: agent_id == "viktor",
            sa_create_allowed_getter=lambda: {"user", "ordo"},
        )
        approvals_mod.APPROVAL_REQUESTS.update(
            {
                "appr_own": {
                    "request_id": "appr_own",
                    "agent_id": "codex",
                    "requested_by": "codex",
                    "status": "pending",
                    "requested_at": "2026-03-15T01:00:00+00:00",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                },
                "appr_other": {
                    "request_id": "appr_other",
                    "agent_id": "buddy",
                    "requested_by": "buddy",
                    "status": "pending",
                    "requested_at": "2026-03-15T01:05:00+00:00",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                },
            }
        )
        approvals_mod._save_standing_approvals(
            [
                {
                    "id": "SA-TEST",
                    "status": "active",
                    "action": "browser_login",
                    "agent": "codex",
                    "scope": {"target": "example.com"},
                }
            ]
        )

    def tearDown(self) -> None:
        approvals_mod.APPROVAL_REQUESTS.clear()
        approvals_mod.APPROVAL_REQUESTS.update(self._orig_requests)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_pending_acl_and_detail_and_standing_list(self) -> None:
        pending_handler = _DummyHandler(headers={"X-Bridge-Agent": "codex"})
        self.assertTrue(
            approvals_mod.handle_get(
                pending_handler,
                "/approval/pending",
                {},
            )
        )
        pending_status, pending_body = pending_handler.responses[0]
        self.assertEqual(pending_status, 200)
        self.assertEqual(pending_body["count"], 1)
        self.assertEqual(pending_body["pending"][0]["request_id"], "appr_own")

        detail_handler = _DummyHandler()
        self.assertTrue(approvals_mod.handle_get(detail_handler, "/approval/appr_other", {}))
        self.assertEqual(detail_handler.responses[0][0], 200)
        self.assertEqual(detail_handler.responses[0][1]["request_id"], "appr_other")

        standing_handler = _DummyHandler()
        self.assertTrue(approvals_mod.handle_get(standing_handler, "/standing-approval/list", {}))
        self.assertEqual(standing_handler.responses[0][0], 200)
        self.assertEqual(standing_handler.responses[0][1]["count"], 1)


if __name__ == "__main__":
    unittest.main()
