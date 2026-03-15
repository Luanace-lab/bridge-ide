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


class TestWorkflowsReadRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_registry = dict(routes_mod.WORKFLOW_REGISTRY)
        self._orig_tools = dict(routes_mod._WORKFLOW_TOOLS)
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.WORKFLOW_REGISTRY.clear()
        routes_mod.WORKFLOW_REGISTRY["wf_1"] = {
            "workflow_id": "wf_1",
            "source": "bridge_builder",
            "bridge_spec": {"name": "Flow"},
        }
        routes_mod._WORKFLOW_TOOLS.clear()
        routes_mod._WORKFLOW_TOOLS["tool_1"] = {"name": "tool_1", "workflow_id": "wf_1"}

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.WORKFLOW_REGISTRY.clear()
        routes_mod.WORKFLOW_REGISTRY.update(self._orig_registry)
        routes_mod._WORKFLOW_TOOLS.clear()
        routes_mod._WORKFLOW_TOOLS.update(self._orig_tools)
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

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    @patch("handlers.workflows._n8n_request")
    def test_workflows_read_routes_http(self, mock_request) -> None:
        mock_request.side_effect = [
            (200, {"data": [{"id": "exec_1"}]}),
            (200, {"data": [{"id": "wf_1", "name": "Flow", "active": True, "tags": []}]}),
            (200, {"data": [{"id": "wf_2", "name": "List Flow", "active": False}]}),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "template.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "template_id": "tpl_demo",
                        "name": "Demo",
                        "description": "Demo template",
                        "category": "ops",
                        "difficulty": "easy",
                        "icon": "tool",
                        "variables": [],
                        "setup_steps": [],
                    },
                    handle,
                )
            with patch.object(routes_mod, "WORKFLOW_TEMPLATES_DIR", tmpdir):
                with patch("handlers.workflows.workflow_bot.detect_workflow_intent", return_value={"intent": "list_workflows"}):
                    with patch("handlers.workflows.workflow_bot.format_list_response", return_value="formatted"):
                        base_url = self._start_server()

                        execution_status, execution_body = self._get(base_url, "/n8n/executions?limit=10")
                        self.assertEqual(execution_status, 200)
                        self.assertEqual(execution_body["data"][0]["id"], "exec_1")

                        workflows_status, workflows_body = self._get(base_url, "/workflows?limit=20")
                        self.assertEqual(workflows_status, 200)
                        self.assertEqual(workflows_body["count"], 1)

                        definition_status, definition_body = self._get(base_url, "/workflows/wf_1/definition")
                        self.assertEqual(definition_status, 200)
                        self.assertEqual(definition_body["workflow_id"], "wf_1")

                        templates_status, templates_body = self._get(base_url, "/workflows/templates")
                        self.assertEqual(templates_status, 200)
                        self.assertEqual(templates_body["count"], 1)

                        tools_status, tools_body = self._get(base_url, "/workflows/tools")
                        self.assertEqual(tools_status, 200)
                        self.assertEqual(tools_body["count"], 1)

                        suggest_status, suggest_body = self._get(base_url, "/workflows/suggest?message=liste")
                        self.assertEqual(suggest_status, 200)
                        self.assertEqual(suggest_body["formatted_response"], "formatted")


if __name__ == "__main__":
    unittest.main()
