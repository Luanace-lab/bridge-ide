from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import capability_library  # noqa: E402


class TestCapabilityLibraryGeneratedData(unittest.TestCase):
    def test_generated_library_has_500_plus_entries(self) -> None:
        capability_library.clear_cache()
        self.assertTrue(capability_library.library_path().exists())
        self.assertGreaterEqual(capability_library.total_entries(), 500)
        meta = capability_library.metadata()
        self.assertGreaterEqual(int(meta.get("entry_count", 0)), 500)
        self.assertGreaterEqual(int(meta.get("official_entry_count", 0)), 10)
        self.assertGreaterEqual(int(meta.get("runtime_verified_count", 0)), 4)


class TestCapabilityLibraryQueries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="capability_library_")
        self.addCleanup(self._tmpdir.cleanup)
        self._orig_env = os.environ.get("BRIDGE_CAPABILITY_LIBRARY_PATH")
        sample = {
            "metadata": {
                "version": 1,
                "entry_count": 3,
                "official_entry_count": 2,
                "runtime_verified_count": 1,
            },
            "entries": [
                {
                    "id": "official::openai-docs-mcp",
                    "name": "OpenAI Docs MCP",
                    "title": "Official OpenAI Docs MCP",
                    "vendor": "openai",
                    "owner": "openai",
                    "summary": "Official docs MCP for OpenAI API documentation and examples.",
                    "type": "mcp",
                    "protocol": "mcp",
                    "transport": ["streamable_http"],
                    "install_methods": [{"kind": "remote_mcp", "url": "https://mcp.openai.com/mcp"}],
                    "auth_mode": "none",
                    "task_tags": ["docs", "research", "code"],
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
                    "id": "official::anthropic-claude-code-slash-commands",
                    "name": "Claude Code Slash Commands",
                    "title": "Claude Code Slash Commands",
                    "vendor": "anthropic",
                    "owner": "anthropic",
                    "summary": "Reusable slash commands for Claude Code workflows.",
                    "type": "custom-command",
                    "protocol": "local_cli",
                    "transport": ["local_process"],
                    "install_methods": [{"kind": "builtin_cli_capability", "command": "claude"}],
                    "auth_mode": "n/a",
                    "task_tags": ["automation", "productivity"],
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
                    "source_url": "https://docs.anthropic.com/en/docs/claude-code/slash-commands",
                },
                {
                    "id": "bridge-runtime::bridge",
                    "name": "bridge",
                    "title": "bridge",
                    "vendor": "bridge",
                    "owner": "bridge",
                    "summary": "Repo-local Bridge runtime MCP.",
                    "type": "mcp",
                    "protocol": "mcp",
                    "transport": ["stdio"],
                    "install_methods": [{"kind": "runtime_command", "command": "python3"}],
                    "auth_mode": "none",
                    "task_tags": ["automation"],
                    "engine_compatibility": {
                        "claude_code": "inferred",
                        "codex": "inferred",
                        "gemini_cli": "inferred",
                        "qwen_code": "inferred",
                    },
                    "reproducible": True,
                    "runtime_verified": True,
                    "status": "runtime_verified",
                    "trust_tier": "bridge",
                    "official_vendor": True,
                    "source_registry": "bridge_runtime_catalog",
                    "source_url": "config/mcp_catalog.json",
                },
            ],
        }
        self._library_path = Path(self._tmpdir.name) / "sample_capability_library.json"
        self._library_path.write_text(json.dumps(sample), encoding="utf-8")
        os.environ["BRIDGE_CAPABILITY_LIBRARY_PATH"] = str(self._library_path)
        capability_library.clear_cache()
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._orig_env is None:
            os.environ.pop("BRIDGE_CAPABILITY_LIBRARY_PATH", None)
        else:
            os.environ["BRIDGE_CAPABILITY_LIBRARY_PATH"] = self._orig_env
        capability_library.clear_cache()

    def test_list_entries_filters_by_cli_and_official_vendor(self) -> None:
        result = capability_library.list_entries(cli="claude", official_vendor=True, limit=10)
        self.assertEqual(result["count"], 3)
        exact = capability_library.list_entries(cli="claude", entry_type="custom-command", official_vendor=True, limit=10)
        self.assertEqual(exact["count"], 1)
        self.assertEqual(exact["entries"][0]["id"], "official::anthropic-claude-code-slash-commands")

    def test_search_entries_ranks_name_and_tags(self) -> None:
        result = capability_library.search_entries(query="openai docs", limit=5)
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["entries"][0]["id"], "official::openai-docs-mcp")
        self.assertGreater(result["entries"][0]["match_score"], 0)

    def test_recommend_entries_normalizes_engine_aliases(self) -> None:
        result = capability_library.recommend_entries(task="need a reusable slash command", engine="claude", top_k=5)
        self.assertEqual(result["cli"], "claude_code")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["id"], "official::anthropic-claude-code-slash-commands")

    def test_facets_include_expected_clis_and_tags(self) -> None:
        facets = capability_library.facets()
        self.assertIn("claude_code", facets["clis"])
        self.assertIn("codex", facets["clis"])
        self.assertIn("automation", facets["task_tags"])
        self.assertIn("official_docs", facets["source_registries"])


if __name__ == "__main__":
    unittest.main()
