from __future__ import annotations

import os
from pathlib import Path
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "Frontend"))


class TestAutomationUiServerContract(unittest.TestCase):
    def test_control_center_uses_canonical_event_names_and_overdue_condition(self) -> None:
        raw = Path(os.path.join(FRONTEND_DIR, "control_center.html")).read_text(encoding="utf-8")
        self.assertIn("task_overdue", raw)
        self.assertIn("eventType: 'task.created'", raw)
        self.assertIn("eventType: 'task.done'", raw)
        self.assertIn("eventType: 'agent.online'", raw)
        self.assertNotIn("eventType: 'task_created'", raw)
        self.assertNotIn("eventType: 'task_done'", raw)
        self.assertNotIn("eventType: 'agent_online'", raw)

    def test_server_exposes_local_automation_webhook_and_condition_context(self) -> None:
        raw = Path(os.path.join(BACKEND_DIR, "server.py")).read_text(encoding="utf-8")
        startup_raw = Path(os.path.join(BACKEND_DIR, "server_startup.py")).read_text(encoding="utf-8")
        self.assertIn('re.match(r"^/automations/([^/]+)/webhook$"', raw)
        self.assertIn("condition_context_callback=_automation_condition_context", startup_raw)


if __name__ == "__main__":
    unittest.main()
