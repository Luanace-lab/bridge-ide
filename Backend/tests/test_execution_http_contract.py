from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import capability_library  # noqa: E402
import execution_journal as journal  # noqa: E402
import guardrails  # noqa: E402
import server as srv  # noqa: E402


class TestExecutionHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="execution_http_contract_")
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        self._orig_guardrails_file = guardrails.GUARDRAILS_FILE
        self._orig_violations_file = guardrails.VIOLATIONS_FILE
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_session_tokens = dict(srv.SESSION_TOKENS)
        self._orig_library_env = os.environ.get("BRIDGE_CAPABILITY_LIBRARY_PATH")

        journal.RUNS_BASE_DIR = os.path.join(self._tmpdir, "execution_runs")
        guardrails.GUARDRAILS_FILE = os.path.join(self._tmpdir, "guardrails.json")
        guardrails.VIOLATIONS_FILE = os.path.join(self._tmpdir, "guardrails_violations.jsonl")
        srv.BRIDGE_STRICT_AUTH = False
        srv.SESSION_TOKENS.clear()
        srv.TEAM_CONFIG = {
            "agents": [
                {"id": "manager", "level": 1, "active": True},
                {"id": "codex", "level": 3, "active": True},
            ]
        }
        sample_library = {
            "metadata": {"version": 1, "entry_count": 2},
            "entries": [
                {
                    "id": "official::openai-docs-mcp",
                    "name": "OpenAI Docs MCP",
                    "title": "Official OpenAI Docs MCP",
                    "vendor": "openai",
                    "owner": "openai",
                    "summary": "Official docs MCP for OpenAI API documentation.",
                    "type": "mcp",
                    "protocol": "mcp",
                    "transport": ["streamable_http"],
                    "install_methods": [{"kind": "remote_mcp", "url": "https://mcp.openai.com/mcp"}],
                    "auth_mode": "none",
                    "task_tags": ["docs", "research"],
                    "engine_compatibility": {
                        "claude_code": "inferred",
                        "codex": "documented",
                        "gemini_cli": "inferred",
                        "qwen_code": "inferred",
                    },
                    "reproducible": True,
                    "runtime_verified": False,
                    "status": "catalogued",
                    "trust_tier": "official",
                    "official_vendor": True,
                    "source_registry": "official_docs",
                    "source_url": "https://platform.openai.com/docs/docs-mcp",
                },
                {
                    "id": "official::anthropic-claude-code-hooks",
                    "name": "Claude Code Hooks",
                    "title": "Claude Code Hooks",
                    "vendor": "anthropic",
                    "owner": "anthropic",
                    "summary": "Hook system for Claude Code.",
                    "type": "hook",
                    "protocol": "local_cli",
                    "transport": ["local_process"],
                    "install_methods": [{"kind": "builtin_cli_capability", "command": "claude"}],
                    "auth_mode": "n/a",
                    "task_tags": ["automation"],
                    "engine_compatibility": {
                        "claude_code": "documented",
                        "codex": "unsupported",
                        "gemini_cli": "unsupported",
                        "qwen_code": "unsupported",
                    },
                    "reproducible": True,
                    "runtime_verified": False,
                    "status": "catalogued",
                    "trust_tier": "official",
                    "official_vendor": True,
                    "source_registry": "official_docs",
                    "source_url": "https://docs.anthropic.com/en/docs/claude-code/hooks",
                },
            ],
        }
        sample_path = os.path.join(self._tmpdir, "capability_library.json")
        with open(sample_path, "w", encoding="utf-8") as handle:
            json.dump(sample_library, handle)
        os.environ["BRIDGE_CAPABILITY_LIBRARY_PATH"] = sample_path
        capability_library.clear_cache()

    def tearDown(self) -> None:
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir
        guardrails.GUARDRAILS_FILE = self._orig_guardrails_file
        guardrails.VIOLATIONS_FILE = self._orig_violations_file
        srv.TEAM_CONFIG = self._orig_team_config
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_session_tokens)
        if self._orig_library_env is None:
            os.environ.pop("BRIDGE_CAPABILITY_LIBRARY_PATH", None)
        else:
            os.environ["BRIDGE_CAPABILITY_LIBRARY_PATH"] = self._orig_library_env
        capability_library.clear_cache()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _get(self, base_url: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, base_url: str, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _put(self, base_url: str, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, base_url: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", headers=headers or {}, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_guardrails_catalog_and_evaluate_endpoints(self) -> None:
        base_url = self._start_server()
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": ["desktop_control"],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["wipe disk"],
                "rate_limits": {"max_per_minute": 1},
            },
        )
        exceeded, reason = guardrails.check_rate_limit("codex")
        self.assertFalse(exceeded)
        self.assertEqual(reason, "")

        status_catalog, body_catalog = self._get(base_url, "/guardrails/catalog", headers={"X-Bridge-Agent": "manager"})
        self.assertEqual(status_catalog, 200)
        self.assertIn("desktop_control", body_catalog["catalog"])

        status_eval, body_eval = self._post(
            base_url,
            "/guardrails/evaluate",
            {
                "agent_id": "codex",
                "tool_name": "bridge_desktop_click",
                "action_text": "wipe disk now",
            },
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_eval, 200)
        self.assertTrue(body_eval["ok"])
        self.assertTrue(body_eval["evaluation"]["tool_allowed"])
        self.assertTrue(body_eval["evaluation"]["action_denied"])
        self.assertTrue(body_eval["evaluation"]["rate_limited"])
        self.assertEqual(body_eval["evaluation"]["rate_limit"]["current_count"], 1)
        self.assertEqual(body_eval["evaluation"]["tool_classification"]["group"], "desktop_control")

    def test_guardrails_presets_list_and_apply_endpoint(self) -> None:
        base_url = self._start_server()

        status_presets, body_presets = self._get(base_url, "/guardrails/presets", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(status_presets, 200)
        self.assertIn("safe_default", body_presets["presets"])
        self.assertIn("creator_operator", body_presets["presets"])

        status_apply, body_apply = self._post(
            base_url,
            "/guardrails/codex/apply-preset",
            {"preset_name": "creator_operator", "overrides": {"rate_limits": {"max_per_minute": 5}}},
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_apply, 200)
        self.assertEqual(body_apply["preset_name"], "creator_operator")
        self.assertEqual(body_apply["policy"]["preset_name"], "creator_operator")
        self.assertEqual(body_apply["policy"]["rate_limits"]["max_per_minute"], 5)

        status_policy, body_policy = self._get(base_url, "/guardrails/codex", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(status_policy, 200)
        self.assertEqual(body_policy["preset_name"], "creator_operator")

        with self.assertRaises(urllib.error.HTTPError) as denied_non_admin:
            self._post(
                base_url,
                "/guardrails/codex/apply-preset",
                {"preset_name": "safe_default"},
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_non_admin.exception.code, 403)

    def test_guardrails_policy_put_and_delete_endpoints(self) -> None:
        base_url = self._start_server()

        status_put, body_put = self._put(
            base_url,
            "/guardrails/codex",
            {
                "allowed_tools": ["browser_write"],
                "consequential_tools_mode": "explicit_allow",
                "rate_limits": {"max_per_minute": 3},
            },
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_put, 200)
        self.assertTrue(body_put["ok"])
        self.assertEqual(body_put["policy"]["allowed_tools"], ["browser_write"])
        self.assertEqual(body_put["policy"]["rate_limits"]["max_per_minute"], 3)

        status_policy, body_policy = self._get(base_url, "/guardrails/codex", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(status_policy, 200)
        self.assertEqual(body_policy["allowed_tools"], ["browser_write"])

        status_delete, body_delete = self._delete(
            base_url,
            "/guardrails/codex",
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_delete, 200)
        self.assertTrue(body_delete["ok"])

        with self.assertRaises(urllib.error.HTTPError) as missing_again:
            self._delete(base_url, "/guardrails/codex", headers={"X-Bridge-Agent": "manager"})
        self.assertEqual(missing_again.exception.code, 404)

    def test_execution_runs_endpoints_expose_run_and_steps(self) -> None:
        base_url = self._start_server()
        artifact_path = os.path.join(self._tmpdir, "http_list.png")
        with open(artifact_path, "wb") as handle:
            handle.write(b"png")
        journal.ensure_run(
            "run-http",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-http",
            agent_id="codex",
            engine="stealth",
        )
        journal.append_step(
            "run-http",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            task_id="task-http",
            agent_id="codex",
            engine="stealth",
            result_summary={"request_id": "req-http"},
            artifacts=[{"path": artifact_path, "kind": "screenshot"}],
        )

        status_list, body_list = self._get(
            base_url,
            "/execution/runs?source=browser&task_id=task-http",
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["count"], 1)
        self.assertEqual(body_list["runs"][0]["run_id"], "run-http")
        self.assertEqual(body_list["runs"][0]["task_id"], "task-http")
        self.assertEqual(body_list["runs"][0]["last_status"], "pending_approval")
        self.assertEqual(body_list["runs"][0]["artifact_count"], 1)
        self.assertFalse(body_list["runs"][0]["has_errors"])
        self.assertEqual(body_list["runs"][0]["last_error"], "")

        status_filtered, body_filtered = self._get(
            base_url,
            "/execution/runs?source=browser&status=pending_approval&task_id=task-http",
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_filtered, 200)
        self.assertEqual(body_filtered["count"], 1)
        self.assertEqual(body_filtered["runs"][0]["run_id"], "run-http")

        status_run, body_run = self._get(base_url, "/execution/runs/run-http", headers={"X-Bridge-Agent": "manager"})
        self.assertEqual(status_run, 200)
        self.assertEqual(body_run["run"]["tool_name"], "bridge_browser_action")
        self.assertEqual(body_run["run"]["task_id"], "task-http")
        self.assertEqual(body_run["steps"][0]["result_summary"]["request_id"], "req-http")
        self.assertEqual(body_run["summary"]["step_count"], 1)
        self.assertEqual(body_run["summary"]["last_status"], "pending_approval")
        self.assertEqual(body_run["summary"]["artifact_count"], 1)
        self.assertFalse(body_run["summary"]["has_errors"])

    def test_capability_library_get_search_and_recommend_endpoints(self) -> None:
        base_url = self._start_server()

        status_list, body_list = self._get(base_url, "/capability-library?cli=codex&official_vendor=true&limit=5")
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["count"], 1)
        self.assertEqual(body_list["entries"][0]["id"], "official::openai-docs-mcp")

        status_facets, body_facets = self._get(base_url, "/capability-library/facets")
        self.assertEqual(status_facets, 200)
        self.assertIn("codex", body_facets["clis"])
        self.assertIn("official_docs", body_facets["source_registries"])

        status_detail, body_detail = self._get(base_url, "/capability-library/official::openai-docs-mcp")
        self.assertEqual(status_detail, 200)
        self.assertEqual(body_detail["entry"]["vendor"], "openai")

        status_search, body_search = self._post(base_url, "/capability-library/search", {"query": "claude hooks"})
        self.assertEqual(status_search, 200)
        self.assertEqual(body_search["entries"][0]["id"], "official::anthropic-claude-code-hooks")

        status_recommend, body_recommend = self._post(
            base_url,
            "/capability-library/recommend",
            {"task": "need docs for OpenAI APIs", "engine": "codex", "top_k": 3},
        )
        self.assertEqual(status_recommend, 200)
        self.assertEqual(body_recommend["matches"][0]["id"], "official::openai-docs-mcp")

    def test_execution_summary_endpoint_exposes_aggregates(self) -> None:
        base_url = self._start_server()
        journal.ensure_run(
            "run-http-summary-a",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-summary-http",
            agent_id="codex",
        )
        journal.append_step(
            "run-http-summary-a",
            source="browser",
            tool_name="bridge_browser_action",
            status="pending_approval",
            task_id="task-summary-http",
            agent_id="codex",
        )
        journal.ensure_run(
            "run-http-summary-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            task_id="task-summary-other",
            agent_id="codex",
        )
        journal.append_step(
            "run-http-summary-b",
            source="desktop",
            tool_name="bridge_desktop_click",
            status="completed",
            task_id="task-summary-other",
            agent_id="codex",
        )

        status_summary, body_summary = self._get(
            base_url,
            "/execution/summary?agent_id=codex&task_id=task-summary-http",
            headers={"X-Bridge-Agent": "manager"},
        )

        self.assertEqual(status_summary, 200)
        self.assertEqual(body_summary["summary"]["filters"]["task_id"], "task-summary-http")
        self.assertEqual(body_summary["summary"]["total_runs"], 1)
        self.assertEqual(body_summary["summary"]["total_steps"], 1)
        self.assertEqual(body_summary["summary"]["by_status"]["pending_approval"], 1)
        self.assertIn("run-http-summary-a", body_summary["summary"]["recent_run_ids"])

    def test_execution_metrics_endpoint_exposes_lightweight_kpis(self) -> None:
        base_url = self._start_server()
        journal.ensure_run(
            "run-http-metrics-a",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics-http",
            agent_id="codex",
        )
        journal.append_step(
            "run-http-metrics-a",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics-http",
            status="pending_approval",
            agent_id="codex",
        )
        journal.ensure_run(
            "run-http-metrics-b",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics-http",
            agent_id="codex",
        )
        journal.append_step(
            "run-http-metrics-b",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-metrics-http",
            status="error",
            agent_id="codex",
            error="approval denied",
        )

        status_metrics, body_metrics = self._get(
            base_url,
            "/execution/metrics?agent_id=codex&task_id=task-metrics-http&window_hours=24",
            headers={"X-Bridge-Agent": "codex"},
        )

        self.assertEqual(status_metrics, 200)
        self.assertEqual(body_metrics["metrics"]["total_runs"], 2)
        self.assertEqual(body_metrics["metrics"]["pending_approval_runs"], 1)
        self.assertEqual(body_metrics["metrics"]["error_runs"], 1)
        self.assertEqual(body_metrics["metrics"]["runs_with_errors"], 1)

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._get(
                base_url,
                "/execution/metrics?agent_id=manager",
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)

    def test_execution_endpoints_require_management_for_foreign_agent(self) -> None:
        base_url = self._start_server()
        journal.ensure_run(
            "run-http-2",
            source="browser",
            tool_name="bridge_browser_action",
            agent_id="codex",
        )

        with self.assertRaises(urllib.error.HTTPError) as denied_runs:
            self._get(base_url, "/execution/runs", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(denied_runs.exception.code, 403)

        with self.assertRaises(urllib.error.HTTPError) as denied_summary:
            self._get(base_url, "/execution/summary", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(denied_summary.exception.code, 403)

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign_runs:
            self._get(base_url, "/execution/runs?agent_id=manager", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(denied_foreign_runs.exception.code, 403)

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign_summary:
            self._get(base_url, "/execution/summary?agent_id=manager", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(denied_foreign_summary.exception.code, 403)

        with self.assertRaises(urllib.error.HTTPError) as denied_catalog:
            self._get(base_url, "/guardrails/catalog", headers={"X-Bridge-Agent": "codex"})
        self.assertEqual(denied_catalog.exception.code, 403)

    def test_execution_endpoints_allow_self_agent_scope(self) -> None:
        base_url = self._start_server()
        journal.ensure_run(
            "run-http-self",
            source="browser",
            tool_name="bridge_browser_action",
            agent_id="codex",
        )
        journal.append_step(
            "run-http-self",
            source="browser",
            tool_name="bridge_browser_action",
            status="completed",
            agent_id="codex",
            result_summary={"ok": True},
        )

        status_list, body_list = self._get(
            base_url,
            "/execution/runs?agent_id=codex",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["count"], 1)
        self.assertEqual(body_list["runs"][0]["run_id"], "run-http-self")

        status_run, body_run = self._get(
            base_url,
            "/execution/runs/run-http-self",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_run, 200)
        self.assertEqual(body_run["run"]["agent_id"], "codex")
        self.assertEqual(body_run["steps"][0]["status"], "completed")

        status_summary, body_summary = self._get(
            base_url,
            "/execution/summary?agent_id=codex",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_summary, 200)
        self.assertEqual(body_summary["summary"]["total_runs"], 1)
        self.assertEqual(body_summary["summary"]["by_status"]["completed"], 1)

    def test_guardrails_violations_endpoint_supports_type_filter(self) -> None:
        base_url = self._start_server()
        guardrails.set_policy("codex", {"allowed_tools": [], "consequential_tools_mode": "explicit_allow"})
        allowed, _ = guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        self.assertFalse(allowed)

        status_violations, body_violations = self._get(
            base_url,
            "/guardrails/violations?agent_id=codex&type=tool_denied",
            headers={"X-Bridge-Agent": "manager"},
        )

        self.assertEqual(status_violations, 200)
        self.assertEqual(body_violations["count"], 1)
        self.assertEqual(body_violations["violations"][0]["type"], "tool_denied")
        self.assertEqual(body_violations["violations"][0]["metadata"]["tool_name"], "bridge_desktop_click")

    def test_guardrails_violations_allow_self_scope_but_not_foreign_scope(self) -> None:
        base_url = self._start_server()
        guardrails.set_policy("codex", {"allowed_tools": [], "consequential_tools_mode": "explicit_allow"})
        allowed, _ = guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        self.assertFalse(allowed)

        status_self, body_self = self._get(
            base_url,
            "/guardrails/violations?agent_id=codex",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_self, 200)
        self.assertEqual(body_self["count"], 1)
        self.assertEqual(body_self["violations"][0]["agent_id"], "codex")

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._get(
                base_url,
                "/guardrails/violations?agent_id=manager",
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)

    def test_guardrails_summary_supports_management_and_self_scope(self) -> None:
        base_url = self._start_server()
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": [],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["wipe disk"],
            },
        )
        allowed, _ = guardrails.check_tool_allowed("codex", "bridge_desktop_click")
        self.assertFalse(allowed)
        denied, _ = guardrails.check_action_denied("codex", "wipe disk now")
        self.assertTrue(denied)

        status_manager, body_manager = self._get(
            base_url,
            "/guardrails/summary?agent_id=codex",
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_manager, 200)
        self.assertEqual(body_manager["summary"]["total_violations"], 2)
        self.assertEqual(body_manager["summary"]["by_type"]["tool_denied"], 1)
        self.assertEqual(body_manager["summary"]["by_type"]["action_denied"], 1)

        status_self, body_self = self._get(
            base_url,
            "/guardrails/summary?agent_id=codex",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_self, 200)
        self.assertEqual(body_self["summary"]["by_agent_id"]["codex"], 2)

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._get(
                base_url,
                "/guardrails/summary?agent_id=manager",
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)

    def test_guardrails_policy_endpoint_allows_self_but_not_foreign_agent(self) -> None:
        base_url = self._start_server()
        guardrails.set_policy(
            "codex",
            {
                "allowed_tools": ["desktop_control"],
                "consequential_tools_mode": "explicit_allow",
                "denied_actions": ["wipe disk"],
            },
        )

        status_self, body_self = self._get(
            base_url,
            "/guardrails/codex",
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_self, 200)
        self.assertEqual(body_self["agent_id"], "codex")
        self.assertEqual(body_self["consequential_tools_mode"], "explicit_allow")

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._get(
                base_url,
                "/guardrails/manager",
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)

    def test_execution_prune_endpoint_supports_dry_run_and_management_apply(self) -> None:
        base_url = self._start_server()
        for run_id in ("old-http-a", "old-http-b", "recent-http"):
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
        for run_id in ("old-http-a", "old-http-b"):
            run_path = journal._run_file(run_id)
            with open(run_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["created_at"] = old_timestamp
            with open(run_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)

        status_preview, body_preview = self._post(
            base_url,
            "/execution/runs/prune",
            {"agent_id": "codex", "max_age_hours": 1, "keep_latest": 1, "dry_run": True},
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_preview, 200)
        self.assertEqual(body_preview["result"]["candidate_runs"], 2)

        status_apply, body_apply = self._post(
            base_url,
            "/execution/runs/prune",
            {"agent_id": "codex", "max_age_hours": 1, "keep_latest": 1, "dry_run": False},
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_apply, 200)
        self.assertEqual(body_apply["result"]["pruned_runs"], 2)

        status_remaining, body_remaining = self._get(
            base_url,
            "/execution/runs?agent_id=codex",
            headers={"X-Bridge-Agent": "manager"},
        )
        self.assertEqual(status_remaining, 200)
        self.assertEqual(body_remaining["count"], 1)
        self.assertEqual(body_remaining["runs"][0]["run_id"], "recent-http")

        with self.assertRaises(urllib.error.HTTPError) as denied_non_admin:
            self._post(
                base_url,
                "/execution/runs/prune",
                {"agent_id": "codex", "max_age_hours": 1, "dry_run": True},
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_non_admin.exception.code, 403)

    def test_guardrails_incident_bundle_combines_policy_violations_and_execution(self) -> None:
        base_url = self._start_server()
        guardrails.apply_preset("codex", "safe_default")
        tool_allowed, _ = guardrails.check_tool_allowed("codex", "bridge_browser_click")
        action_denied, _ = guardrails.check_action_denied("codex", "wipe disk now")
        self.assertFalse(tool_allowed)
        self.assertTrue(action_denied)

        journal.ensure_run(
            "run-incident",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-incident",
            agent_id="codex",
        )
        journal.append_step(
            "run-incident",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-incident",
            status="pending_approval",
            agent_id="codex",
        )

        status_bundle, body_bundle = self._post(
            base_url,
            "/guardrails/incident-bundle",
            {
                "agent_id": "codex",
                "tool_name": "bridge_browser_click",
                "action_text": "wipe disk now",
                "source": "browser",
                "task_id": "task-incident",
                "recent_limit": 3,
            },
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_bundle, 200)
        self.assertTrue(body_bundle["ok"])
        self.assertEqual(body_bundle["bundle"]["policy"]["preset_name"], "safe_default")
        self.assertFalse(body_bundle["bundle"]["evaluation"]["tool_allowed"])
        self.assertTrue(body_bundle["bundle"]["evaluation"]["action_denied"])
        self.assertEqual(body_bundle["bundle"]["violations_summary"]["total_violations"], 2)
        self.assertEqual(body_bundle["bundle"]["execution_summary"]["total_runs"], 1)
        self.assertEqual(body_bundle["bundle"]["recent_runs"][0]["run_id"], "run-incident")

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._post(
                base_url,
                "/guardrails/incident-bundle",
                {"agent_id": "manager"},
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)

    def test_audit_export_provides_stable_combined_payload(self) -> None:
        base_url = self._start_server()
        guardrails.apply_preset("codex", "creator_operator")
        denied, _ = guardrails.check_action_denied("codex", "wipe disk now")
        self.assertTrue(denied)

        journal.ensure_run(
            "run-audit",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-audit",
            agent_id="codex",
        )
        journal.append_step(
            "run-audit",
            source="browser",
            tool_name="bridge_browser_action",
            task_id="task-audit",
            status="completed",
            agent_id="codex",
        )

        status_export, body_export = self._post(
            base_url,
            "/audit/export",
            {
                "agent_id": "codex",
                "source": "browser",
                "task_id": "task-audit",
                "window_hours": 24,
                "recent_limit": 5,
            },
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status_export, 200)
        self.assertTrue(body_export["ok"])
        self.assertEqual(body_export["export"]["schema_version"], "bridge.audit_export.v1")
        self.assertEqual(body_export["export"]["guardrails"]["policy"]["preset_name"], "creator_operator")
        self.assertEqual(body_export["export"]["guardrails"]["summary"]["total_violations"], 1)
        self.assertEqual(body_export["export"]["execution"]["summary"]["total_runs"], 1)
        self.assertEqual(body_export["export"]["execution"]["metrics"]["completed_runs"], 1)
        self.assertEqual(body_export["export"]["execution"]["recent_runs"][0]["run_id"], "run-audit")

        with self.assertRaises(urllib.error.HTTPError) as denied_foreign:
            self._post(
                base_url,
                "/audit/export",
                {"agent_id": "manager"},
                headers={"X-Bridge-Agent": "codex"},
            )
        self.assertEqual(denied_foreign.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
