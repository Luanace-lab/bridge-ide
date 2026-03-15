from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
PROJECT_CONFIG_PATH = os.path.join(REPO_ROOT, "BRIDGE", "Frontend", "project_config.html")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestProjectConfigScanServerContract(unittest.TestCase):
    def test_build_context_map_includes_all_wrapped_cli_engines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = srv.build_context_map(tmpdir)

        for engine in ("claude", "codex", "gemini", "qwen"):
            self.assertIn(engine, context)

        self.assertIn("instruction_candidates", context["gemini"])
        self.assertIn("settings", context["gemini"])
        self.assertIn("instruction_candidates", context["qwen"])
        self.assertIn("settings", context["qwen"])
        self.assertTrue(
            any(item.get("source") == "GEMINI.md" for item in context["gemini"]["instruction_candidates"])
        )
        self.assertTrue(
            any(item.get("source") == "QWEN.md" for item in context["qwen"]["instruction_candidates"])
        )


class TestProjectConfigScanFrontendContract(unittest.TestCase):
    def _read(self) -> str:
        return Path(PROJECT_CONFIG_PATH).read_text(encoding="utf-8")

    def test_project_config_scan_renders_all_supported_cli_engines(self) -> None:
        raw = self._read()
        self.assertIn("for(const engine of ['claude','codex','gemini','qwen'])", raw)

    def test_folder_picker_does_not_fake_absolute_project_path(self) -> None:
        raw = self._read()
        self.assertNotIn("document.getElementById('projPath').value = dirHandle.name;", raw)
        self.assertIn("Browser liefert keinen absoluten Pfad", raw)

    def test_project_create_uses_projects_base_lookup_and_path_resolution(self) -> None:
        raw = self._read()
        self.assertIn("let allowedProjectsBaseDir = ''", raw)
        self.assertIn("async function loadAllowedProjectsBaseDir()", raw)
        self.assertIn("const res = await fetch(API_SERVER + '/projects')", raw)
        self.assertIn("function resolveCreateBaseDir(projectPath, projectName)", raw)
        self.assertIn("Projekt-Erstellung ist nur innerhalb von ", raw)
        self.assertIn("base_dir: baseDirResolution.baseDir,", raw)

    def test_runtime_configure_error_projection_prefers_failed_detail(self) -> None:
        raw = self._read()
        self.assertIn("function formatRuntimeConfigureError(data)", raw)
        self.assertIn("const failures = Array.isArray(data.failed) ? data.failed : [];", raw)
        self.assertIn("const detail = first.error_detail || first.error_reason || data.error", raw)
        self.assertIn("showFeedback(startTeamBtn.parentNode, 'error', formatRuntimeConfigureError(data));", raw)


if __name__ == "__main__":
    unittest.main()
