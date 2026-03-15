import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import server as srv  # noqa: E402
import handlers.workflows as wf_mod  # noqa: E402


class TestWorkflowRegistryProjection(unittest.TestCase):
    def setUp(self):
        self._orig_registry = dict(srv.WORKFLOW_REGISTRY)
        self._orig_tools = dict(srv._WORKFLOW_TOOLS)
        self._orig_save = wf_mod._save_workflow_registry
        srv.WORKFLOW_REGISTRY.clear()
        srv._WORKFLOW_TOOLS.clear()
        wf_mod._save_workflow_registry = lambda: None

    def tearDown(self):
        srv.WORKFLOW_REGISTRY.clear()
        srv.WORKFLOW_REGISTRY.update(self._orig_registry)
        srv._WORKFLOW_TOOLS.clear()
        srv._WORKFLOW_TOOLS.update(self._orig_tools)
        wf_mod._save_workflow_registry = self._orig_save

    def test_projection_uses_registry_metadata_for_bridge_builder(self):
        srv._record_workflow_deployment(
            workflow_id="wf_123",
            workflow_name="Bridge Flow",
            source="bridge_builder",
            bridge_spec={"name": "Bridge Flow", "nodes": [], "edges": []},
            bridge_subscription={"subscription_id": "sub_1"},
            tool_registered={"name": "bridge_flow__wf123abc", "workflow_id": "wf_123"},
            compiled_workflow={"name": "Bridge Flow", "nodes": [], "connections": {}},
        )

        projection = srv._workflow_projection({
            "id": "wf_123",
            "name": "Bridge Flow",
            "active": True,
            "createdAt": "2026-03-09T00:00:00Z",
            "updatedAt": "2026-03-09T00:00:00Z",
            "tags": [],
        })

        self.assertEqual(projection["source"], "bridge_builder")
        self.assertEqual(projection["type"], "Bridge Builder")
        self.assertTrue(projection["bridge_managed"])
        self.assertTrue(projection["definition_available"])
        self.assertTrue(projection["tool_registered"])
        self.assertTrue(projection["subscription_registered"])

    def test_record_and_remove_workflow_deployment_updates_tool_cache(self):
        record = srv._record_workflow_deployment(
            workflow_id="wf_tpl",
            workflow_name="Template Flow",
            source="template",
            template_id="daily-report",
            bridge_spec={"kind": "template_deploy", "template_id": "daily-report"},
            tool_registered={
                "name": "template_flow__wf_tpl",
                "workflow_name": "Template Flow",
                "workflow_id": "wf_tpl",
                "webhook_url": "http://localhost:5678/webhook/template",
            },
            compiled_workflow={"name": "Template Flow", "nodes": [], "connections": {}},
            variables_used={"channel": "ops"},
        )

        self.assertEqual(record["variables_used"], {"channel": "ops"})
        self.assertIn("template_flow__wf_tpl", srv._WORKFLOW_TOOLS)

        removed = srv._remove_workflow_record("wf_tpl")
        self.assertIsNotNone(removed)
        self.assertEqual(removed["template_id"], "daily-report")
        self.assertNotIn("template_flow__wf_tpl", srv._WORKFLOW_TOOLS)

    def test_delete_cleanup_keeps_shared_subscription_for_deduplicated_records(self):
        cleanup = srv._workflow_delete_cleanup({
            "bridge_subscription": {
                "subscription_id": "sub_shared",
                "deduplicated": True,
            },
            "tool_registered": {
                "name": "shared_tool__wf123",
            },
        })

        self.assertEqual(cleanup["event_subscription_id"], "sub_shared")
        self.assertTrue(cleanup["event_subscription_shared"])
        self.assertEqual(cleanup["tool_removed"], "shared_tool__wf123")
        self.assertNotIn("event_subscription_deleted", cleanup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
