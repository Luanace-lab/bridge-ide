from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.workflows as routes_mod  # noqa: E402


class TestWorkflowsWriteRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_registry = dict(routes_mod.WORKFLOW_REGISTRY)
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.WORKFLOW_REGISTRY.clear()
        routes_mod.WORKFLOW_REGISTRY["wf_1"] = {
            "workflow_id": "wf_1",
            "source": "bridge_builder",
            "bridge_subscription": {"subscription_id": "sub_old"},
            "bridge_spec": {"name": "Old"},
        }

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.WORKFLOW_REGISTRY.clear()
        routes_mod.WORKFLOW_REGISTRY.update(self._orig_registry)
        routes_mod.init(
            get_port_fn=lambda: srv.PORT,
            get_bridge_user_token_fn=lambda: srv.BRIDGE_USER_TOKEN,
            get_auth_tier2_post_paths_fn=lambda: srv.AUTH_TIER2_POST_PATHS,
            get_auth_tier3_post_paths_fn=lambda: srv.AUTH_TIER3_POST_PATHS,
            get_auth_tier3_patterns_fn=lambda: srv.AUTH_TIER3_POST_PATTERNS,
            utc_now_iso_fn=srv.utc_now_iso,
        )

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

    def _request(self, base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    @patch("handlers.workflows._record_workflow_deployment")
    @patch("handlers.workflows._register_workflow_webhook_tool", return_value={"name": "tool_1"})
    @patch("handlers.workflows._register_workflow_subscription", return_value={"subscription_id": "sub_new"})
    @patch("handlers.workflows._workflow_delete_cleanup", return_value={"tool_removed": "tool_1"})
    @patch("handlers.workflows.event_bus.unsubscribe")
    @patch("handlers.workflows._update_workflow_in_n8n", return_value=({"name": "Updated Flow", "active": True}, None))
    @patch("handlers.workflows.workflow_builder.compile_bridge_workflow")
    @patch("handlers.workflows._n8n_request")
    def test_workflows_write_routes_http(
        self,
        mock_request,
        mock_compile,
        _mock_update,
        _mock_unsub,
        _mock_delete_cleanup,
        _mock_register_sub,
        _mock_register_tool,
        _mock_record,
    ) -> None:
        mock_request.side_effect = [
            (200, {"id": "wf_1"}),      # GET before toggle
            (200, {"active": True}),    # activate
            (200, {"ok": True}),        # delete
        ]
        mock_compile.return_value = {
            "workflow": {"name": "Updated Flow", "nodes": [], "connections": {}},
            "validation": {"valid": True},
            "bridge_subscription": {"event_type": "task.created"},
        }

        base_url = self._start_server()

        status, body = self._request(base_url, "PATCH", "/workflows/wf_1/toggle", {"active": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["workflow"]["active"])

        status, body = self._request(base_url, "PUT", "/workflows/wf_1/definition", {"definition": {"name": "Updated Flow", "nodes": [], "edges": []}})
        self.assertEqual(status, 200)
        self.assertEqual(body["workflow"]["name"], "Updated Flow")

        status, body = self._request(base_url, "DELETE", "/workflows/wf_1")
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted_workflow"], "wf_1")


if __name__ == "__main__":
    unittest.main()
