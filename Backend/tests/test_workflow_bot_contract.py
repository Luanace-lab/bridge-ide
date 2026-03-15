import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWorkflowBotContract(unittest.TestCase):
    def _mod(self):
        try:
            import workflow_bot  # type: ignore
        except ImportError as exc:
            self.fail(f"workflow_bot import failed: {exc}")
        return workflow_bot

    def test_create_intent_returns_template_variables_for_ui_forms(self):
        mod = self._mod()
        result = mod.detect_workflow_intent("workflow erstellen wochenreport")

        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "create_workflow")
        templates = result["suggested_templates"]
        self.assertGreaterEqual(len(templates), 1)

        first = templates[0]
        self.assertEqual(first["template_id"], "tpl_weekly_report")
        self.assertIn("variables", first)
        self.assertGreater(len(first["variables"]), 0)
        self.assertEqual(first["variables"][0]["key"], "day_of_week")


if __name__ == "__main__":
    unittest.main(verbosity=2)
