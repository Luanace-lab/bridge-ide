from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "Frontend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestStatusSnapshotHelpers(unittest.TestCase):
    def setUp(self):
        self._orig_registered = dict(srv.REGISTERED_AGENTS)
        self._orig_last_seen = dict(srv.AGENT_LAST_SEEN)
        self._orig_busy = dict(srv.AGENT_BUSY)
        self._orig_connection_status = srv.agent_connection_status
        self._orig_runtime = dict(srv.RUNTIME)
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_runtime_team_path = srv.RUNTIME_TEAM_PATH
        self._orig_runtime_configure_audit_log = srv.RUNTIME_CONFIGURE_AUDIT_LOG

    def tearDown(self):
        srv.REGISTERED_AGENTS.clear()
        srv.REGISTERED_AGENTS.update(self._orig_registered)
        srv.AGENT_LAST_SEEN.clear()
        srv.AGENT_LAST_SEEN.update(self._orig_last_seen)
        srv.AGENT_BUSY.clear()
        srv.AGENT_BUSY.update(self._orig_busy)
        srv.agent_connection_status = self._orig_connection_status
        srv.TEAM_CONFIG = self._orig_team_config
        srv.RUNTIME_TEAM_PATH = self._orig_runtime_team_path
        srv.RUNTIME_CONFIGURE_AUDIT_LOG = self._orig_runtime_configure_audit_log
        with srv.RUNTIME_LOCK:
            srv.RUNTIME.clear()
            srv.RUNTIME.update(self._orig_runtime)

    def test_platform_status_snapshot_counts_only_connected_agents(self):
        srv.REGISTERED_AGENTS.clear()
        srv.REGISTERED_AGENTS.update({
            "buddy": {"registered_at": "2026-03-09T00:00:00Z"},
            "viktor": {"registered_at": "2026-03-09T00:00:00Z"},
            "kai": {"registered_at": "2026-03-09T00:00:00Z"},
        })
        states = {"buddy": "active", "viktor": "idle", "kai": "disconnected"}
        srv.agent_connection_status = lambda agent_id: states[agent_id]

        snapshot = srv.platform_status_snapshot()

        self.assertEqual(snapshot["registered_count"], 3)
        self.assertEqual(snapshot["online_count"], 2)
        self.assertEqual(snapshot["disconnected_count"], 1)
        self.assertEqual(snapshot["online_ids"], ["buddy", "viktor"])

    def test_registered_agent_uses_recent_bridge_activity_as_liveness_signal(self):
        now = time.time()
        srv.REGISTERED_AGENTS.clear()
        srv.AGENT_LAST_SEEN.clear()
        srv.AGENT_BUSY.clear()
        srv.REGISTERED_AGENTS["qwen_1"] = {
            "registered_at": "2026-03-10T00:00:00Z",
            "last_heartbeat": now - 600,
        }
        srv.AGENT_LAST_SEEN["qwen_1"] = now - 5

        self.assertEqual(srv.agent_connection_status("qwen_1"), "waiting")

    def test_runtime_snapshot_marks_active_only_after_real_runtime_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.RUNTIME_TEAM_PATH = os.path.join(tmpdir, "runtime_team.json")
            with srv.RUNTIME_LOCK:
                srv.RUNTIME.update({
                    "project_name": "",
                    "agent_profiles": [],
                    "runtime_overlay": None,
                    "last_start_at": None,
                })
            inactive = srv.runtime_snapshot()
            self.assertFalse(inactive["configured"])

        with srv.RUNTIME_LOCK:
            srv.RUNTIME.update({
                "project_name": "Alpha",
                "agent_profiles": [{"id": "buddy"}],
                "runtime_overlay": {"project": {"id": "alpha"}},
                "last_start_at": "2026-03-09T09:00:00Z",
            })
        active = srv.runtime_snapshot()
        self.assertTrue(active["configured"])

    def test_runtime_snapshot_agents_are_enriched_from_runtime_profiles(self):
        self._orig_is_session_alive = srv.is_session_alive
        try:
            srv.agent_connection_status = lambda agent_id: "waiting"
            srv.is_session_alive = lambda agent_id: True
            with srv.RUNTIME_LOCK:
                srv.RUNTIME.update({
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_name": "Alpha",
                    "project_path": "/tmp/alpha",
                    "agent_profiles": [
                        {
                            "id": "codex",
                            "slot": "a",
                            "name": "Implementer",
                            "display_name": "Implementer",
                            "engine": "codex",
                            "role": "Implementer",
                            "description": "Implements features.",
                            "model": "gpt-5.4",
                            "team": "delivery",
                            "reports_to": "teamlead",
                            "level": 3,
                        },
                        {
                            "id": "claude",
                            "slot": "b",
                            "name": "Reviewer",
                            "display_name": "Reviewer",
                            "engine": "claude",
                            "role": "Reviewer",
                            "description": "Reviews diffs.",
                            "model": "sonnet-4.6",
                            "team": "delivery",
                            "reports_to": "teamlead",
                            "level": 2,
                        },
                    ],
                    "runtime_overlay": {"project": {"id": "alpha"}},
                    "last_start_at": "2026-03-09T09:00:00Z",
                })

            snapshot = srv.runtime_snapshot()
            by_id = {agent["id"]: agent for agent in snapshot["agents"]}

            self.assertEqual(by_id["codex"]["name"], "Implementer")
            self.assertEqual(by_id["codex"]["role"], "Implementer")
            self.assertEqual(by_id["codex"]["team"], "delivery")
            self.assertEqual(by_id["codex"]["reports_to"], "teamlead")
            self.assertEqual(by_id["codex"]["model"], "gpt-5.4")
            self.assertEqual(by_id["claude"]["name"], "Reviewer")
            self.assertEqual(by_id["claude"]["role"], "Reviewer")
            self.assertEqual(by_id["claude"]["model"], "sonnet-4.6")
        finally:
            srv.is_session_alive = self._orig_is_session_alive

    def test_runtime_snapshot_uses_explicit_runtime_specs_for_multi_agent_runtime(self):
        self._orig_is_session_alive = srv.is_session_alive
        try:
            srv.agent_connection_status = lambda agent_id: "waiting"
            srv.is_session_alive = lambda agent_id: True
            with srv.RUNTIME_LOCK:
                srv.RUNTIME.update({
                    "pair_mode": "multi",
                    "agent_a_engine": "claude",
                    "agent_b_engine": "claude",
                    "project_name": "Scale Lab",
                    "project_path": "/tmp/scale-lab",
                    "agent_profiles": [
                        {
                            "id": "claude_1",
                            "slot": "agent_1",
                            "name": "Claude Alpha",
                            "display_name": "Claude Alpha",
                            "engine": "claude",
                            "role": "Lead",
                            "description": "Coordinates.",
                            "model": "claude-sonnet-4-6",
                            "team": "dogfood",
                            "reports_to": "user",
                            "level": 1,
                        },
                        {
                            "id": "claude_2",
                            "slot": "agent_2",
                            "name": "Claude Beta",
                            "display_name": "Claude Beta",
                            "engine": "claude",
                            "role": "Implementer",
                            "description": "Implements.",
                            "model": "claude-sonnet-4-6",
                            "team": "dogfood",
                            "reports_to": "claude_1",
                            "level": 3,
                        },
                        {
                            "id": "gemini_1",
                            "slot": "agent_3",
                            "name": "Gemini Reviewer",
                            "display_name": "Gemini Reviewer",
                            "engine": "gemini",
                            "role": "Reviewer",
                            "description": "Reviews.",
                            "model": "gemini-2.5-pro",
                            "team": "dogfood",
                            "reports_to": "claude_1",
                            "level": 2,
                        },
                    ],
                    "runtime_specs": [
                        {"slot": "agent_1", "id": "claude_1", "engine": "claude", "name": "Claude Alpha", "peer": ""},
                        {"slot": "agent_2", "id": "claude_2", "engine": "claude", "name": "Claude Beta", "peer": ""},
                        {"slot": "agent_3", "id": "gemini_1", "engine": "gemini", "name": "Gemini Reviewer", "peer": "claude_1"},
                    ],
                    "runtime_overlay": {"project": {"id": "scale-lab"}},
                    "last_start_at": "2026-03-10T10:00:00Z",
                    "team_lead_cli_enabled": False,
                })

            snapshot = srv.runtime_snapshot()

            self.assertEqual(snapshot["pair_mode"], "multi")
            self.assertEqual(snapshot["agents_total"], 3)
            self.assertEqual(snapshot["agent_ids"], ["claude_1", "claude_2", "gemini_1"])
            by_id = {agent["id"]: agent for agent in snapshot["agents"]}
            self.assertEqual(by_id["gemini_1"]["engine"], "gemini")
            self.assertEqual(by_id["claude_2"]["slot"], "agent_2")
        finally:
            srv.is_session_alive = self._orig_is_session_alive

    def test_cli_identity_bundle_prefers_workspace_payload_as_cli_sot(self):
        srv.TEAM_CONFIG = {
            "agents": [
                {
                    "id": "codex",
                    "home_dir": "/srv/legacy-project",
                }
            ]
        }

        identity = srv._cli_identity_bundle(
            "codex",
            {
                "workspace": "/tmp/project/.agent_sessions/codex",
                "project_root": "/tmp/project",
                "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "instruction_path": "/tmp/project/.agent_sessions/codex/AGENTS.md",
            },
        )

        self.assertEqual(identity["workspace"], "/tmp/project/.agent_sessions/codex")
        self.assertEqual(identity["project_root"], "/tmp/project")
        self.assertEqual(identity["resume_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(identity["instruction_path"], "/tmp/project/.agent_sessions/codex/AGENTS.md")
        self.assertEqual(identity["cli_identity_source"], "cli_register")

    def test_cli_identity_bundle_falls_back_to_team_home_when_register_payload_is_missing(self):
        agent_id = "__team_home_fallback_probe__"
        srv.TEAM_CONFIG = {
            "agents": [
                {
                    "id": agent_id,
                    "home_dir": "/srv/project",
                }
            ]
        }

        identity = srv._cli_identity_bundle(agent_id, {})

        self.assertEqual(identity["workspace"], f"/srv/project/.agent_sessions/{agent_id}")
        self.assertEqual(identity["project_root"], "/srv/project")
        self.assertEqual(identity["resume_id"], "")
        self.assertEqual(identity["cli_identity_source"], "team_home_fallback")

    def test_context_restore_uses_runtime_state_home_when_team_config_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "project"
            agent_id = "__runtime_restore_probe__"
            workspace = project / ".agent_sessions" / agent_id
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "CONTEXT_BRIDGE.md").write_text(
                "RUNTIME_CONTEXT_MARKER",
                encoding="utf-8",
            )
            (workspace / "SOUL.md").write_text(
                "RUNTIME_SOUL_MARKER",
                encoding="utf-8",
            )
            srv.TEAM_CONFIG = {"agents": []}

            restore = srv._build_context_restore_message(
                agent_id,
                {
                    "home_dir": str(workspace),
                    "workspace": str(workspace),
                    "project_root": str(project),
                    "context_summary": "runtime-summary",
                },
            )

        self.assertIn("RUNTIME_CONTEXT_MARKER", restore)
        self.assertIn("RUNTIME_SOUL_MARKER", restore)
        self.assertIn("runtime-summary", restore)
        self.assertIn("## PERSISTENZ-HOOK (JETZT AUSFUEHREN)", restore)
        self.assertIn(str(workspace / "CONTEXT_BRIDGE.md"), restore)
        self.assertIn(str(workspace / "SOUL.md"), restore)

    def test_get_agent_home_dir_uses_runtime_state_when_team_config_missing(self):
        agent_id = "__runtime_home_probe__"
        state_path = Path(srv._agent_state_path(agent_id))
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                project = Path(tmpdir) / "project"
                workspace = project / ".agent_sessions" / agent_id
                workspace.mkdir(parents=True, exist_ok=True)
                srv.TEAM_CONFIG = {"agents": []}
                srv._save_agent_state(
                    agent_id,
                    {
                        "workspace": str(workspace),
                        "project_root": str(project),
                    },
                )
                resolved = srv._get_agent_home_dir(agent_id)
            self.assertEqual(resolved, str(workspace))
        finally:
            srv._AGENT_STATE_CACHE.pop(agent_id, None)
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass

    def test_check_agent_memory_health_uses_runtime_state_home_when_team_config_missing(self):
        agent_id = "__runtime_memory_probe__"
        state_path = Path(srv._agent_state_path(agent_id))
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                project = Path(tmpdir) / "project"
                workspace = project / ".agent_sessions" / agent_id
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "MEMORY.md").write_text("RUNTIME_MEMORY_MARKER", encoding="utf-8")
                (workspace / "CONTEXT_BRIDGE.md").write_text("RUNTIME_CONTEXT_MARKER", encoding="utf-8")
                stale_ts = time.time() - 61
                os.utime(workspace / "CONTEXT_BRIDGE.md", (stale_ts, stale_ts))
                srv.TEAM_CONFIG = {"agents": []}
                srv._save_agent_state(
                    agent_id,
                    {
                        "home_dir": str(workspace),
                        "workspace": str(workspace),
                        "project_root": str(project),
                    },
                )
                health = srv._check_agent_memory_health(agent_id)
            self.assertTrue(health["has_memory"])
            self.assertEqual(health["memory_path"], str(workspace / "MEMORY.md"))
            self.assertEqual(health["context_bridge_path"], str(workspace / "CONTEXT_BRIDGE.md"))
            self.assertTrue(health["healthy"])
        finally:
            srv._AGENT_STATE_CACHE.pop(agent_id, None)
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass

    def test_runtime_snapshot_restores_runtime_from_overlay_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.RUNTIME_TEAM_PATH = os.path.join(tmpdir, "runtime_team.json")
            overlay = {
                "active": True,
                "generated_at": "2026-03-10T09:27:25.800383+00:00",
                "project": {
                    "id": "bridge-dogfood",
                    "name": "bridge-dogfood",
                    "path": "/tmp/bridge-dogfood",
                },
                "agents": [
                    {
                        "id": "claude_a",
                        "slot": "a",
                        "name": "Scale Lab Alpha",
                        "display_name": "Scale Lab Alpha",
                        "engine": "claude",
                        "role": "Worker A",
                        "description": "Dogfood alpha",
                        "model": "claude-sonnet-4-6",
                    },
                    {
                        "id": "claude_b",
                        "slot": "b",
                        "name": "Scale Lab Beta",
                        "display_name": "Scale Lab Beta",
                        "engine": "claude",
                        "role": "Worker B",
                        "description": "Dogfood beta",
                        "model": "claude-sonnet-4-6",
                    },
                ],
                "teams": [],
                "routes": {},
            }
            Path(srv.RUNTIME_TEAM_PATH).write_text(
                json.dumps(overlay),
                encoding="utf-8",
            )
            with srv.RUNTIME_LOCK:
                srv.RUNTIME.clear()
                srv.RUNTIME.update({
                    "pair_mode": "codex-claude",
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_name": "",
                    "project_path": srv.ROOT_DIR,
                    "allow_peer_auto": False,
                    "peer_auto_require_flag": True,
                    "max_peer_hops": 20,
                    "max_turns": 0,
                    "process_all": False,
                    "keep_history": False,
                    "timeout": 90,
                    "team_lead_timeout": 300,
                    "team_lead_enabled": False,
                    "team_lead_max_peer_messages": 40,
                    "team_lead_cli_enabled": False,
                    "team_lead_engine": "codex",
                    "team_lead_scope_file": os.path.join(srv.ROOT_DIR, "teamlead.md"),
                    "agent_profiles": [],
                    "runtime_overlay": None,
                    "last_start_at": None,
                })

            snapshot = srv.runtime_snapshot()

            self.assertTrue(snapshot["configured"])
            self.assertEqual(snapshot["pair_mode"], "claude-claude")
            self.assertEqual(snapshot["project_name"], "bridge-dogfood")
            self.assertEqual(snapshot["project_path"], "/tmp/bridge-dogfood")
            self.assertEqual(len(snapshot["agent_profiles"]), 2)
            self.assertEqual(snapshot["agent_profiles"][0]["model"], "claude-sonnet-4-6")

    def test_runtime_configure_audit_helper_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.RUNTIME_CONFIGURE_AUDIT_LOG = os.path.join(tmpdir, "runtime_configure_audit.jsonl")

            srv._append_runtime_configure_audit(
                "request",
                {
                    "remote_addr": "127.0.0.1",
                    "x_bridge_agent": "user",
                    "user_agent": "pytest",
                    "referer": "http://127.0.0.1:8787/",
                },
                {
                    "project_name": "bridge-dogfood",
                    "project_path": "/tmp/bridge-dogfood",
                    "agent_a_engine": "claude",
                    "agent_b_engine": "claude",
                    "agent_count": 2,
                    "agents": [{"name": "alpha"}, {"name": "beta"}],
                },
                {"started_ids": ["claude_a", "claude_b"]},
            )

            lines = Path(srv.RUNTIME_CONFIGURE_AUDIT_LOG).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["event"], "request")
            self.assertEqual(entry["request"]["x_bridge_agent"], "user")
            self.assertEqual(entry["payload"]["project_name"], "bridge-dogfood")
            self.assertEqual(entry["outcome"]["started_ids"], ["claude_a", "claude_b"])

    def test_runtime_configure_summary_limits_logged_agents(self):
        summary = srv._runtime_configure_payload_summary(
            {
                "project_name": "bridge-dogfood",
                "project_path": "/tmp/bridge-dogfood",
                "agent_a_engine": "claude",
                "agent_b_engine": "claude",
                "leader": {"name": "lead", "model": "opus"},
                "agents": [
                    {"name": f"agent-{idx}", "model": "claude-sonnet-4-6", "role": "worker"}
                    for idx in range(6)
                ],
            }
        )

        self.assertEqual(summary["project_name"], "bridge-dogfood")
        self.assertEqual(summary["agent_count"], 6)
        self.assertEqual(len(summary["agents"]), 5)
        self.assertEqual(summary["leader"]["name"], "lead")

    def test_agents_endpoint_merges_runtime_profiles_for_runtime_only_agents(self):
        raw = Path(os.path.join(BACKEND_DIR, "server.py")).read_text(encoding="utf-8")
        agents_idx = raw.find('if path == "/agents":')
        self.assertGreater(agents_idx, 0)
        agents_block = raw[agents_idx:agents_idx + 14000]
        self.assertIn("runtime_profiles = _runtime_profile_map_from_state(runtime_state)", agents_block)
        self.assertIn('"engine": _team_engine.get(agent_id, "") or str(runtime_profile.get("engine", "")) or reg.get("engine", "claude")', agents_block)
        self.assertIn('"role": _team_roles.get(agent_id, "") or str(runtime_profile.get("role", "")) or reg.get("role", "")', agents_block)


class TestFrontendStatusContracts(unittest.TestCase):
    def _read(self, filename: str) -> str:
        return Path(os.path.join(FRONTEND_DIR, filename)).read_text(encoding="utf-8")

    def test_project_config_uses_status_endpoint_for_status_dot(self):
        raw = self._read("project_config.html")
        self.assertIn("fetch(API_BASE + '/status')", raw)
        self.assertIn("runtime.configured", raw)
        self.assertNotIn("fetch(API_BASE + '/agents')", raw)

    def test_control_center_top_status_uses_status_snapshot(self):
        raw = self._read("control_center.html")
        self.assertIn("fetch(API_BASE + '/status', { signal: AbortSignal.timeout(3000) })", raw)
        self.assertIn("statusData.platform?.online_count", raw)
        self.assertIn("fetch(API_BASE + '/agents', { signal: AbortSignal.timeout(3000) })", raw)
        self.assertIn("const runtimeAgents = Array.isArray(statusData.runtime?.agents) ? statusData.runtime.agents : [];", raw)
        self.assertIn("const runtimeDotMap = { lead:'dashStatusL', a:'dashStatusA', b:'dashStatusB' };", raw)
        self.assertIn("runtimeAgents.forEach(agent => {", raw)


if __name__ == "__main__":
    unittest.main()
