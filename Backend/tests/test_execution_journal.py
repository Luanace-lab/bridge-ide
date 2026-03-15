from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import execution_journal as journal  # noqa: E402


class TestExecutionJournal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bridge_journal_test_")
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        journal.RUNS_BASE_DIR = self.tmpdir

    def tearDown(self):
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ensure_run_and_append_step_persist_run_state(self):
        artifact_path = os.path.join(self.tmpdir, "shot.png")
        with open(artifact_path, "wb") as handle:
            handle.write(b"png")

        run = journal.ensure_run(
            "run-1",
            source="browser",
            tool_name="bridge_browser_open",
            task_id="task-1",
            agent_id="codex",
            engine="stealth",
            session_id="sess-1",
            meta={"url": "https://example.com"},
        )
        step = journal.append_step(
            "run-1",
            source="browser",
            tool_name="bridge_browser_open",
            status="ok",
            task_id="task-1",
            agent_id="codex",
            engine="stealth",
            session_id="sess-1",
            input_summary={"url": "https://example.com"},
            result_summary={"session_id": "sess-1"},
            artifacts=[{"path": artifact_path, "kind": "screenshot"}],
        )

        loaded = journal.read_run("run-1")

        self.assertEqual(run["run_id"], "run-1")
        self.assertEqual(run["task_id"], "task-1")
        self.assertEqual(step["run_id"], "run-1")
        self.assertEqual(step["task_id"], "task-1")
        self.assertEqual(loaded["run"]["tool_name"], "bridge_browser_open")
        self.assertEqual(loaded["run"]["task_id"], "task-1")
        self.assertEqual(len(loaded["steps"]), 1)
        self.assertEqual(loaded["steps"][0]["step_id"], step["step_id"])
        self.assertTrue(loaded["steps"][0]["artifacts"][0]["exists"])
        self.assertEqual(loaded["steps"][0]["artifacts"][0]["size_bytes"], 3)

    def test_list_runs_filters_and_orders_results(self):
        artifact_path = os.path.join(self.tmpdir, "list.png")
        with open(artifact_path, "wb") as handle:
            handle.write(b"png")

        journal.ensure_run(
            "run-a",
            source="browser",
            tool_name="bridge_browser_open",
            task_id="task-a",
            agent_id="codex",
            engine="stealth",
        )
        journal.append_step(
            "run-a",
            source="browser",
            tool_name="bridge_browser_open",
            status="ok",
            task_id="task-a",
            agent_id="codex",
        )

        journal.ensure_run(
            "run-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            task_id="task-b",
            agent_id="atlas",
            engine="xdotool",
        )
        journal.append_step(
            "run-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            status="error",
            task_id="task-b",
            agent_id="atlas",
            artifacts=[{"path": artifact_path, "kind": "screenshot"}],
            error="click failed",
        )

        all_runs = journal.list_runs(limit=10)
        browser_runs = journal.list_runs(limit=10, source="browser")
        atlas_runs = journal.list_runs(limit=10, agent_id="atlas")
        task_b_runs = journal.list_runs(limit=10, task_id="task-b")
        all_by_id = {item["run_id"]: item for item in all_runs}

        self.assertEqual(len(all_runs), 2)
        self.assertEqual(len(browser_runs), 1)
        self.assertEqual(browser_runs[0]["run_id"], "run-a")
        self.assertEqual(browser_runs[0]["last_status"], "ok")
        self.assertEqual(browser_runs[0]["step_count"], 1)
        self.assertEqual(browser_runs[0]["artifact_count"], 0)
        self.assertFalse(browser_runs[0]["has_errors"])
        self.assertEqual(len(atlas_runs), 1)
        self.assertEqual(atlas_runs[0]["run_id"], "run-b")
        self.assertEqual(atlas_runs[0]["task_id"], "task-b")
        self.assertEqual(atlas_runs[0]["last_status"], "error")
        self.assertEqual(atlas_runs[0]["artifact_count"], 1)
        self.assertTrue(atlas_runs[0]["has_errors"])
        self.assertEqual(atlas_runs[0]["last_error"], "click failed")
        self.assertEqual(len(task_b_runs), 1)
        self.assertEqual(task_b_runs[0]["run_id"], "run-b")
        self.assertIn("run-b", all_by_id)

    def test_read_run_includes_client_ready_summary(self):
        artifact_path = os.path.join(self.tmpdir, "summary.png")
        with open(artifact_path, "wb") as handle:
            handle.write(b"png")

        journal.ensure_run(
            "run-summary",
            source="browser",
            tool_name="bridge_browser_action",
            agent_id="codex",
        )
        journal.append_step(
            "run-summary",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            agent_id="codex",
            artifacts=[{"path": artifact_path, "kind": "screenshot"}],
        )
        journal.append_step(
            "run-summary",
            source="browser",
            tool_name="bridge_browser_action",
            status="error",
            agent_id="codex",
            error="approval denied",
        )

        payload = journal.read_run("run-summary")

        self.assertEqual(payload["summary"]["step_count"], 2)
        self.assertEqual(payload["summary"]["status_counts"]["pending_approval"], 1)
        self.assertEqual(payload["summary"]["status_counts"]["error"], 1)
        self.assertEqual(payload["summary"]["last_status"], "error")
        self.assertEqual(payload["summary"]["artifact_count"], 1)
        self.assertTrue(payload["summary"]["has_errors"])
        self.assertEqual(payload["summary"]["last_error"], "approval denied")
        self.assertTrue(payload["summary"]["first_step_at"])
        self.assertTrue(payload["summary"]["last_step_at"])

    def test_prune_runs_supports_dry_run_and_apply(self):
        for run_id in ("old-a", "old-b", "recent"):
            journal.ensure_run(
                run_id,
                source="browser",
                tool_name="bridge_browser_action",
                agent_id="codex",
            )
            journal.append_step(
                run_id,
                source="browser",
                tool_name="bridge_browser_action",
                status="completed",
                agent_id="codex",
            )

        old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        for run_id in ("old-a", "old-b"):
            run_path = journal._run_file(run_id)
            with open(run_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["created_at"] = old_timestamp
            with open(run_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)

        preview = journal.prune_runs(max_age_hours=1, keep_latest=1, agent_id="codex", dry_run=True)

        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["matched_runs"], 3)
        self.assertEqual(preview["candidate_runs"], 2)

        applied = journal.prune_runs(max_age_hours=1, keep_latest=1, agent_id="codex", dry_run=False)
        remaining = journal.list_runs(limit=10, agent_id="codex")

        self.assertEqual(applied["pruned_runs"], 2)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["run_id"], "recent")

    def test_metrics_runs_returns_lightweight_recent_kpis(self):
        journal.ensure_run(
            "metrics-pending",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics",
            agent_id="codex",
        )
        journal.append_step(
            "metrics-pending",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics",
            status="pending_approval",
            agent_id="codex",
        )
        journal.ensure_run(
            "metrics-error",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics",
            agent_id="codex",
        )
        journal.append_step(
            "metrics-error",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics",
            status="error",
            agent_id="codex",
            error="approval denied",
        )

        metrics = journal.metrics_runs(agent_id="codex", task_id="task-metrics", window_hours=24)

        self.assertEqual(metrics["total_runs"], 2)
        self.assertEqual(metrics["total_steps"], 2)
        self.assertEqual(metrics["pending_approval_runs"], 1)
        self.assertEqual(metrics["error_runs"], 1)
        self.assertEqual(metrics["runs_with_errors"], 1)
        self.assertIn("metrics-pending", metrics["recent_run_ids"])

    def test_append_cli_session_diary_persists_artifact_and_bundle(self):
        snapshot = journal.append_cli_session_diary(
            agent_id="codex",
            session_id="acw_codex",
            engine="codex",
            workspace="/srv/project/.agent_sessions/codex",
            project_root="/srv/project",
            instruction_path="/srv/project/.agent_sessions/codex/AGENTS.md",
            resume_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            cli_identity_source="cli_register",
            event_type="pre_compact_snapshot",
            context_pct=88,
            agent_status="online",
            mode="focus",
            activity_summary="auditing: prueft diary pipeline",
            task_titles=["Audit RB3", "Review Context Bridge"],
            message_previews=["user->codex: Bitte Status geben"],
            transcript_text="line 1\nline 2\nline 3",
        )

        loaded = journal.read_run(snapshot["run_id"])
        bundle = journal.build_agent_diary_bundle(agent_id="codex", session_id="acw_codex")

        self.assertEqual(loaded["run"]["source"], journal.AGENT_DIARY_SOURCE)
        self.assertEqual(loaded["run"]["tool_name"], journal.AGENT_DIARY_TOOL)
        self.assertEqual(loaded["run"]["meta"]["workspace"], "/srv/project/.agent_sessions/codex")
        self.assertEqual(loaded["run"]["meta"]["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(loaded["steps"][0]["status"], "pre_compact_snapshot")
        self.assertEqual(loaded["steps"][0]["result_summary"]["context_pct"], 88)
        self.assertEqual(loaded["steps"][0]["result_summary"]["task_titles"][0], "Audit RB3")
        self.assertTrue(loaded["steps"][0]["artifacts"][0]["exists"])
        self.assertEqual(bundle["context_bundle_id"], snapshot["context_bundle_id"])
        self.assertEqual(bundle["workspace"], "/srv/project/.agent_sessions/codex")
        self.assertEqual(bundle["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(bundle["event_type"], "pre_compact_snapshot")
        self.assertIn("line 3", bundle["transcript_excerpt"])
        self.assertIn("auditing: prueft diary pipeline", bundle["summary"])

    def test_ensure_run_merges_non_empty_meta_for_stable_diary_run(self):
        run_id = journal._stable_agent_diary_run_id("codex", session_id="acw_codex")
        journal.ensure_run(
            run_id,
            source=journal.AGENT_DIARY_SOURCE,
            tool_name=journal.AGENT_DIARY_TOOL,
            agent_id="codex",
            meta={"run_kind": "agent_diary", "workspace": "/tmp/ws"},
        )

        updated = journal.ensure_run(
            run_id,
            source=journal.AGENT_DIARY_SOURCE,
            tool_name=journal.AGENT_DIARY_TOOL,
            agent_id="codex",
            session_id="acw_codex",
            meta={
                "instruction_path": "/tmp/ws/AGENTS.md",
                "resume_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "workspace": "/tmp/ws",
            },
        )

        self.assertEqual(updated["session_id"], "acw_codex")
        self.assertEqual(updated["meta"]["workspace"], "/tmp/ws")
        self.assertEqual(updated["meta"]["instruction_path"], "/tmp/ws/AGENTS.md")
        self.assertEqual(updated["meta"]["resume_id"], "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    def test_append_cli_session_diary_is_append_only_and_keeps_first_identity(self):
        first = journal.append_cli_session_diary(
            agent_id="codex",
            session_id="acw_codex",
            workspace="/tmp/ws_a",
            project_root="/tmp/project_a",
            instruction_path="/tmp/ws_a/AGENTS.md",
            resume_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            cli_identity_source="cli_register",
            event_type="context_bridge_snapshot",
            transcript_text="first snapshot",
        )
        second = journal.append_cli_session_diary(
            agent_id="codex",
            session_id="acw_codex",
            workspace="/tmp/ws_b",
            project_root="/tmp/project_b",
            instruction_path="/tmp/ws_b/AGENTS.md",
            resume_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            cli_identity_source="cli_reregister",
            event_type="pre_compact_snapshot",
            transcript_text="second snapshot",
        )

        loaded = journal.read_run(first["run_id"])
        bundle = journal.build_agent_diary_bundle(agent_id="codex", session_id="acw_codex")

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(loaded["summary"]["step_count"], 2)
        self.assertEqual(loaded["summary"]["artifact_count"], 2)
        self.assertEqual(loaded["run"]["meta"]["workspace"], "/tmp/ws_a")
        self.assertEqual(loaded["run"]["meta"]["project_root"], "/tmp/project_a")
        self.assertEqual(loaded["run"]["meta"]["instruction_path"], "/tmp/ws_a/AGENTS.md")
        self.assertEqual(loaded["run"]["meta"]["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(loaded["run"]["meta"]["cli_identity_source"], "cli_register")
        self.assertEqual(loaded["steps"][1]["input_summary"]["workspace"], "/tmp/ws_b")
        self.assertEqual(
            loaded["steps"][1]["input_summary"]["resume_id"],
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
        self.assertEqual(bundle["workspace"], "/tmp/ws_a")
        self.assertEqual(bundle["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(bundle["event_type"], "pre_compact_snapshot")
        self.assertIn("second snapshot", bundle["transcript_excerpt"])

    def test_build_agent_diary_bundle_is_deterministic_without_new_writes(self):
        journal.append_cli_session_diary(
            agent_id="codex",
            session_id="acw_codex",
            workspace="/tmp/ws",
            project_root="/tmp/project",
            instruction_path="/tmp/ws/AGENTS.md",
            resume_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            cli_identity_source="cli_register",
            event_type="pre_compact_snapshot",
            transcript_text="stable snapshot",
        )

        bundle_a = journal.build_agent_diary_bundle(agent_id="codex", session_id="acw_codex")
        bundle_b = journal.build_agent_diary_bundle(agent_id="codex", session_id="acw_codex")

        self.assertEqual(bundle_a, bundle_b)


if __name__ == "__main__":
    unittest.main()
