from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.approvals as approvals_mod  # noqa: E402


class TestApprovalWriteRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="approval_write_routes_http_contract_")
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_requests = dict(approvals_mod.APPROVAL_REQUESTS)
        srv.BRIDGE_STRICT_AUTH = False
        approvals_mod.APPROVAL_REQUESTS.clear()
        approvals_mod.init(
            base_dir=self._tmpdir,
            messages_dir=self._tmpdir,
            agent_log_dir=self._tmpdir,
            append_message_fn=lambda *args, **kwargs: None,
            ws_broadcast_fn=lambda *args, **kwargs: None,
            is_management_agent_fn=srv._is_management_agent,
            sa_create_allowed_getter=lambda: {"user", "ordo"},
        )
        approvals_mod.APPROVAL_REQUESTS["appr_http_pending"] = {
            "request_id": "appr_http_pending",
            "agent_id": "codex",
            "requested_by": "codex",
            "status": "pending",
            "requested_at": "2026-03-15T01:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "payload": {"url": "https://example.com"},
        }

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        approvals_mod.APPROVAL_REQUESTS.clear()
        approvals_mod.APPROVAL_REQUESTS.update(self._orig_requests)
        approvals_mod.init(
            base_dir=srv.BASE_DIR,
            messages_dir=srv.MESSAGES_DIR,
            agent_log_dir=srv.AGENT_LOG_DIR,
            append_message_fn=srv.append_message,
            ws_broadcast_fn=srv.ws_broadcast,
            is_management_agent_fn=srv._is_management_agent,
            sa_create_allowed_getter=lambda: set(srv._RBAC_SA_CREATE_ALLOWED),
        )
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_approval_edit_and_standing_approval_write_routes_http(self) -> None:
        base_url = self._start_server()

        edit_status, edit_body = self._post(
            base_url,
            "/approval/appr_http_pending/edit",
            {"decided_by": "user", "payload": {"username": "owner"}},
        )
        self.assertEqual(edit_status, 200)
        self.assertEqual(edit_body["payload"]["url"], "https://example.com")
        self.assertEqual(edit_body["payload"]["username"], "owner")

        create_status, create_body = self._post(
            base_url,
            "/standing-approval/create",
            {
                "created_by": "user",
                "action": "browser_login",
                "agent": "codex",
                "scope": {"target": "slice99-http.example"},
            },
        )
        self.assertEqual(create_status, 201)
        sa_id = create_body["standing_approval"]["id"]

        revoke_status, revoke_body = self._post(base_url, f"/standing-approval/{sa_id}/revoke", {})
        self.assertEqual(revoke_status, 200)
        self.assertEqual(revoke_body["sa_id"], sa_id)
        self.assertEqual(revoke_body["status"], "revoked")


if __name__ == "__main__":
    unittest.main()
