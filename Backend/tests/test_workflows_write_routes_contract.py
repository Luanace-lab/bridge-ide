from __future__ import annotations

import os
import sys
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


class TestWorkflowsWriteRoutesContract(unittest.TestCase):
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
        routes_mod.WORKFLOW_REGISTRY.clear()
        routes_mod.WORKFLOW_REGISTRY["wf_1"] = {
            "workflow_id": "wf_1",
            "source": "bridge_builder",
            "bridge_subscription": {"subscription_id": "sub_old"},
            "bridge_spec": {"name": "Old"},
        }

    def tearDown(self) -> None:
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

    @patch("handlers.workflows._n8n_request")
    def test_toggle_route(self, mock_request) -> None:
        mock_request.side_effect = [(200, {"id": "wf_1"}), (200, {"active": True})]
        handler = _DummyHandler({"active": True})
        self.assertTrue(routes_mod.handle_patch(handler, "/workflows/wf_1/toggle"))
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.responses[0][1]["workflow"]["id"], "wf_1")

    @patch("handlers.workflows._record_workflow_deployment")
    @patch("handlers.workflows._register_workflow_webhook_tool", return_value={"name": "tool_1"})
    @patch("handlers.workflows._register_workflow_subscription", return_value={"subscription_id": "sub_new"})
    @patch("handlers.workflows.event_bus.unsubscribe")
    @patch("handlers.workflows._update_workflow_in_n8n", return_value=({"name": "Updated Flow", "active": True}, None))
    @patch("handlers.workflows.workflow_builder.compile_bridge_workflow")
    def test_put_definition_route(
        self,
        mock_compile,
        _mock_update,
        mock_unsub,
        _mock_register_sub,
        _mock_register_tool,
        mock_record,
    ) -> None:
        mock_compile.return_value = {
            "workflow": {"name": "Updated Flow", "nodes": [], "connections": {}},
            "validation": {"valid": True},
            "bridge_subscription": {"event_type": "task.created"},
        }
        handler = _DummyHandler({"definition": {"name": "Updated Flow", "nodes": [], "edges": []}})
        self.assertTrue(routes_mod.handle_put(handler, "/workflows/wf_1/definition"))
        self.assertEqual(handler.responses[0][0], 200)
        mock_unsub.assert_called_once_with("sub_old")
        mock_record.assert_called_once()

    @patch("handlers.workflows._remove_workflow_record", return_value={"workflow_id": "wf_1"})
    @patch("handlers.workflows._workflow_delete_cleanup", return_value={"tool_removed": "tool_1"})
    @patch("handlers.workflows._n8n_request", return_value=(200, {"ok": True}))
    def test_delete_route(self, _mock_request, _mock_cleanup, mock_remove) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_delete(handler, "/workflows/wf_1"))
        self.assertEqual(handler.responses[0][0], 200)
        mock_remove.assert_called_once_with("wf_1")


if __name__ == "__main__":
    unittest.main()
