from __future__ import annotations

import json
import os
import sys
import tempfile
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


class TestWorkflowsPostRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
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
    @patch("handlers.workflows._register_workflow_subscription", return_value={"subscription_id": "sub_1"})
    @patch("handlers.workflows._deploy_workflow_to_n8n", return_value=("wf_1", {"name": "Flow", "active": False}, None))
    @patch("handlers.workflows.workflow_validator.validate_workflow")
    @patch("handlers.workflows.workflow_builder.compile_bridge_workflow")
    def test_workflows_post_routes_http(
        self,
        mock_compile,
        mock_validate,
        _mock_deploy,
        _mock_sub,
        _mock_tool,
        _mock_record,
    ) -> None:
        mock_compile.side_effect = [
            {
                "workflow": {"name": "Compiled", "nodes": []},
                "node_names_by_id": {"n1": "Node 1"},
                "bridge_subscription": {"event_type": "task.created"},
                "validation": {"valid": True},
            },
            {
                "workflow": {"name": "Flow", "nodes": [], "connections": {}},
                "validation": {"valid": True},
                "bridge_subscription": {"event_type": "task.created"},
            },
        ]
        mock_validate.return_value = type("Result", (), {"valid": True, "warnings": [], "to_dict": lambda self: {"valid": True}})()

        base_url = self._start_server()

        status, body = self._request(base_url, "POST", "/workflows/compile", {"definition": {"name": "Compiled"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["workflow"]["name"], "Compiled")

        status, body = self._request(base_url, "POST", "/workflows/deploy", {"definition": {"name": "Flow"}, "activate": False})
        self.assertEqual(status, 201)
        self.assertEqual(body["workflow"]["id"], "wf_1")

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "template.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "template_id": "tpl_demo",
                        "name": "Template Flow",
                        "variables": [{"key": "channel", "required": True}],
                        "n8n_workflow": {"name": "Template {{channel}}", "nodes": [], "connections": {}},
                    },
                    handle,
                )
            with patch.object(routes_mod, "WORKFLOW_TEMPLATES_DIR", tmpdir):
                status, body = self._request(base_url, "POST", "/workflows/deploy-template", {"template_id": "tpl_demo", "variables": {"channel": "ops"}})
        self.assertEqual(status, 201)
        self.assertEqual(body["template_id"], "tpl_demo")


if __name__ == "__main__":
    unittest.main()
