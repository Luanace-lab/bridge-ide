from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_engine_models as models_mod  # noqa: E402


class TestServerEngineModelContracts(unittest.TestCase):
    def test_server_reexports_cli_model_helpers(self):
        self.assertIs(srv._claude_models_from_cli, models_mod._claude_models_from_cli)
        self.assertIs(srv._codex_models_from_cli, models_mod._codex_models_from_cli)
        self.assertIs(srv._gemini_models_from_cli, models_mod._gemini_models_from_cli)
        self.assertIs(srv._qwen_models_from_cli, models_mod._qwen_models_from_cli)

    def test_engine_registry_wrapper_uses_server_level_monkeypatches(self):
        orig_detect = srv._detect_available_engines
        orig_claude = srv._claude_models_from_cli
        orig_codex = srv._codex_models_from_cli
        orig_gemini = srv._gemini_models_from_cli
        orig_qwen = srv._qwen_models_from_cli
        try:
            srv._detect_available_engines = lambda: {"codex"}
            srv._claude_models_from_cli = lambda: []
            srv._codex_models_from_cli = lambda: [{"id": "gpt-test", "label": "gpt-test", "default": True}]
            srv._gemini_models_from_cli = lambda: []
            srv._qwen_models_from_cli = lambda: []

            registry = srv._engine_model_registry()

            self.assertTrue(registry["codex"]["available"])
            self.assertEqual(registry["codex"]["source"], "codex-config+cache")
            self.assertEqual(registry["codex"]["models"][0]["id"], "gpt-test")
            self.assertFalse(registry["claude"]["available"])
        finally:
            srv._detect_available_engines = orig_detect
            srv._claude_models_from_cli = orig_claude
            srv._codex_models_from_cli = orig_codex
            srv._gemini_models_from_cli = orig_gemini
            srv._qwen_models_from_cli = orig_qwen

    def test_model_choice_wrapper_uses_server_level_registry(self):
        orig_registry = srv._engine_model_registry
        try:
            srv._engine_model_registry = lambda: {
                "claude": {
                    "models": [
                        {"id": "claude-sonnet-4-6", "alias": "sonnet", "label": "Sonnet 4.6"},
                    ]
                }
            }
            self.assertEqual(
                srv._resolve_engine_model_choice("claude", "sonnet"),
                "claude-sonnet-4-6",
            )
        finally:
            srv._engine_model_registry = orig_registry


if __name__ == "__main__":
    unittest.main(verbosity=2)
