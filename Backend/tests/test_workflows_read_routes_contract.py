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
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


class TestWorkflowsReadRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        routes_mod.init(
            get_port_fn=lambda: 9111,
            get_bridge_user_token_fn=lambda: "test-token",
            get_auth_tier2_post_paths_fn=lambda: set(),
            get_auth_tier3_post_paths_fn=lambda: set(),
            get_auth_tier3_patterns_fn=lambda: [],
            utc_now_iso_fn=lambda: "2026-03-15T00:00:00+00:00",
        )
        self._orig_registry = dict(routes_mod.WORKFLOW_REGISTRY)
        self._orig_tools = dict(routes_mod._WORKFLOW_TOOLS)

    def tearDown(self) -> None:
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

    @patch("handlers.workflows._n8n_request")
    def test_n8n_and_workflow_list_routes(self, mock_request) -> None:
        mock_request.side_effect = [
            (200, {"data": [{"id": "exec_1"}]}),
            (200, {"data": [{"id": "wf_1", "name": "Flow", "active": True, "tags": []}]}),
        ]
        execution_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(execution_handler, "/n8n/executions", {"limit": ["10"]}))
        self.assertEqual(execution_handler.responses[0][1]["data"][0]["id"], "exec_1")

        routes_mod.WORKFLOW_REGISTRY["wf_1"] = {
            "workflow_id": "wf_1",
            "source": "bridge_builder",
            "bridge_spec": {"name": "Flow"},
            "tool_registered": {"name": "flow__wf_1"},
        }
        workflow_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(workflow_handler, "/workflows", {"limit": ["20"]}))
        self.assertEqual(workflow_handler.responses[0][1]["count"], 1)
        self.assertTrue(workflow_handler.responses[0][1]["workflows"][0]["bridge_managed"])

    def test_definition_tools_templates_and_suggest(self) -> None:
        routes_mod.WORKFLOW_REGISTRY["wf_2"] = {
            "workflow_id": "wf_2",
            "source": "template",
            "template_id": "daily-report",
            "bridge_spec": {"name": "Template Flow"},
            "compiled_workflow": {"name": "Compiled"},
            "variables_used": {"channel": "ops"},
        }
        routes_mod._WORKFLOW_TOOLS["tool_1"] = {"name": "tool_1", "workflow_id": "wf_2"}

        definition_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(definition_handler, "/workflows/wf_2/definition", {}))
        self.assertEqual(definition_handler.responses[0][1]["template_id"], "daily-report")

        tools_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(tools_handler, "/workflows/tools", {}))
        self.assertEqual(tools_handler.responses[0][1]["count"], 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "template.json")
            with open(template_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "template_id": "tpl_demo",
                        "name": "Demo",
                        "description": "Demo template",
                        "category": "ops",
                        "difficulty": "easy",
                        "icon": "tool",
                        "variables": [{"key": "channel"}],
                        "setup_steps": ["Step 1"],
                    },
                    handle,
                )
            with patch.object(routes_mod, "WORKFLOW_TEMPLATES_DIR", tmpdir):
                template_handler = _DummyHandler()
                self.assertTrue(routes_mod.handle_get(template_handler, "/workflows/templates", {}))
                self.assertEqual(template_handler.responses[0][1]["count"], 1)

        with patch("handlers.workflows.workflow_bot.detect_workflow_intent", return_value={"intent": "create_workflow"}):
            with patch("handlers.workflows.workflow_bot.format_create_response", return_value="formatted"):
                suggest_handler = _DummyHandler()
                self.assertTrue(routes_mod.handle_get(suggest_handler, "/workflows/suggest", {"message": ["report"]}))
                self.assertEqual(suggest_handler.responses[0][1]["formatted_response"], "formatted")

        missing_message_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(missing_message_handler, "/workflows/suggest", {}))
        self.assertEqual(missing_message_handler.responses[0][0], 400)


if __name__ == "__main__":
    unittest.main()
