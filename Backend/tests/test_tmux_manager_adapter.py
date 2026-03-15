from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from tmux_manager import (  # noqa: E402
    _agent_initial_prompt,
    _mcp_registry,
    _requested_mcp_names,
    _stabilize_claude_startup,
    _stabilize_codex_startup,
    _stabilize_gemini_startup,
    _tmux_engine_spec,
    _write_agent_runtime_config,
    generate_agent_claude_md,
)


class TestTmuxEngineSpec(unittest.TestCase):
    def test_claude_spec(self):
        spec = _tmux_engine_spec("claude")
        self.assertEqual(spec.engine, "claude")
        self.assertEqual(spec.instruction_filename, "CLAUDE.md")
        self.assertIn("claude", spec.start_shell)
        self.assertEqual(spec.submit_enter_count, 2)

    def test_codex_spec(self):
        spec = _tmux_engine_spec("codex")
        self.assertEqual(spec.engine, "codex")
        self.assertEqual(spec.instruction_filename, "AGENTS.md")
        self.assertIn("codex", spec.start_shell)
        self.assertEqual(spec.submit_enter_count, 1)
        self.assertIn("›", spec.ready_prompt_regex)

    def test_qwen_spec(self):
        spec = _tmux_engine_spec("qwen")
        self.assertEqual(spec.engine, "qwen")
        self.assertEqual(spec.instruction_filename, "QWEN.md")
        self.assertIn("qwen", spec.start_shell)
        self.assertRegex("*   Type your message or @path/to/file", spec.ready_prompt_regex)

    def test_gemini_spec(self):
        spec = _tmux_engine_spec("gemini")
        self.assertEqual(spec.engine, "gemini")
        self.assertEqual(spec.instruction_filename, "GEMINI.md")
        self.assertIn("gemini", spec.start_shell)
        self.assertRegex("*   Type your message or @path/to/file", spec.ready_prompt_regex)

    def test_unknown_engine_raises(self):
        with self.assertRaises(ValueError):
            _tmux_engine_spec("unknown")


class TestInitialPrompt(unittest.TestCase):
    def test_claude_initial_prompt_mentions_claude_md(self):
        prompt = _agent_initial_prompt("CLAUDE.md")
        self.assertIn("CLAUDE.md", prompt)
        self.assertIn("bridge_register", prompt)
        self.assertIn("STRICT SEQUENTIELL", prompt)
        self.assertIn("bridge_task_queue(state='created', limit=50)", prompt)

    def test_codex_initial_prompt_mentions_agents_md(self):
        prompt = _agent_initial_prompt("AGENTS.md")
        self.assertIn("AGENTS.md", prompt)
        self.assertIn("bridge_receive", prompt)


class TestInstructionRendering(unittest.TestCase):
    def test_generate_agent_doc_renders_permission_dict(self):
        content = generate_agent_claude_md(
            agent_id="viktor",
            role="Lead",
            role_description="Koordiniert das Team.",
            project_path="/tmp/project",
            team_members=[],
            permissions={"approval_required": True, "autonomy_level": "normal"},
            engine="claude",
        )
        self.assertIn("- approval_required: True", content)
        self.assertIn("- autonomy_level: normal", content)

    def test_generate_qwen_agent_doc_includes_capabilities_in_register_call(self):
        content = generate_agent_claude_md(
            agent_id="qwen_1",
            role="QA",
            role_description="Prueft die Runtime.",
            project_path="/tmp/project",
            team_members=[],
            engine="qwen",
            permissions=["qa"],
        )
        self.assertIn('bridge_register(agent_id="qwen_1", role="QA", capabilities=["qa"])', content)
        self.assertIn('{"agent_id": "qwen_1", "role": "QA", "capabilities": ["qa"]}', content)

    def test_generate_gemini_agent_doc_keeps_runtime_capabilities_in_register_call(self):
        content = generate_agent_claude_md(
            agent_id="gemini_1",
            role="Reviewer",
            role_description="Prueft die Runtime.",
            project_path="/tmp/project",
            team_members=[],
            engine="gemini",
            permissions=["review"],
        )
        self.assertIn('bridge_register(agent_id="gemini_1", role="Reviewer", capabilities=["review"])', content)
        self.assertIn('{"agent_id": "gemini_1", "role": "Reviewer", "capabilities": ["review"]}', content)

    def test_generate_codex_agent_doc_uses_runtime_report_recipient(self):
        content = generate_agent_claude_md(
            agent_id="codex_1",
            role="Implementer",
            role_description="Implementiert Features.",
            project_path="/tmp/project",
            team_members=[{"id": "claude_1", "role": "Lead Analyst"}],
            engine="codex",
            report_recipient="claude_1",
        )
        self.assertIn("Reports NUR an deinen Lead (claude_1), NICHT an user.", content)
        self.assertNotIn("Lead (viktor)", content)

    def test_generate_agent_doc_uses_bounded_shared_queue_reads(self):
        content = generate_agent_claude_md(
            agent_id="qwen_1",
            role="QA",
            role_description="Prueft die Runtime.",
            project_path="/tmp/project",
            team_members=[],
            engine="qwen",
            permissions=["qa"],
        )
        self.assertIn("bridge_task_queue(state='created', limit=50)", content)
        self.assertNotIn("bridge_task_queue(state='created')", content)
        self.assertIn('curl -s "http://127.0.0.1:9111/task/queue?state=created&limit=50"', content)


class TestRuntimeConfigWriting(unittest.TestCase):
    def test_catalog_backed_registry_contains_internal_servers(self):
        registry = _mcp_registry()
        self.assertIn("bridge", registry)
        self.assertIn("playwright", registry)
        self.assertIn("bridge-rag", registry)
        self.assertIn("n8n", registry)
        self.assertEqual(registry["playwright"]["args"], ["@playwright/mcp@0.0.68"])

    def test_all_requested_mcps_stays_catalog_scoped(self):
        requested = _requested_mcp_names("all")
        self.assertEqual(requested, ["bridge", "playwright", "aase", "ghost"])

    def test_write_claude_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            project_path = "/tmp/project-x"

            _write_agent_runtime_config(workspace, "claude", project_path)

            cfg = workspace / ".claude" / "settings.json"
            self.assertTrue(cfg.exists())
            data = json.loads(cfg.read_text(encoding="utf-8"))
            perms = data.get("permissions", {})
            self.assertIn(project_path, perms.get("additionalDirectories", []))
            allow = perms.get("allow", [])
            self.assertIn("mcp__bridge__bridge_register", allow)
            self.assertIn("mcp__bridge__bridge_receive", allow)

    def test_write_codex_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            project_path = "/tmp/project-y"

            _write_agent_runtime_config(
                workspace, "codex", project_path, permission_mode="dontAsk"
            )

            cfg = workspace / ".codex" / "config.toml"
            self.assertTrue(cfg.exists())
            raw = cfg.read_text(encoding="utf-8")
            self.assertIn('sandbox_mode = "workspace-write"', raw)
            self.assertIn('approval_policy = "never"', raw)
            self.assertIn('writable_roots = ["/tmp/project-y"]', raw)
            self.assertIn("[mcp_servers.bridge]", raw)
            self.assertIn('command = "python3"', raw)
            self.assertIn("bridge_mcp.py", raw)
            self.assertIn(f'[projects."{workspace}"]', raw)
            self.assertIn('trust_level = "trusted"', raw)
            codex_home_cfg = workspace / ".codex-home" / "config.toml"
            self.assertTrue(codex_home_cfg.exists())
            home_raw = codex_home_cfg.read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.bridge]", home_raw)
            self.assertIn("bridge_mcp.py", home_raw)
            self.assertIn(f'[projects."{workspace}"]', home_raw)
            self.assertIn('trust_level = "trusted"', home_raw)

    def test_write_codex_runtime_config_includes_requested_mcps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()

            _write_agent_runtime_config(
                workspace, "codex", "/tmp/project-y", mcp_servers="playwright,aase"
            )

            raw = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.playwright]", raw)
            self.assertIn('@playwright/mcp@0.0.68', raw)
            self.assertIn("[mcp_servers.aase]", raw)
            self.assertIn("aase_mcp.py", raw)

    def test_write_codex_runtime_config_supports_internal_optional_servers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()

            _write_agent_runtime_config(
                workspace, "codex", "/tmp/project-y", mcp_servers="bridge-rag,n8n"
            )

            raw = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.bridge-rag]", raw)
            self.assertIn("bridge_rag_mcp.py", raw)
            self.assertIn("[mcp_servers.n8n]", raw)
            self.assertIn("n8n_mcp.py", raw)

    def test_qwen_runtime_config_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            _write_agent_runtime_config(
                workspace,
                "qwen",
                "/tmp/project-z",
                model="qwen3-coder-plus",
                permission_mode="acceptEdits",
                allowed_tools=["Bash", "WebFetch"],
            )
            cfg = workspace / ".qwen" / "settings.json"
            self.assertTrue(cfg.exists())
            data = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(data["tools"]["approvalMode"], "auto-edit")
            self.assertIn("run_shell_command", data["tools"]["allowed"])
            self.assertIn("http_fetch", data["tools"]["allowed"])
            self.assertIn("bridge", data["mcpServers"])
            self.assertEqual(data["model"]["name"], "qwen3-coder-plus")
            trusted = json.loads((workspace / ".qwen" / "trustedFolders.json").read_text(encoding="utf-8"))
            self.assertEqual(trusted[str(workspace.resolve())], "TRUST_FOLDER")
            self.assertEqual(trusted["/tmp/project-z"], "TRUST_FOLDER")

    def test_gemini_runtime_config_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            _write_agent_runtime_config(
                workspace,
                "gemini",
                "/tmp/project-z",
                model="gemini-2.5-pro",
                permission_mode="plan",
                allowed_tools=["WebSearch"],
            )
            cfg = workspace / ".gemini" / "settings.json"
            self.assertTrue(cfg.exists())
            data = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(data["general"]["defaultApprovalMode"], "plan")
            self.assertIn("google_web_search", data["tools"]["allowed"])
            self.assertTrue(data["tools"]["sandbox"])
            self.assertIn("bridge", data["mcpServers"])
            self.assertEqual(data["model"]["name"], "gemini-2.5-pro")
            trusted = json.loads((workspace / ".gemini" / "trustedFolders.json").read_text(encoding="utf-8"))
            self.assertEqual(trusted[str(workspace.resolve())], "TRUST_FOLDER")
            self.assertEqual(trusted["/tmp/project-z"], "TRUST_FOLDER")

    def test_gemini_runtime_config_persists_auto_edit_for_unattended_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            _write_agent_runtime_config(
                workspace,
                "gemini",
                "/tmp/project-z",
                permission_mode="dontAsk",
            )
            data = json.loads((workspace / ".gemini" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(data["general"]["defaultApprovalMode"], "auto_edit")


class TestClaudeStartupStabilizer(unittest.TestCase):
    def test_accepts_trust_and_bypass_dialogs(self):
        captures = iter(
            [
                "Quick safety check\n1. Yes, I trust this folder",
                "WARNING: Claude Code running in Bypass Permissions mode\n2. Yes, I accept",
                "Welcome back Leo!\n❯",
            ]
        )
        sent_keys: list[str] = []

        with (
            mock.patch("tmux_manager._tmux_capture_text", side_effect=lambda *_args, **_kwargs: next(captures)),
            mock.patch("tmux_manager._tmux_send_key", side_effect=lambda _session, key: sent_keys.append(key) or True),
            mock.patch("tmux_manager._time.sleep"),
        ):
            _stabilize_claude_startup("bridge_test", permission_mode="bypassPermissions", timeout=5)

        self.assertEqual(sent_keys, ["Enter", "Down", "Enter"])

    def test_skips_bypass_acceptance_for_other_modes(self):
        captures = iter(
            [
                "WARNING: Claude Code running in Bypass Permissions mode\n2. Yes, I accept",
                "Welcome back Leo!\n❯",
            ]
        )
        sent_keys: list[str] = []

        with (
            mock.patch("tmux_manager._tmux_capture_text", side_effect=lambda *_args, **_kwargs: next(captures)),
            mock.patch("tmux_manager._tmux_send_key", side_effect=lambda _session, key: sent_keys.append(key) or True),
            mock.patch("tmux_manager._time.sleep"),
        ):
            _stabilize_claude_startup("bridge_test", permission_mode="default", timeout=5)

        self.assertEqual(sent_keys, [])

    def test_gemini_stabilizer_accepts_flash_fallback_prompt(self):
        captures = iter(
            [
                "Usage limit reached for all Pro models.\n1. Switch to gemini-2.5-flash",
                "*   Type your message or @path/to/file",
            ]
        )
        sent_keys: list[str] = []

        with (
            mock.patch("tmux_manager._tmux_capture_text", side_effect=lambda *_args, **_kwargs: next(captures)),
            mock.patch("tmux_manager._tmux_send_key", side_effect=lambda _session, key: sent_keys.append(key) or True),
            mock.patch("tmux_manager._time.sleep"),
        ):
            _stabilize_gemini_startup("bridge_test", timeout=5)

        self.assertEqual(sent_keys, ["Enter"])

    def test_codex_stabilizer_accepts_reasoning_level_prompt(self):
        captures = iter(
            [
                "Select Reasoning Level for gpt-5.1-codex-max\n› 2. Medium (default)\nPress enter to confirm or esc to go back",
                "› Explain this codebase",
            ]
        )
        sent_keys: list[str] = []

        with (
            mock.patch("tmux_manager._tmux_capture_text", side_effect=lambda *_args, **_kwargs: next(captures)),
            mock.patch("tmux_manager._tmux_send_key", side_effect=lambda _session, key: sent_keys.append(key) or True),
            mock.patch("tmux_manager._time.sleep"),
        ):
            _stabilize_codex_startup("bridge_test", timeout=5)

        self.assertEqual(sent_keys, ["Enter"])

    def test_codex_stabilizer_skips_update_prompt(self):
        captures = iter(
            [
                "Update available! 0.112.0 -> 0.113.0\n3. Skip until next version\nPress enter to continue",
                "› Explain this codebase",
            ]
        )
        sent_keys: list[str] = []

        with (
            mock.patch("tmux_manager._tmux_capture_text", side_effect=lambda *_args, **_kwargs: next(captures)),
            mock.patch("tmux_manager._tmux_send_key", side_effect=lambda _session, key: sent_keys.append(key) or True),
            mock.patch("tmux_manager._time.sleep"),
        ):
            _stabilize_codex_startup("bridge_test", timeout=5)

        self.assertEqual(sent_keys, ["Down", "Down", "Enter"])


if __name__ == "__main__":
    unittest.main()
