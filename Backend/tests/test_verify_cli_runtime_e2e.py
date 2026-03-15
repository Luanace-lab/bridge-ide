from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND_DIR.parent / "config" / "mcp_catalog.json"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import verify_cli_runtime_e2e as harness  # noqa: E402


def _write_threads_db(db_path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source,
                model_provider, cwd, title, sandbox_policy, approval_mode
            ) VALUES (?, ?, ?, ?, 'cli', 'openai', ?, 'thread', 'workspace-write', 'never')
            """,
            [(sid, rollout_path, created_at, created_at, cwd) for sid, cwd, created_at, rollout_path in rows],
        )
        conn.commit()
    finally:
        conn.close()


class TestVerifyCliRuntimeE2EHelpers(unittest.TestCase):
    @staticmethod
    def _decorated_success_result(workspace: Path) -> dict[str, object]:
        return harness._decorate_result(
            {
                "engine": "codex",
                "workspace": str(workspace),
                "shell": {"command": [], "returncode": 0, "stdout_tail": [], "stderr_tail": []},
                "prompt_ready": True,
                "slash_ok": True,
                "probe_listed": True,
                "probe_marker_seen": True,
                "interactive": {},
                "session_log": str(workspace / "session_0.log"),
                "session_logs": [str(workspace / "session_0.log")],
                "cycles": [],
                "cli_sot": {
                    "config_paths": [str(workspace / ".codex" / "config.toml")],
                    "config_present": {str(workspace / ".codex" / "config.toml"): True},
                    "state_roots": [str(workspace / ".codex-home")],
                    "state_roots_present": {str(workspace / ".codex-home"): True},
                    "session_artifact_count": 2,
                    "session_artifacts_tail": [],
                    "resume_candidates": ["sid-1"],
                    "thread_rows": [],
                    "rollout_rows": [],
                },
                "cli_sot_ok": True,
                "memory_context": {
                    "markers": {
                        "agents_marker": "AGENTS-1",
                        "memory_marker": "MEMORY-1",
                        "context_marker": "CONTEXT-1",
                    },
                    "cycle_results": [
                        {
                            "cycle_index": 0,
                            "markers_read": {
                                "agents_marker": "AGENTS-1",
                                "memory_marker": "MEMORY-1",
                                "context_marker": "CONTEXT-1",
                            },
                        }
                    ],
                    "marker_reads_ok": True,
                    "restore_consistent": False,
                    "restore_attempted": False,
                    "canonical_paths_unchanged": True,
                    "drift_paths_unchanged": True,
                    "cwd_matches_workspace": True,
                    "probe_marker_consistent": True,
                },
                "persistence": {
                    "before_restart": {
                        "resume_candidates": ["sid-1"],
                    },
                    "after_restart": {
                        "resume_candidates": ["sid-1"],
                    },
                    "stable_state_roots": True,
                    "config_paths_persisted": True,
                    "state_roots_present_after_restart": True,
                    "session_artifacts_non_decreasing": True,
                    "resume_candidates_preserved": True,
                },
                "persistence_ok": True,
                "restart_ok": True,
                "all_cycles_ok": True,
                "progress": {"phase": "cycle_0_completed", "cycle_index": 0},
            }
        )

    def test_native_state_snapshot_collects_codex_resume_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "project" / ".agent_sessions" / "codex"
            codex_home = workspace / ".codex-home"
            (workspace / ".codex").mkdir(parents=True, exist_ok=True)
            codex_home.mkdir(parents=True, exist_ok=True)
            (workspace / ".codex" / "config.toml").write_text("mode = 'test'\n", encoding="utf-8")
            (codex_home / "config.toml").write_text("mode = 'test'\n", encoding="utf-8")

            session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            rollout_dir = codex_home / "sessions" / "2026" / "03" / "11"
            rollout_dir.mkdir(parents=True, exist_ok=True)
            rollout_path = rollout_dir / f"rollout-2026-03-11T08-00-00-{session_id}.jsonl"
            rollout_payload = {
                "timestamp": "2026-03-11T08:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-03-11T08:00:00.000Z",
                    "cwd": str(workspace),
                    "originator": "codex_cli_rs",
                },
            }
            rollout_path.write_text(json.dumps(rollout_payload) + "\n", encoding="utf-8")
            _write_threads_db(
                codex_home / "state_5.sqlite",
                [(session_id, str(workspace), 200, str(rollout_path))],
            )

            scenario = harness.Scenario(engine="codex", slash_commands=("/",))
            with mock.patch.object(harness, "_codex_home_dir", return_value=codex_home):
                snapshot = harness._native_state_snapshot(scenario, workspace)

            self.assertTrue(snapshot["config_present"][str(workspace / ".codex" / "config.toml")])
            self.assertTrue(snapshot["config_present"][str(codex_home / "config.toml")])
            self.assertTrue(snapshot["state_roots_present"][str(codex_home)])
            self.assertIn(session_id, snapshot["resume_candidates"])
            self.assertGreaterEqual(snapshot["session_artifact_count"], 2)

    def test_run_scenario_reports_restart_and_persistence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "codex_runtime"
            workspace.mkdir(parents=True, exist_ok=True)
            scenario = harness.Scenario(
                engine="codex",
                slash_commands=("/",),
                shell_list_command=("codex", "mcp", "list"),
            )
            cli_sot = {
                "config_paths": [str(workspace / ".codex" / "config.toml")],
                "config_present": {str(workspace / ".codex" / "config.toml"): True},
                "state_roots": [str(workspace / ".codex-home")],
                "state_roots_present": {str(workspace / ".codex-home"): True},
                "session_artifact_count": 0,
                "session_artifacts_tail": [],
                "resume_candidates": [],
                "thread_rows": [],
                "rollout_rows": [],
            }
            before_restart = {
                **cli_sot,
                "session_artifact_count": 1,
                "resume_candidates": ["sid-1"],
            }
            after_restart = {
                **cli_sot,
                "session_artifact_count": 2,
                "resume_candidates": ["sid-1", "sid-2"],
            }

            def cycle(idx: int) -> dict[str, object]:
                return {
                    "cycle_index": idx,
                    "prompt_ready": True,
                    "slash_ok": True,
                    "probe_listed": True,
                    "probe_marker_seen": True,
                    "interactive": {"commands": []},
                    "memory_context": {
                        "result_seen": True,
                        "markers_read": {
                            "agents_marker": "AGENTS-1",
                            "memory_marker": "MEMORY-1",
                            "context_marker": "CONTEXT-1",
                        },
                        "expected_markers": {
                            "agents_marker": "AGENTS-1",
                            "memory_marker": "MEMORY-1",
                            "context_marker": "CONTEXT-1",
                        },
                        "matches_expected": True,
                        "canonical_observation": {"workspace_memory": {"path": "/tmp/demo/MEMORY.md", "exists": True, "size": 1, "sha256": "abc"}},
                        "drift_observation": {"root_memory": {"path": "/tmp/demo-root/MEMORY.md", "exists": True, "size": 1, "sha256": "def"}},
                    },
                    "prompt_capture_tail": [],
                    "session_log": str(workspace / f"session_{idx}.log"),
                }

            with (
                mock.patch.object(harness, "_prepare_workspace", return_value=(workspace, {}, "")),
                mock.patch.object(
                    harness,
                    "_seed_memory_context_drill",
                    return_value={
                        "markers": {
                            "agents_marker": "AGENTS-1",
                            "memory_marker": "MEMORY-1",
                            "context_marker": "CONTEXT-1",
                        },
                        "canonical_paths": {"workspace_memory": str(workspace / "MEMORY.md")},
                        "drift_paths": {"root_memory": str(root / "MEMORY.md")},
                        "baseline": {
                            "canonical": {"workspace_memory": {"path": str(workspace / "MEMORY.md"), "exists": True, "size": 1, "sha256": "abc"}},
                            "drift": {"root_memory": {"path": str(root / "MEMORY.md"), "exists": True, "size": 1, "sha256": "def"}},
                        },
                    },
                ),
                mock.patch.object(
                    harness,
                    "_shell_list",
                    return_value={
                        "command": ["codex", "mcp", "list"],
                        "returncode": 0,
                        "stdout_tail": ["probe"],
                        "stderr_tail": [],
                    },
                ),
                mock.patch.object(
                    harness,
                    "_native_state_snapshot",
                    side_effect=[cli_sot, before_restart, after_restart],
                ),
                mock.patch.object(harness, "_run_cycle", side_effect=[cycle(0), cycle(1)]),
            ):
                result = harness.run_scenario(scenario, root, restart_count=1)

            self.assertTrue(result["cli_sot_ok"])
            self.assertTrue(result["memory_context"]["marker_reads_ok"])
            self.assertTrue(result["memory_context"]["restore_consistent"])
            self.assertTrue(result["restart_ok"])
            self.assertTrue(result["persistence_ok"])
            self.assertTrue(result["all_cycles_ok"])
            self.assertEqual(result["session_logs"], [str(workspace / "session_0.log"), str(workspace / "session_1.log")])
            self.assertEqual(len(result["cycles"]), 2)

    def test_scenario_failure_result_is_structured(self) -> None:
        scenario = harness.Scenario(engine="codex", slash_commands=("/",))
        with tempfile.TemporaryDirectory() as tmpdir:
            result = harness._scenario_failure_result(scenario, Path(tmpdir), RuntimeError("boom"))

        self.assertEqual(result["engine"], "codex")
        self.assertEqual(result["error"], "RuntimeError: boom")
        self.assertFalse(result["cli_sot_ok"])
        self.assertFalse(result["persistence_ok"])
        self.assertFalse(result["restart_ok"])

    def test_start_session_kills_tmux_session_when_startup_raises(self) -> None:
        scenario = harness.Scenario(engine="codex", slash_commands=("/",))
        tmux_calls: list[list[str]] = []

        def fake_tmux(args: list[str], *, timeout: int = 30):
            del timeout
            tmux_calls.append(args)
            return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "codex_runtime"
            workspace.mkdir(parents=True, exist_ok=True)
            log_path = workspace / "session_0.log"
            with (
                mock.patch.object(harness, "_tmux", side_effect=fake_tmux),
                mock.patch.object(harness, "_stabilize_codex_startup", side_effect=RuntimeError("startup boom")),
            ):
                with self.assertRaisesRegex(RuntimeError, "startup boom"):
                    harness._start_session(
                        scenario,
                        workspace,
                        session_name="bridge_codex_deadbeef",
                        start_prefix="",
                        log_path=log_path,
                        cycle_index=0,
                    )

        self.assertIn(["kill-session", "-t", "bridge_codex_deadbeef"], tmux_calls)

    def test_execute_scenario_timeout_returns_fail_with_progress(self) -> None:
        scenario = harness.Scenario(engine="codex", slash_commands=("/",))
        scenario_state = {"engine": "codex", "status": "running", "progress": {"phase": "queued"}}
        payload = {
            "generated_at": "2026-03-11T00:00:00Z",
            "last_updated_at": "2026-03-11T00:00:00Z",
            "status": "running",
            "probe_marker": "bridge-live-probe",
            "engines": ["codex"],
            "restart_count": 1,
            "scenario_timeout": 1,
            "results": [scenario_state],
        }

        def fake_run_scenario(*args, **kwargs):
            progress_callback = kwargs["progress_callback"]
            progress_callback(phase="shell_list_started", workspace="/tmp/demo")
            time.sleep(2)
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"
            with mock.patch.object(harness, "run_scenario", side_effect=fake_run_scenario):
                result = harness._execute_scenario(
                    scenario,
                    Path(tmpdir),
                    restart_count=1,
                    scenario_timeout=1,
                    scenario_state=scenario_state,
                    payload=payload,
                    json_output=str(report_path),
                )

        self.assertEqual(result["signal"], "FAIL")
        self.assertIn("ScenarioTimeoutError", result["error"])
        self.assertEqual(result["progress"]["phase"], "shell_list_started")

    def test_decorate_result_builds_nine_point_matrix(self) -> None:
        result = self._decorated_success_result(Path("/tmp/demo"))

        self.assertEqual(result["signal"], "SUCCESS")
        self.assertEqual(len(result["verification_matrix"]), 9)
        self.assertIn(1, result["verified_points"])
        self.assertIn(8, result["verified_points"])
        self.assertTrue(all(entry["status"] in {"SUCCESS", "FAIL", "BLOCKED"} for entry in result["verification_matrix"]))

    def test_apply_verification_summary_collects_open_points(self) -> None:
        payload = {"results": [self._decorated_success_result(Path("/tmp/demo"))]}

        harness._apply_verification_summary(payload)

        self.assertEqual(len(payload["verification_summary"]), 9)
        self.assertEqual(payload["verification_summary"][0]["status"], "SUCCESS")
        self.assertTrue(any(entry["point"] == 3 for entry in payload["open_not_verified_points"]))

    def test_main_uses_execute_scenario_without_prerunning_run_scenario(self) -> None:
        scenario = harness.Scenario(engine="codex", slash_commands=("/",))
        observed: dict[str, object] = {}

        def fake_execute_scenario(*args, **kwargs):
            root = args[1]
            report_path = Path(kwargs["json_output"])
            observed["preexisting_report"] = json.loads(report_path.read_text(encoding="utf-8"))
            return self._decorated_success_result(Path(root) / "codex_runtime")

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"
            workspace_root = Path(tmpdir) / "workspaces"
            argv = [
                "verify_cli_runtime_e2e.py",
                "--engines",
                "codex",
                "--restart-count",
                "1",
                "--scenario-timeout",
                "5",
                "--workspace-root",
                str(workspace_root),
                "--json-output",
                str(report_path),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(harness, "_selected_scenarios", return_value=[scenario]),
                mock.patch.object(
                    harness,
                    "run_scenario",
                    side_effect=AssertionError("run_scenario should not be called directly from main"),
                ),
                mock.patch.object(harness, "_execute_scenario", side_effect=fake_execute_scenario) as execute_mock,
            ):
                exit_code = harness.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(execute_mock.call_count, 1)
        preexisting_report = observed["preexisting_report"]
        self.assertEqual(preexisting_report["status"], "running")
        self.assertEqual(preexisting_report["results"][0]["status"], "running")
        self.assertEqual(preexisting_report["results"][0]["progress"]["phase"], "scheduled")

    def test_decorate_result_uses_persisted_resume_candidates_and_blocks_restart_without_restart_cycle(self) -> None:
        result = self._decorated_success_result(Path("/tmp/demo"))

        point_2 = next(entry for entry in result["verification_matrix"] if entry["point"] == 2)
        point_6 = next(entry for entry in result["verification_matrix"] if entry["point"] == 6)

        self.assertEqual(point_2["status"], "SUCCESS")
        self.assertEqual(point_6["status"], "BLOCKED")

    def test_memory_context_summary_reports_restore_consistency(self) -> None:
        drill = {
            "markers": {
                "agents_marker": "AGENTS-1",
                "memory_marker": "MEMORY-1",
                "context_marker": "CONTEXT-1",
            },
            "canonical_paths": {"workspace_memory": "/tmp/demo/MEMORY.md"},
            "drift_paths": {"root_memory": "/tmp/demo-root/MEMORY.md"},
            "baseline": {
                "canonical": {"workspace_memory": {"path": "/tmp/demo/MEMORY.md", "exists": True, "size": 1, "sha256": "abc"}},
                "drift": {"root_memory": {"path": "/tmp/demo-root/MEMORY.md", "exists": True, "size": 1, "sha256": "def"}},
            },
        }
        cycles = [
            {
                "cycle_index": 0,
                "memory_context": {
                    "markers_read": drill["markers"],
                    "matches_expected": True,
                    "probe_marker_ok": True,
                    "cwd_matches_workspace": True,
                    "canonical_observation": drill["baseline"]["canonical"],
                    "drift_observation": drill["baseline"]["drift"],
                },
            },
            {
                "cycle_index": 1,
                "memory_context": {
                    "markers_read": drill["markers"],
                    "matches_expected": True,
                    "probe_marker_ok": True,
                    "cwd_matches_workspace": True,
                    "canonical_observation": drill["baseline"]["canonical"],
                    "drift_observation": drill["baseline"]["drift"],
                },
            },
        ]

        summary = harness._memory_context_summary(drill, cycles)

        self.assertTrue(summary["marker_reads_ok"])
        self.assertTrue(summary["restore_attempted"])
        self.assertTrue(summary["restore_consistent"])
        self.assertTrue(summary["canonical_paths_unchanged"])
        self.assertTrue(summary["drift_paths_unchanged"])
        self.assertTrue(summary["cwd_matches_workspace"])
        self.assertTrue(summary["probe_marker_consistent"])

    def test_decorate_result_marks_point_three_success_when_memory_context_restores_cleanly(self) -> None:
        result = harness._decorate_result(
            {
                **self._decorated_success_result(Path("/tmp/demo")),
                "cycles": [
                    {"cycle_index": 0},
                    {"cycle_index": 1},
                ],
                "memory_context": {
                    "markers": {
                        "agents_marker": "AGENTS-1",
                        "memory_marker": "MEMORY-1",
                        "context_marker": "CONTEXT-1",
                    },
                    "marker_reads_ok": True,
                    "restore_consistent": True,
                    "restore_attempted": True,
                    "canonical_paths_unchanged": True,
                    "drift_paths_unchanged": True,
                    "cwd_matches_workspace": True,
                    "probe_marker_consistent": True,
                },
            }
        )

        point_3 = next(entry for entry in result["verification_matrix"] if entry["point"] == 3)
        self.assertEqual(point_3["status"], "SUCCESS")

    def test_run_cycle_uses_codex_exec_path_for_codex(self) -> None:
        scenario = harness.Scenario(engine="codex", slash_commands=("/",))
        expected = {
            "cycle_index": 0,
            "prompt_ready": True,
            "slash_ok": True,
            "probe_listed": True,
            "probe_marker_seen": True,
            "interactive": {},
            "memory_context": {},
            "prompt_capture_tail": [],
            "session_log": "/tmp/session_0.log",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "codex_runtime"
            workspace.mkdir(parents=True, exist_ok=True)
            with mock.patch.object(harness, "_run_codex_exec_cycle", return_value=expected) as exec_mock:
                result = harness._run_cycle(
                    scenario,
                    workspace,
                    {},
                    cycle_index=0,
                    start_prefix="",
                    drill={"markers": {}},
                )

        self.assertEqual(result, expected)
        self.assertEqual(exec_mock.call_count, 1)

    def test_ensure_codex_exec_auth_symlinks_home_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir) / ".codex-home"
            auth_src = Path(tmpdir) / ".codex" / "auth.json"
            auth_src.parent.mkdir(parents=True, exist_ok=True)
            auth_src.write_text("{\"token\":\"demo\"}\n", encoding="utf-8")
            with mock.patch.object(harness.Path, "home", return_value=Path(tmpdir)):
                auth_dst = harness._ensure_codex_exec_auth(codex_home)

            self.assertTrue(auth_dst.is_symlink())
            self.assertEqual(auth_dst.resolve(), auth_src.resolve())

    def test_decorate_result_marks_restart_point_failed_after_cycle_one_timeout(self) -> None:
        result = harness._decorate_result(
            {
                "engine": "codex",
                "workspace": "/tmp/demo",
                "error": "ScenarioTimeoutError: scenario codex exceeded 20s during cycle_1_startup_stabilizing",
                "shell": {"command": [], "returncode": 0, "stdout_tail": [], "stderr_tail": []},
                "prompt_ready": False,
                "slash_ok": False,
                "probe_listed": False,
                "probe_marker_seen": False,
                "interactive": {},
                "session_log": "",
                "session_logs": [],
                "cycles": [],
                "cli_sot": {
                    "config_paths": ["/tmp/demo/.codex/config.toml"],
                    "config_present": {"/tmp/demo/.codex/config.toml": True},
                    "state_roots": ["/tmp/demo/.codex-home"],
                    "state_roots_present": {"/tmp/demo/.codex-home": True},
                    "session_artifact_count": 1,
                    "session_artifacts_tail": [],
                    "resume_candidates": ["sid-1"],
                    "thread_rows": [],
                    "rollout_rows": [],
                },
                "cli_sot_ok": True,
                "persistence": {},
                "persistence_ok": False,
                "restart_ok": False,
                "all_cycles_ok": False,
                "progress": {"phase": "cycle_1_startup_stabilizing", "cycle_index": 1},
            }
        )

        point_6 = next(entry for entry in result["verification_matrix"] if entry["point"] == 6)
        self.assertEqual(point_6["status"], "FAIL")


@pytest.mark.skipif(
    os.environ.get("BRIDGE_RUN_LIVE_TESTS") != "1",
    reason="manual live harness test; set BRIDGE_RUN_LIVE_TESTS=1 to enable",
)
@pytest.mark.skipif(
    shutil.which("tmux") is None or shutil.which("codex") is None,
    reason="requires tmux and codex CLI",
)
@pytest.mark.skipif(
    not CATALOG_PATH.exists(),
    reason="requires config/mcp_catalog.json",
)
def test_live_codex_restart_contract(tmp_path: Path) -> None:
    report_path = tmp_path / "codex_restart_report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_DIR / "verify_cli_runtime_e2e.py"),
            "--engines",
            "codex",
            "--restart-count",
            "1",
            "--scenario-timeout",
            "60",
            "--workspace-root",
            str(tmp_path / "workspaces"),
            "--json-output",
            str(report_path),
        ],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert report_path.exists(), result.stdout + "\n" + result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["engines"] == ["codex"]
    assert payload["restart_count"] == 1
    assert payload["scenario_timeout"] == 60
    assert len(payload["results"]) == 1

    codex_result = payload["results"][0]
    assert codex_result["engine"] == "codex"
    assert codex_result["signal"] in {"SUCCESS", "FAIL", "BLOCKED"}
    assert len(codex_result["verification_matrix"]) == 9
    assert isinstance(codex_result["open_not_verified_points"], list)
