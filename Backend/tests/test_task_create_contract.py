from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
CONTROL_CENTER_PATH = os.path.join(REPO_ROOT, "BRIDGE", "Frontend", "control_center.html")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


class TestTaskCreateFrontendContract(unittest.TestCase):
    def test_control_center_task_create_matches_backend_schema(self):
        raw = Path(CONTROL_CENTER_PATH).read_text(encoding="utf-8")

        self.assertIn('id="aufgNewTeam"', raw)
        self.assertIn("type: document.getElementById('aufgNewType')?.value || 'general'", raw)
        self.assertIn("team: document.getElementById('aufgNewTeam')?.value || ''", raw)
        self.assertIn("created_by: 'user'", raw)
        self.assertIn("payload: {}", raw)
        self.assertNotIn("task_type: document.getElementById('aufgNewType')?.value", raw)
        self.assertNotIn('<option value="bug_fix">', raw)

        for value in ("general", "code_change", "review", "test", "research", "task"):
            self.assertIn(f'<option value="{value}">', raw)


class TestTaskCreateWorkflowBuilderContract(unittest.TestCase):
    def _mod(self):
        try:
            import workflow_builder  # type: ignore
        except ImportError as exc:
            self.fail(f"workflow_builder import failed: {exc}")
        return workflow_builder

    def test_workflow_builder_emits_backend_task_contract(self):
        mod = self._mod()
        spec = {
            "name": "Task Contract Probe",
            "nodes": [
                {
                    "id": "sched",
                    "kind": "bridge.trigger.schedule",
                    "config": {"cron": "0 9 * * *"},
                },
                {
                    "id": "make_task",
                    "kind": "bridge.action.create_task",
                    "config": {
                        "title": "Probe",
                        "description": "Check contract",
                        "task_type": "review",
                        "priority": 2,
                        "team": "team-alpha",
                        "assigned_to": "backend",
                    },
                },
            ],
            "edges": [{"from": "sched", "to": "make_task"}],
        }

        compiled = mod.compile_bridge_workflow(spec)
        params = compiled["workflow"]["nodes"][1]["parameters"]["bodyParameters"]["parameters"]
        params_by_name = {p["name"]: p["value"] for p in params}

        self.assertEqual(params_by_name["type"], "review")
        self.assertEqual(params_by_name["created_by"], "workflow")
        self.assertEqual(params_by_name["team"], "team-alpha")
        self.assertEqual(params_by_name["assigned_to"], "backend")
        self.assertNotIn("task_type", params_by_name)


if __name__ == "__main__":
    unittest.main()
