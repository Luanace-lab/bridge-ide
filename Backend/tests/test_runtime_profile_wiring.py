from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestRuntimeProfileWiring(unittest.TestCase):
    def test_open_agent_sessions_falls_back_to_team_config_dir_for_runtime_pair(self):
        captured = []
        original_create = srv.create_agent_session
        original_team = srv.TEAM_CONFIG
        try:
            def fake_create_agent_session(**kwargs):
                captured.append(kwargs)
                return True

            srv.create_agent_session = fake_create_agent_session
            srv.TEAM_CONFIG = {
                "agents": [
                    {
                        "id": "claude",
                        "description": "Claude Agent B. Release-Blocker Implementierung.",
                        "config_dir": "/tmp/test-config/",
                        "mcp_servers": "all",
                        "model": "claude-haiku-4-5-20251001",
                        "permissions": ["review"],
                        "scope": ["Backend/"],
                    }
                ]
            }
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_path": tmpdir,
                    "agent_profiles": [],
                    "runtime_specs": [
                        {"slot": "a", "id": "codex", "engine": "codex", "name": "codex_agent", "peer": "claude"},
                        {"slot": "b", "id": "claude", "engine": "claude", "name": "claude_agent", "peer": "codex"},
                    ],
                }

                srv.open_agent_sessions(config)

            calls = {item["agent_id"]: item for item in captured}
            self.assertEqual(calls["claude"]["config_dir"], "/tmp/test-config/")
            self.assertEqual(calls["claude"]["mcp_servers"], "all")
            self.assertEqual(calls["claude"]["model"], "claude-haiku-4-5-20251001")
            self.assertEqual(calls["claude"]["permissions"], ["review"])
            self.assertEqual(calls["claude"]["scope"], ["Backend/"])
        finally:
            srv.create_agent_session = original_create
            srv.TEAM_CONFIG = original_team

    def test_open_agent_sessions_runtime_profiles_still_fall_back_to_team_config_dir(self):
        captured = []
        original_create = srv.create_agent_session
        original_team = srv.TEAM_CONFIG
        try:
            def fake_create_agent_session(**kwargs):
                captured.append(kwargs)
                return True

            srv.create_agent_session = fake_create_agent_session
            srv.TEAM_CONFIG = {
                "agents": [
                    {
                        "id": "claude",
                        "description": "Claude Agent B. Release-Blocker Implementierung.",
                        "config_dir": "/tmp/test-config-mobile/",
                        "mcp_servers": "all",
                        "model": "claude-opus-4-1",
                        "permissions": ["review"],
                        "scope": ["Backend/"],
                    }
                ]
            }
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_path": tmpdir,
                    "agent_profiles": [
                        {
                            "id": "claude",
                            "engine": "claude",
                            "name": "Claude Agent B",
                            "permission_mode": "default",
                        }
                    ],
                    "runtime_specs": [
                        {"slot": "a", "id": "codex", "engine": "codex", "name": "codex_agent", "peer": "claude"},
                        {"slot": "b", "id": "claude", "engine": "claude", "name": "claude_agent", "peer": "codex"},
                    ],
                }

                srv.open_agent_sessions(config)

            calls = {item["agent_id"]: item for item in captured}
            self.assertEqual(calls["claude"]["config_dir"], "/tmp/test-config-mobile/")
            self.assertEqual(calls["claude"]["mcp_servers"], "all")
            self.assertEqual(calls["claude"]["model"], "claude-opus-4-1")
            self.assertEqual(calls["claude"]["permissions"], ["review"])
            self.assertEqual(calls["claude"]["scope"], ["Backend/"])
        finally:
            srv.create_agent_session = original_create
            srv.TEAM_CONFIG = original_team

    def test_open_agent_sessions_does_not_deadlock_when_team_members_are_loaded(self):
        captured = []
        original_create = srv.create_agent_session
        original_team = srv.TEAM_CONFIG
        try:
            def fake_create_agent_session(**kwargs):
                captured.append(kwargs)
                return True

            srv.create_agent_session = fake_create_agent_session
            srv.TEAM_CONFIG = {
                "agents": [
                    {
                        "id": "codex",
                        "team": "delivery",
                        "description": "Codex",
                    },
                    {
                        "id": "claude",
                        "team": "delivery",
                        "description": "Claude",
                        "config_dir": "/tmp/test-config-mobile/",
                    },
                ]
            }
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_path": tmpdir,
                    "agent_profiles": [],
                    "runtime_specs": [
                        {"slot": "a", "id": "codex", "engine": "codex", "name": "codex_agent", "peer": "claude"},
                        {"slot": "b", "id": "claude", "engine": "claude", "name": "claude_agent", "peer": "codex"},
                    ],
                }

                result_holder: dict[str, object] = {}

                def runner() -> None:
                    result_holder["value"] = srv.open_agent_sessions(config)

                thread = threading.Thread(target=runner, daemon=True)
                thread.start()
                thread.join(timeout=2.0)

                self.assertFalse(thread.is_alive(), "open_agent_sessions deadlocked while loading team members")
                self.assertIn("value", result_holder)

            calls = {item["agent_id"]: item for item in captured}
            self.assertEqual(calls["codex"]["team_members"], [{"id": "claude", "role": "Claude"}])
            self.assertEqual(calls["claude"]["team_members"], [{"id": "codex", "role": "Codex"}])
        finally:
            srv.create_agent_session = original_create
            srv.TEAM_CONFIG = original_team

    def test_registered_capabilities_fall_back_to_runtime_profile(self):
        original_runtime = dict(srv.RUNTIME)
        original_registered = dict(srv.REGISTERED_AGENTS)
        try:
            srv.RUNTIME.clear()
            srv.RUNTIME.update(
                {
                    "agent_profiles": [
                        {
                            "id": "qwen_1",
                            "capabilities": ["qa"],
                        }
                    ]
                }
            )
            srv.REGISTERED_AGENTS.clear()
            srv.REGISTERED_AGENTS["qwen_1"] = {
                "role": "QA",
                "capabilities": [],
                "engine": "qwen",
                "registered_at": "2026-03-10T12:00:00+00:00",
                "last_heartbeat": 0.0,
                "last_heartbeat_iso": "2026-03-10T12:00:00+00:00",
            }

            registered, caps = srv._get_registered_agent_capabilities("qwen_1")

            self.assertTrue(registered)
            self.assertEqual(caps, ["qa"])
            self.assertEqual(srv._capabilities_for_response("qwen_1", srv.REGISTERED_AGENTS["qwen_1"]), ["qa"])
        finally:
            srv.RUNTIME.clear()
            srv.RUNTIME.update(original_runtime)
            srv.REGISTERED_AGENTS.clear()
            srv.REGISTERED_AGENTS.update(original_registered)

    def test_build_runtime_profiles_preserves_form_fields(self):
        layout = [
            {"slot": "a", "id": "codex", "engine": "codex", "name": "codex_agent", "peer": "qwen"},
            {"slot": "b", "id": "qwen", "engine": "qwen", "name": "qwen_agent", "peer": "codex"},
            {"slot": "lead", "id": "teamlead", "engine": "claude", "name": "teamlead_agent", "peer": "codex"},
        ]
        data = {
            "leader": {
                "name": "Lead",
                "model": "claude-sonnet-4-6",
                "prompt": "Koordiniere das Team.",
                "permission": "plan",
                "position": "Koordinator",
                "hierarchyLevel": "lead",
                "teamAssignment": "management",
                "scope": "docs, planning.md",
                "permissions": ["strategy", "review"],
                "tools": ["Read", "WebFetch"],
            },
            "agents": [
                {
                    "name": "Implementer",
                    "model": "gpt-5.3-codex",
                    "prompt": "Implementiere Features.",
                    "permission": "dontAsk",
                    "position": "Implementer",
                    "hierarchyLevel": "worker",
                    "teamAssignment": "delivery",
                    "reportsTo": "teamlead",
                    "scope": "src, api.py",
                    "permissions": ["code"],
                    "tools": ["Read", "Write", "Edit", "Bash"],
                },
                {
                    "name": "Reviewer",
                    "model": "qwen3-coder-plus",
                    "prompt": "Pruefe Qualitaet.",
                    "permission": "acceptEdits",
                    "position": "Reviewer",
                    "hierarchyLevel": "senior",
                    "teamAssignment": "delivery",
                    "reportsTo": "teamlead",
                    "scope": "tests, docs",
                    "permissions": ["review", "qa"],
                    "tools": ["Read", "Edit"],
                },
            ],
        }

        profiles = srv._build_runtime_agent_profiles(
            data,
            layout,
            project_name="Alpha Project",
            project_path="/tmp/alpha-project",
        )
        by_id = {p["id"]: p for p in profiles}

        self.assertEqual(by_id["teamlead"]["model"], "claude-sonnet-4-6")
        self.assertEqual(by_id["teamlead"]["permission_mode"], "plan")
        self.assertEqual(by_id["teamlead"]["role"], "Koordinator")
        self.assertEqual(by_id["teamlead"]["team"], "management")
        self.assertEqual(by_id["teamlead"]["reports_to"], "user")
        self.assertEqual(by_id["teamlead"]["scope"], ["docs", "planning.md"])
        self.assertEqual(by_id["teamlead"]["capabilities"], ["strategy", "review"])

        self.assertEqual(by_id["codex"]["model"], "gpt-5.3-codex")
        self.assertEqual(by_id["codex"]["permission_mode"], "dontAsk")
        self.assertEqual(by_id["codex"]["role"], "Implementer")
        self.assertEqual(by_id["codex"]["reports_to"], "teamlead")
        self.assertEqual(by_id["codex"]["scope"], ["src", "api.py"])
        self.assertEqual(by_id["codex"]["capabilities"], ["code"])

        self.assertEqual(by_id["qwen"]["level_label"], "senior")
        self.assertEqual(by_id["qwen"]["level"], 2)
        self.assertEqual(by_id["qwen"]["team"], "delivery")
        self.assertEqual(by_id["qwen"]["capabilities"], ["review", "qa"])

    def test_build_runtime_profiles_supports_explicit_multi_agent_layout(self):
        layout = [
            {"slot": "agent_1", "id": "claude_1", "engine": "claude", "name": "Claude 1", "peer": "", "source_index": 0},
            {"slot": "agent_2", "id": "claude_2", "engine": "claude", "name": "Claude 2", "peer": "", "source_index": 1},
            {"slot": "agent_3", "id": "gemini_1", "engine": "gemini", "name": "Gemini 1", "peer": "claude_1", "source_index": 2},
            {"slot": "agent_4", "id": "qwen_1", "engine": "qwen", "name": "Qwen 1", "peer": "claude_1", "source_index": 3},
        ]
        data = {
            "agents": [
                {
                    "id": "claude_1",
                    "engine": "claude",
                    "name": "Claude Alpha",
                    "model": "claude-sonnet-4-6",
                    "prompt": "Analysiere.",
                    "position": "Analyst",
                    "hierarchyLevel": "lead",
                    "teamAssignment": "dogfood",
                    "scope": "Backend",
                    "permissions": ["strategy", "review"],
                    "tools": ["Read", "Bash"],
                },
                {
                    "id": "claude_2",
                    "engine": "claude",
                    "name": "Claude Beta",
                    "model": "claude-sonnet-4-6",
                    "prompt": "Implementiere.",
                    "position": "Implementer",
                    "hierarchyLevel": "worker",
                    "reportsTo": "claude_1",
                    "teamAssignment": "dogfood",
                    "scope": "Frontend",
                    "permissions": ["code"],
                    "tools": ["Read", "Write", "Edit", "Bash"],
                },
                {
                    "id": "gemini_1",
                    "engine": "gemini",
                    "name": "Gemini Reviewer",
                    "model": "gemini-2.5-pro",
                    "prompt": "Pruefe.",
                    "position": "Reviewer",
                    "hierarchyLevel": "senior",
                    "reportsTo": "claude_1",
                    "teamAssignment": "dogfood",
                    "scope": "tests",
                    "permissions": ["review", "qa"],
                    "tools": ["Read", "Edit"],
                },
                {
                    "id": "qwen_1",
                    "engine": "qwen",
                    "name": "Qwen QA",
                    "model": "qwen3-coder-plus",
                    "prompt": "Finde Risiken.",
                    "position": "QA",
                    "hierarchyLevel": "worker",
                    "reportsTo": "claude_1",
                    "teamAssignment": "dogfood",
                    "scope": "docs",
                    "permissions": ["qa"],
                    "tools": ["Read", "Edit"],
                },
            ]
        }

        profiles = srv._build_runtime_agent_profiles(
            data,
            layout,
            project_name="Scale Lab",
            project_path="/tmp/scale-lab",
        )
        by_id = {p["id"]: p for p in profiles}

        self.assertEqual(len(by_id), 4)
        self.assertEqual(by_id["claude_1"]["role"], "Analyst")
        self.assertEqual(by_id["claude_1"]["reports_to"], "user")
        self.assertEqual(by_id["claude_2"]["reports_to"], "claude_1")
        self.assertEqual(by_id["gemini_1"]["engine"], "gemini")
        self.assertEqual(by_id["gemini_1"]["capabilities"], ["review", "qa"])
        self.assertEqual(by_id["qwen_1"]["model"], "qwen3-coder-plus")

    def test_runtime_overlay_derives_teams_routes_and_context(self):
        profiles = [
            {
                "id": "teamlead",
                "slot": "lead",
                "name": "Lead",
                "engine": "claude",
                "role": "Koordinator",
                "description": "Koordiniert das Team.",
                "prompt": "Koordiniere das Team.",
                "model": "claude-sonnet-4-6",
                "permission_mode": "plan",
                "tools": ["Read"],
                "capabilities": ["strategy"],
                "scope": ["docs"],
                "scope_text": "docs",
                "level_label": "lead",
                "level": 1,
                "team": "management",
                "reports_to": "user",
                "active": True,
            },
            {
                "id": "codex",
                "slot": "a",
                "name": "Implementer",
                "engine": "codex",
                "role": "Implementer",
                "description": "Implementiert Features.",
                "prompt": "Implementiere Features.",
                "model": "gpt-5.3-codex",
                "permission_mode": "dontAsk",
                "tools": ["Read", "Write", "Edit", "Bash"],
                "capabilities": ["code"],
                "scope": ["src"],
                "scope_text": "src",
                "level_label": "worker",
                "level": 3,
                "team": "delivery",
                "reports_to": "teamlead",
                "active": True,
            },
            {
                "id": "qwen",
                "slot": "b",
                "name": "Reviewer",
                "engine": "qwen",
                "role": "Reviewer",
                "description": "Prueft Features.",
                "prompt": "Pruefe Qualitaet.",
                "model": "qwen3-coder-plus",
                "permission_mode": "acceptEdits",
                "tools": ["Read", "Edit"],
                "capabilities": ["review"],
                "scope": ["tests"],
                "scope_text": "tests",
                "level_label": "senior",
                "level": 2,
                "team": "delivery",
                "reports_to": "teamlead",
                "active": True,
            },
        ]

        overlay = srv._build_runtime_overlay("Alpha Project", "/tmp/alpha-project", profiles)
        self.assertIsNotNone(overlay)
        assert overlay is not None
        routes = overlay["routes"]
        self.assertIn("teamlead", routes["codex"])
        self.assertIn("qwen", routes["codex"])
        self.assertIn("codex", routes["qwen"])
        self.assertIn("teamlead", routes["user"])

        teams = {team["id"]: team for team in overlay["teams"]}
        self.assertIn("management", teams)
        self.assertIn("delivery", teams)
        self.assertEqual(teams["delivery"]["lead"], "qwen")

        ctx = srv._runtime_overlay_team_context(overlay, "codex")
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx["agent"]["reports_to"], "teamlead")
        self.assertEqual(ctx["team"]["id"], "delivery")
        teammate_ids = {item["id"] for item in ctx["teammates"]}
        self.assertIn("qwen", teammate_ids)

    def test_qwen_permission_queries_use_real_cli_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.write_agent_permission(tmpdir, "qwen", "auto_approve", True)
            perms = srv.read_agent_permissions(tmpdir, "qwen")
            self.assertTrue(perms["auto_approve"])
            settings_path = os.path.join(tmpdir, ".qwen", "settings.json")
            raw = json.loads(open(settings_path, encoding="utf-8").read())
            self.assertEqual(raw["tools"]["approvalMode"], "auto-edit")

            srv.write_agent_permission(tmpdir, "qwen", "file_write", False)
            perms = srv.read_agent_permissions(tmpdir, "qwen")
            self.assertFalse(perms["file_write"])
            raw = json.loads(open(settings_path, encoding="utf-8").read())
            self.assertEqual(raw["tools"]["approvalMode"], "plan")

    def test_gemini_permission_queries_use_real_cli_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srv.write_agent_permission(tmpdir, "gemini", "auto_approve", True)
            perms = srv.read_agent_permissions(tmpdir, "gemini")
            self.assertTrue(perms["auto_approve"])
            settings_path = os.path.join(tmpdir, ".gemini", "settings.json")
            raw = json.loads(open(settings_path, encoding="utf-8").read())
            self.assertEqual(raw["general"]["defaultApprovalMode"], "auto_edit")

            srv.write_agent_permission(tmpdir, "gemini", "file_write", False)
            perms = srv.read_agent_permissions(tmpdir, "gemini")
            self.assertFalse(perms["file_write"])
            raw = json.loads(open(settings_path, encoding="utf-8").read())
            self.assertEqual(raw["general"]["defaultApprovalMode"], "plan")

    def test_create_scaffold_docs_include_runtime_profile_fields(self):
        agent = {
            "name": "Reviewer",
            "position": "Reviewer",
            "model": "qwen3-coder-plus",
            "prompt": "Pruefe Qualitaet.",
            "hierarchyLevel": "senior",
            "teamAssignment": "delivery",
            "reportsTo": "teamlead",
            "scope": "tests, docs",
            "permission": "acceptEdits",
            "permissions": ["review", "qa"],
        }
        content = srv._generate_agents_md("Alpha Project", {}, [agent])
        self.assertIn("**Role:** Reviewer", content)
        self.assertIn("**Level:** senior", content)
        self.assertIn("**Team:** delivery", content)
        self.assertIn("**Reports-to:** teamlead", content)
        self.assertIn("**Scope:** tests, docs", content)
        self.assertIn("**Permission-Mode:** acceptEdits", content)
        self.assertIn("**Capabilities:** review, qa", content)

    def test_qwen_models_follow_cli_registry_and_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "qwen-settings.json")
            cli_js_path = os.path.join(tmpdir, "qwen-cli.js")
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "security": {"auth": {"selectedType": "qwen-oauth"}},
                        "model": {"name": "coder-model"},
                    },
                    fh,
                )
            with open(cli_js_path, "w", encoding="utf-8") as fh:
                fh.write(
                    'QWEN_OAUTH_MODELS = [\n'
                    '  {\n'
                    '    id: "coder-model",\n'
                    '    name: "coder-model",\n'
                    '    description: "Qwen 3.5 Plus \\\\u2014 efficient hybrid model with leading coding performance"\n'
                    '  }\n'
                    '];\n'
                    'QWEN_OAUTH_ALLOWED_MODELS = QWEN_OAUTH_MODELS.map((model) => model.id);\n'
                )

            models = srv._qwen_models_from_cli(
                settings_path=settings_path,
                cli_js_path=cli_js_path,
            )

        self.assertEqual(models[0]["id"], "coder-model")
        self.assertEqual(models[0]["label"], "Qwen 3.5 Plus")
        self.assertTrue(models[0]["default"])

    def test_gemini_models_follow_cli_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "gemini-settings.json")
            models_js_path = os.path.join(tmpdir, "models.js")
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump({"security": {"auth": {"selectedType": "oauth-personal"}}}, fh)
            with open(models_js_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "export const PREVIEW_GEMINI_MODEL = 'gemini-3-pro-preview';\n"
                    "export const PREVIEW_GEMINI_FLASH_MODEL = 'gemini-3-flash-preview';\n"
                    "export const DEFAULT_GEMINI_MODEL = 'gemini-2.5-pro';\n"
                    "export const DEFAULT_GEMINI_FLASH_MODEL = 'gemini-2.5-flash';\n"
                    "export const DEFAULT_GEMINI_FLASH_LITE_MODEL = 'gemini-2.5-flash-lite';\n"
                    "export const PREVIEW_GEMINI_MODEL_AUTO = 'auto-gemini-3';\n"
                    "export const DEFAULT_GEMINI_MODEL_AUTO = 'auto-gemini-2.5';\n"
                )

            models = srv._gemini_models_from_cli(
                settings_path=settings_path,
                models_js_path=models_js_path,
            )

        model_ids = [item["id"] for item in models]
        self.assertEqual(models[0]["id"], "auto-gemini-3")
        self.assertTrue(models[0]["default"])
        self.assertIn("auto-gemini-2.5", model_ids)
        self.assertIn("gemini-2.5-flash-lite", model_ids)

    def test_codex_models_follow_cache_and_current_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.toml")
            cache_path = os.path.join(tmpdir, "models_cache.json")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write('model = "gpt-5.4"\n')
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.3-codex",
                                "display_name": "gpt-5.3-codex",
                                "description": "Latest frontier agentic coding model.",
                                "visibility": "list",
                                "priority": 1,
                            },
                            {
                                "slug": "gpt-5.4",
                                "display_name": "gpt-5.4",
                                "description": "Latest frontier agentic coding model.",
                                "visibility": "list",
                                "priority": 0,
                            },
                        ]
                    },
                    fh,
                )

            models = srv._codex_models_from_cli(
                config_path=config_path,
                cache_path=cache_path,
            )

        self.assertEqual(models[0]["id"], "gpt-5.4")
        self.assertTrue(models[0]["default"])
        self.assertEqual(models[1]["id"], "gpt-5.3-codex")

    def test_create_project_writes_repo_local_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_base_dir = srv.PROJECTS_BASE_DIR
            try:
                srv.PROJECTS_BASE_DIR = tmpdir
                result = srv.create_project(
                    {
                        "project_name": "alpha-project",
                        "base_dir": tmpdir,
                        "overwrite": True,
                    }
                )
            finally:
                srv.PROJECTS_BASE_DIR = original_base_dir

            project_path = result["project_path"]
            mcp_path = os.path.join(project_path, ".mcp.json")
            self.assertTrue(os.path.exists(mcp_path))
            payload = json.loads(open(mcp_path, encoding="utf-8").read())
            self.assertIn("bridge", payload["mcpServers"])
            self.assertTrue(
                payload["mcpServers"]["bridge"]["args"][0].endswith("Backend/bridge_mcp.py")
            )

    def test_open_agent_sessions_forwards_runtime_profiles_to_wrapper(self):
        captured = []
        original_create = srv.create_agent_session
        try:
            def fake_create_agent_session(**kwargs):
                captured.append(kwargs)
                return True

            srv.create_agent_session = fake_create_agent_session
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "agent_a_engine": "codex",
                    "agent_b_engine": "qwen",
                    "project_path": tmpdir,
                    "team_lead_cli_enabled": True,
                    "team_lead_engine": "claude",
                    "team_lead_scope_file": os.path.join(tmpdir, "teamlead.md"),
                    "agent_profiles": [
                        {
                            "id": "codex",
                            "slot": "a",
                            "name": "Implementer",
                            "engine": "codex",
                            "role": "Implementer",
                            "description": "Implementiert Features.",
                            "prompt": "Implementiere Features.",
                            "model": "gpt-5.3-codex",
                            "permission_mode": "dontAsk",
                            "tools": ["Read", "Write", "Edit", "Bash"],
                            "capabilities": ["code"],
                            "scope": ["src"],
                            "team": "delivery",
                            "reports_to": "teamlead",
                            "level": 3,
                        },
                        {
                            "id": "qwen",
                            "slot": "b",
                            "name": "Reviewer",
                            "engine": "qwen",
                            "role": "Reviewer",
                            "description": "Prueft Qualitaet.",
                            "prompt": "Pruefe Qualitaet.",
                            "model": "qwen3-coder-plus",
                            "permission_mode": "acceptEdits",
                            "tools": ["Read", "Edit"],
                            "capabilities": ["review"],
                            "scope": ["tests"],
                            "team": "delivery",
                            "reports_to": "teamlead",
                            "level": 2,
                        },
                        {
                            "id": "teamlead",
                            "slot": "lead",
                            "name": "Lead",
                            "engine": "claude",
                            "role": "Koordinator",
                            "description": "Koordiniert das Team.",
                            "prompt": "Koordiniere das Team.",
                            "model": "claude-sonnet-4-6",
                            "permission_mode": "plan",
                            "tools": ["Read", "WebFetch"],
                            "capabilities": ["strategy"],
                            "scope": ["docs"],
                            "team": "management",
                            "reports_to": "user",
                            "level": 1,
                        },
                    ],
                }

                started = srv.open_agent_sessions(config)

            self.assertEqual(len(started), 3)
            calls = {item["agent_id"]: item for item in captured}
            self.assertEqual(calls["codex"]["role"], "Implementer")
            self.assertEqual(calls["codex"]["role_description"], "Implementiere Features.")
            self.assertEqual(calls["codex"]["model"], "gpt-5.3-codex")
            self.assertEqual(calls["codex"]["permission_mode"], "dontAsk")
            self.assertEqual(calls["codex"]["permissions"], ["code"])
            self.assertEqual(calls["codex"]["scope"], ["src"])
            self.assertEqual(calls["codex"]["allowed_tools"], ["Read", "Write", "Edit", "Bash"])

            self.assertEqual(calls["teamlead"]["role"], "Koordinator")
            self.assertEqual(calls["teamlead"]["role_description"], "Koordiniere das Team.")
            teammate_ids = {member["id"] for member in calls["teamlead"]["team_members"]}
            self.assertIn("codex", teammate_ids)
            self.assertIn("qwen", teammate_ids)
        finally:
            srv.create_agent_session = original_create

    def test_open_agent_sessions_uses_explicit_runtime_specs_for_multi_agent_runtime(self):
        captured = []
        original_create = srv.create_agent_session
        try:
            def fake_create_agent_session(**kwargs):
                captured.append(kwargs)
                return True

            srv.create_agent_session = fake_create_agent_session
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "pair_mode": "multi",
                    "agent_a_engine": "claude",
                    "agent_b_engine": "claude",
                    "project_path": tmpdir,
                    "team_lead_cli_enabled": False,
                    "runtime_specs": [
                        {"slot": "agent_1", "id": "claude_1", "engine": "claude", "name": "Claude 1", "peer": ""},
                        {"slot": "agent_2", "id": "claude_2", "engine": "claude", "name": "Claude 2", "peer": ""},
                        {"slot": "agent_3", "id": "gemini_1", "engine": "gemini", "name": "Gemini 1", "peer": "claude_1"},
                        {"slot": "agent_4", "id": "qwen_1", "engine": "qwen", "name": "Qwen 1", "peer": "claude_1"},
                    ],
                    "agent_profiles": [
                        {
                            "id": "claude_1",
                            "slot": "agent_1",
                            "name": "Claude Alpha",
                            "engine": "claude",
                            "role": "Lead Analyst",
                            "description": "Koordiniert den Lauf.",
                            "prompt": "Koordiniere und analysiere.",
                            "model": "claude-sonnet-4-6",
                            "permission_mode": "default",
                            "tools": ["Read", "Bash"],
                            "capabilities": ["strategy"],
                            "scope": ["Backend"],
                            "team": "dogfood",
                            "reports_to": "user",
                            "level": 1,
                        },
                        {
                            "id": "claude_2",
                            "slot": "agent_2",
                            "name": "Claude Beta",
                            "engine": "claude",
                            "role": "Implementer",
                            "description": "Implementiert.",
                            "prompt": "Implementiere.",
                            "model": "claude-sonnet-4-6",
                            "permission_mode": "dontAsk",
                            "tools": ["Read", "Write", "Edit", "Bash"],
                            "capabilities": ["code"],
                            "scope": ["Frontend"],
                            "team": "dogfood",
                            "reports_to": "claude_1",
                            "level": 3,
                        },
                        {
                            "id": "gemini_1",
                            "slot": "agent_3",
                            "name": "Gemini Reviewer",
                            "engine": "gemini",
                            "role": "Reviewer",
                            "description": "Reviewt.",
                            "prompt": "Review.",
                            "model": "gemini-2.5-pro",
                            "permission_mode": "acceptEdits",
                            "tools": ["Read", "Edit"],
                            "capabilities": ["review"],
                            "scope": ["tests"],
                            "team": "dogfood",
                            "reports_to": "claude_1",
                            "level": 2,
                        },
                        {
                            "id": "qwen_1",
                            "slot": "agent_4",
                            "name": "Qwen QA",
                            "engine": "qwen",
                            "role": "QA",
                            "description": "Prueft Risiken.",
                            "prompt": "QA.",
                            "model": "qwen3-coder-plus",
                            "permission_mode": "acceptEdits",
                            "tools": ["Read", "Edit"],
                            "capabilities": ["qa"],
                            "scope": ["docs"],
                            "team": "dogfood",
                            "reports_to": "claude_1",
                            "level": 3,
                        },
                    ],
                }

                started = srv.open_agent_sessions(config)

            self.assertEqual(len(started), 4)
            calls = {item["agent_id"]: item for item in captured}
            self.assertEqual(set(calls), {"claude_1", "claude_2", "gemini_1", "qwen_1"})
            self.assertEqual(calls["claude_2"]["engine"], "claude")
            self.assertEqual(calls["gemini_1"]["engine"], "gemini")
            self.assertEqual(calls["qwen_1"]["engine"], "qwen")
            self.assertEqual(calls["claude_2"]["permission_mode"], "dontAsk")
            self.assertEqual(calls["gemini_1"]["role_description"], "Review.")
            teammate_ids = {member["id"] for member in calls["claude_1"]["team_members"]}
            self.assertIn("claude_2", teammate_ids)
            self.assertIn("gemini_1", teammate_ids)
            self.assertIn("qwen_1", teammate_ids)
        finally:
            srv.create_agent_session = original_create

    def test_open_agent_sessions_propagates_start_failure_details(self):
        original_create = srv.create_agent_session
        original_consume = srv.consume_agent_start_failure
        try:
            def fake_create_agent_session(**_kwargs):
                return False

            def fake_consume_agent_start_failure(agent_id: str):
                if agent_id == "claude":
                    return {
                        "stage": "credential_prevalidation",
                        "reason": "usage_limit_reached",
                        "detail": "You've hit your limit · resets Mar 16, 2am (Europe/Berlin)",
                    }
                return {}

            srv.create_agent_session = fake_create_agent_session
            srv.consume_agent_start_failure = fake_consume_agent_start_failure
            with tempfile.TemporaryDirectory() as tmpdir:
                config = {
                    "agent_a_engine": "codex",
                    "agent_b_engine": "claude",
                    "project_path": tmpdir,
                    "team_lead_cli_enabled": False,
                }

                started = srv.open_agent_sessions(config)

            failed = {item["id"]: item for item in started}
            self.assertFalse(failed["codex"]["alive"])
            self.assertEqual(failed["claude"]["error_stage"], "credential_prevalidation")
            self.assertEqual(failed["claude"]["error_reason"], "usage_limit_reached")
            self.assertIn("hit your limit", failed["claude"]["error_detail"].lower())
        finally:
            srv.create_agent_session = original_create
            srv.consume_agent_start_failure = original_consume


if __name__ == "__main__":
    unittest.main()
