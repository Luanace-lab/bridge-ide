from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import execution_journal as journal  # noqa: E402
import server as srv  # noqa: E402


class TestExecutionServerContracts(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="execution_server_contract_")
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        journal.RUNS_BASE_DIR = self.tmpdir

    def tearDown(self):
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_server_allows_consequential_guardrail_policy_field(self):
        self.assertIn("browser_action", srv.ALLOWED_APPROVAL_ACTIONS)

    def test_execution_journal_is_readable_for_server_contract(self):
        journal.ensure_run(
            "run-contract",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-contract",
            agent_id="codex",
            engine="stealth",
        )
        journal.append_step(
            "run-contract",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            task_id="task-contract",
            agent_id="codex",
            engine="stealth",
            result_summary={"request_id": "req-123"},
        )

        listing = journal.list_runs(limit=5, source="browser", task_id="task-contract")
        payload = journal.read_run("run-contract")

        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["run_id"], "run-contract")
        self.assertEqual(listing[0]["task_id"], "task-contract")
        self.assertEqual(listing[0]["last_status"], "pending_approval")
        self.assertEqual(listing[0]["artifact_count"], 0)
        self.assertFalse(listing[0]["has_errors"])
        self.assertEqual(listing[0]["last_error"], "")
        self.assertEqual(payload["run"]["tool_name"], "bridge_browser_action")
        self.assertEqual(payload["run"]["task_id"], "task-contract")
        self.assertEqual(payload["steps"][0]["result_summary"]["request_id"], "req-123")
        self.assertEqual(payload["summary"]["step_count"], 1)
        self.assertEqual(payload["summary"]["last_status"], "pending_approval")
        self.assertFalse(payload["summary"]["has_errors"])

    def test_execution_journal_status_filter_only_returns_matching_runs(self):
        journal.ensure_run(
            "run-pending",
            source="browser",
            tool_name="bridge_browser_action",
            agent_id="codex",
        )
        journal.append_step(
            "run-pending",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            agent_id="codex",
        )
        journal.ensure_run(
            "run-success",
            source="browser",
            tool_name="bridge_browser_action",
            agent_id="codex",
        )
        journal.append_step(
            "run-success",
            source="browser",
            tool_name="bridge_browser_action",
            status="completed",
            agent_id="codex",
        )

        filtered = journal.list_runs(limit=10, source="browser", status="pending_approval")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["run_id"], "run-pending")

    def test_execution_summary_aggregates_matching_runs(self):
        journal.ensure_run(
            "run-summary-a",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-summary",
            agent_id="codex",
        )
        journal.append_step(
            "run-summary-a",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            task_id="task-summary",
            agent_id="codex",
        )
        journal.ensure_run(
            "run-summary-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            task_id="task-other",
            agent_id="codex",
        )
        journal.append_step(
            "run-summary-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            status="completed",
            task_id="task-other",
            agent_id="codex",
        )

        summary = journal.summarize_runs(agent_id="codex", task_id="task-summary")

        self.assertEqual(summary["total_runs"], 1)
        self.assertEqual(summary["total_steps"], 1)
        self.assertEqual(summary["filters"]["task_id"], "task-summary")
        self.assertEqual(summary["by_source"]["browser"], 1)
        self.assertEqual(summary["by_status"]["pending_approval"], 1)
        self.assertIn("run-summary-a", summary["recent_run_ids"])

    def test_guardrail_evaluation_contract_reports_decision(self):
        import guardrails

        tmp_policy_file = os.path.join(self.tmpdir, "guardrails.json")
        tmp_violation_file = os.path.join(self.tmpdir, "guardrails_violations.jsonl")
        orig_policy_file = guardrails.GUARDRAILS_FILE
        orig_violation_file = guardrails.VIOLATIONS_FILE
        try:
            guardrails.GUARDRAILS_FILE = tmp_policy_file
            guardrails.VIOLATIONS_FILE = tmp_violation_file
            guardrails.set_policy(
                "codex",
                {
                    "allowed_tools": ["desktop_control"],
                    "consequential_tools_mode": "explicit_allow",
                    "denied_actions": ["wipe disk"],
                },
            )
            result = guardrails.evaluate_policy(
                "codex",
                tool_name="bridge_desktop_click",
                action_text="wipe disk now",
            )
        finally:
            guardrails.GUARDRAILS_FILE = orig_policy_file
            guardrails.VIOLATIONS_FILE = orig_violation_file

        self.assertTrue(result["tool_allowed"])
        self.assertEqual(result["tool_classification"]["group"], "desktop_control")
        self.assertTrue(result["action_denied"])
        self.assertIn("wipe disk", result["action_reason"])
        self.assertIn("rate_limited", result)
        self.assertIn("rate_limit", result)


if __name__ == "__main__":
    unittest.main()
