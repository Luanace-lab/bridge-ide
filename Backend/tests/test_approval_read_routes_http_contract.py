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


class TestApprovalReadRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="approval_read_routes_http_contract_")
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
            is_management_agent_fn=lambda agent_id: agent_id == "viktor",
            sa_create_allowed_getter=lambda: {"user", "ordo"},
        )
        approvals_mod.APPROVAL_REQUESTS.update(
            {
                "appr_http_codex": {
                    "request_id": "appr_http_codex",
                    "agent_id": "codex",
                    "requested_by": "codex",
                    "status": "pending",
                    "requested_at": "2026-03-15T01:00:00+00:00",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                },
                "appr_http_buddy": {
                    "request_id": "appr_http_buddy",
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
                    "id": "SA-HTTP",
                    "status": "active",
                    "action": "browser_login",
                    "agent": "codex",
                    "scope": {"target": "example.com"},
                }
            ]
        )

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

    def _get(self, base_url: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_approval_read_routes_http(self) -> None:
        base_url = self._start_server()

        pending_status, pending_body = self._get(
            base_url,
            "/approval/pending",
            {"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(pending_status, 200)
        self.assertEqual(pending_body["count"], 1)
        self.assertEqual(pending_body["pending"][0]["request_id"], "appr_http_codex")

        detail_status, detail_body = self._get(base_url, "/approval/appr_http_buddy")
        self.assertEqual(detail_status, 200)
        self.assertEqual(detail_body["request_id"], "appr_http_buddy")

        standing_status, standing_body = self._get(base_url, "/standing-approval/list")
        self.assertEqual(standing_status, 200)
        self.assertEqual(standing_body["count"], 1)


if __name__ == "__main__":
    unittest.main()
