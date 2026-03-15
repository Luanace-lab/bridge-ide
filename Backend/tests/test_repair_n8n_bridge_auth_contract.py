import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


import repair_n8n_bridge_auth as repair  # noqa: E402


class TestRepairN8nBridgeAuthContract(unittest.TestCase):
    def test_workflow_requires_repair_for_local_bridge_write_without_header(self):
        workflow = {
            "id": "wf1",
            "name": "Needs Repair",
            "nodes": [
                {
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {
                        "method": "POST",
                        "url": "http://localhost:9111/send",
                    },
                }
            ],
            "connections": {},
        }

        self.assertTrue(repair._workflow_requires_bridge_auth_repair(workflow))

    def test_workflow_does_not_require_repair_for_read_only_bridge_call(self):
        workflow = {
            "id": "wf2",
            "name": "Read Only",
            "nodes": [
                {
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {
                        "method": "GET",
                        "url": "http://localhost:9111/agents",
                    },
                }
            ],
            "connections": {},
        }

        self.assertFalse(repair._workflow_requires_bridge_auth_repair(workflow))

    @patch("repair_n8n_bridge_auth.server._update_workflow_in_n8n")
    @patch("repair_n8n_bridge_auth.server._n8n_request")
    def test_repair_workflows_only_updates_changed_active_workflows(self, mock_request, mock_update):
        mock_request.return_value = (
            200,
            {
                "data": [
                    {
                        "id": "wf1",
                        "name": "Needs Repair",
                        "active": True,
                        "nodes": [
                            {
                                "type": "n8n-nodes-base.httpRequest",
                                "parameters": {"method": "POST", "url": "http://localhost:9111/send"},
                            }
                        ],
                        "connections": {},
                    },
                    {
                        "id": "wf2",
                        "name": "No Repair",
                        "active": True,
                        "nodes": [
                            {
                                "type": "n8n-nodes-base.httpRequest",
                                "parameters": {"method": "GET", "url": "http://localhost:9111/agents"},
                            }
                        ],
                        "connections": {},
                    },
                    {
                        "id": "wf3",
                        "name": "Inactive",
                        "active": False,
                        "nodes": [
                            {
                                "type": "n8n-nodes-base.httpRequest",
                                "parameters": {"method": "POST", "url": "http://localhost:9111/send"},
                            }
                        ],
                        "connections": {},
                    },
                ]
            },
        )

        result = repair.repair_workflows(limit=10, active_only=True, dry_run=False)

        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["repaired_count"], 1)
        self.assertEqual(result["repaired"][0]["id"], "wf1")
        self.assertEqual(result["unchanged_count"], 1)
        mock_update.assert_called_once()

    @patch("repair_n8n_bridge_auth.server._n8n_request")
    def test_repair_workflows_dry_run_skips_updates(self, mock_request):
        mock_request.return_value = (
            200,
            {
                "data": [
                    {
                        "id": "wf1",
                        "name": "Needs Repair",
                        "active": True,
                        "nodes": [
                            {
                                "type": "n8n-nodes-base.httpRequest",
                                "parameters": {"method": "POST", "url": "http://localhost:9111/send"},
                            }
                        ],
                        "connections": {},
                    }
                ]
            },
        )

        with patch("repair_n8n_bridge_auth.server._update_workflow_in_n8n") as mock_update:
            result = repair.repair_workflows(limit=10, active_only=True, dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["repaired_count"], 1)
        mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
