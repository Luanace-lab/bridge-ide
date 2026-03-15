from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.workflows as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self, body: dict | None = None) -> None:
        self._body = body
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._body


class TestWorkflowsPostRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        routes_mod.init(
            get_port_fn=lambda: 9111,
            get_bridge_user_token_fn=lambda: "test-token",
            get_auth_tier2_post_paths_fn=lambda: set(),
            get_auth_tier3_post_paths_fn=lambda: set(),
            get_auth_tier3_patterns_fn=lambda: [],
            utc_now_iso_fn=lambda: "2026-03-15T00:00:00+00:00",
        )

    def tearDown(self) -> None:
        routes_mod.init(
            get_port_fn=lambda: srv.PORT,
            get_bridge_user_token_fn=lambda: srv.BRIDGE_USER_TOKEN,
            get_auth_tier2_post_paths_fn=lambda: srv.AUTH_TIER2_POST_PATHS,
            get_auth_tier3_post_paths_fn=lambda: srv.AUTH_TIER3_POST_PATHS,
            get_auth_tier3_patterns_fn=lambda: srv.AUTH_TIER3_POST_PATTERNS,
            utc_now_iso_fn=srv.utc_now_iso,
        )

    @patch("handlers.workflows.workflow_builder.compile_bridge_workflow")
    def test_compile_route(self, mock_compile) -> None:
        mock_compile.return_value = {
            "workflow": {"name": "Compiled", "nodes": []},
            "node_names_by_id": {"n1": "Node 1"},
            "bridge_subscription": {"event_type": "task.created"},
            "validation": {"valid": True},
        }
        handler = _DummyHandler({"definition": {"name": "Compiled"}})
        self.assertTrue(routes_mod.handle_post(handler, "/workflows/compile"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["workflow"]["name"], "Compiled")

    @patch("handlers.workflows._record_workflow_deployment")
    @patch("handlers.workflows._register_workflow_webhook_tool", return_value={"name": "tool_1"})
    @patch("handlers.workflows._register_workflow_subscription", return_value={"subscription_id": "sub_1"})
    @patch("handlers.workflows._deploy_workflow_to_n8n", return_value=("wf_1", {"name": "Flow", "active": False}, None))
    @patch("handlers.workflows.workflow_builder.compile_bridge_workflow")
    def test_deploy_route(
        self,
        mock_compile,
        _mock_deploy,
        _mock_sub,
        _mock_tool,
        mock_record,
    ) -> None:
        mock_compile.return_value = {
            "workflow": {"name": "Flow", "nodes": [], "connections": {}},
            "validation": {"valid": True},
            "bridge_subscription": {"event_type": "task.created"},
        }
        handler = _DummyHandler({"definition": {"name": "Flow"}, "activate": False})
        self.assertTrue(routes_mod.handle_post(handler, "/workflows/deploy"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertEqual(handler.responses[0][1]["workflow"]["id"], "wf_1")
        mock_record.assert_called_once()

    @patch("handlers.workflows._record_workflow_deployment")
    @patch("handlers.workflows._register_workflow_webhook_tool", return_value={"name": "tool_1"})
    @patch("handlers.workflows._register_workflow_subscription", return_value={"subscription_id": "sub_1"})
    @patch("handlers.workflows._deploy_workflow_to_n8n", return_value=("wf_tpl", {"name": "Template Flow", "active": True}, None))
    @patch("handlers.workflows.workflow_validator.validate_workflow")
    def test_deploy_template_route(
        self,
        mock_validate,
        _mock_deploy,
        _mock_sub,
        _mock_tool,
        mock_record,
    ) -> None:
        mock_validate.return_value = type("Result", (), {"valid": True, "warnings": [], "to_dict": lambda self: {"valid": True}})()
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
                handler = _DummyHandler({"template_id": "tpl_demo", "variables": {"channel": "ops"}})
                self.assertTrue(routes_mod.handle_post(handler, "/workflows/deploy-template"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertEqual(handler.responses[0][1]["template_id"], "tpl_demo")
        mock_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
