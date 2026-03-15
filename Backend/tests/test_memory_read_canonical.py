#!/usr/bin/env python3
"""
Regression tests for canonical reads via /memory/read helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as srv  # noqa: E402


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False):
        rows = []
        for text in texts:
            rows.append(
                [
                    float(len(text)),
                    float(sum(ord(ch) for ch in text) % 103 + 1),
                    1.0,
                ]
            )
        return np.array(rows, dtype=float)


@pytest.fixture
def canonical_read_env(tmp_path, monkeypatch):
    import knowledge_engine as ke
    import semantic_memory as sm

    vault_dir = tmp_path / "Knowledge"
    semantic_dir = tmp_path / "semantic"
    monkeypatch.setattr(ke, "_VAULT_DIR", str(vault_dir), raising=False)
    monkeypatch.setattr(sm, "MEMORY_BASE_DIR", str(semantic_dir), raising=False)
    monkeypatch.setattr(sm, "_MODEL", _FakeEmbeddingModel(), raising=False)
    monkeypatch.setattr(sm, "_get_model", lambda: sm._MODEL, raising=False)
    sm._AGENT_LOCKS.clear()
    return ke, sm


class TestCanonicalMemoryReads:
    def test_read_agent_memory_uses_canonical_notes_without_legacy_tree(
        self, tmp_path, canonical_read_env
    ):
        ke, _sm = canonical_read_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        project_scope = srv._legacy_memory_project_scope(str(project_path))
        ke.init_vault()
        ke.init_project_vault(project_scope)
        ke.init_agent_vault("kai")
        ke.write_note(f"Projects/{project_scope}/PROJECT", "Canonical project context.")
        ke.write_note(f"Projects/{project_scope}/DECISIONS", "Canonical ADR entry.")
        ke.write_note(
            f"Agents/kai/PROJECT_MEMORY/{project_scope}",
            "Canonical private note for Kai.",
        )

        result = srv.read_agent_memory(str(project_path), "kai", max_tokens=600)

        assert "Canonical project context." in result["packet"]
        assert "Canonical ADR entry." in result["packet"]
        assert "Canonical private note for Kai." in result["packet"]
        assert any(path.endswith(f"Projects/{project_scope}/PROJECT.md") for path in result["files_read"])
        assert any(path.endswith(f"Agents/kai/PROJECT_MEMORY/{project_scope}.md") for path in result["files_read"])

    def test_read_agent_memory_prefers_canonical_over_legacy_when_divergent(
        self, tmp_path, canonical_read_env
    ):
        ke, _sm = canonical_read_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        base = project_path / ".agent"
        (base / "project").mkdir(parents=True)
        (base / "agents").mkdir(parents=True)
        (base / "episodes").mkdir(parents=True)
        (base / "project" / "PROJECT.md").write_text("Legacy project context.", encoding="utf-8")
        (base / "agents" / "kai.md").write_text("Legacy private note.", encoding="utf-8")
        (base / "episodes" / "index.jsonl").write_text("", encoding="utf-8")

        project_scope = srv._legacy_memory_project_scope(str(project_path))
        ke.init_vault()
        ke.init_project_vault(project_scope)
        ke.init_agent_vault("kai")
        ke.write_note(f"Projects/{project_scope}/PROJECT", "Canonical truth for project.")
        ke.write_note(
            f"Agents/kai/PROJECT_MEMORY/{project_scope}",
            "Canonical truth for Kai.",
        )

        result = srv.read_agent_memory(str(project_path), "kai", max_tokens=600)

        assert "Canonical truth for project." in result["packet"]
        assert "Canonical truth for Kai." in result["packet"]
        assert "Legacy project context." not in result["packet"]
        assert "Legacy private note." not in result["packet"]

    def test_read_agent_memory_loads_recent_episodes_from_canonical_vault(
        self, tmp_path, canonical_read_env
    ):
        ke, _sm = canonical_read_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        project_scope = srv._legacy_memory_project_scope(str(project_path))
        ke.init_vault()
        ke.init_project_vault(project_scope)
        ke.write_note(
            f"Projects/{project_scope}/EPISODES/kai__2026-03-09__deploy.md",
            "Deployed the workflow compiler.\nValidated end-to-end.",
            {
                "agent": "kai",
                "task": "workflow deploy",
                "updated": "2026-03-09T10:00:00Z",
            },
        )

        result = srv.read_agent_memory(str(project_path), "kai", max_tokens=600)

        assert "workflow deploy" in result["packet"]
        assert "Deployed the workflow compiler." in result["packet"]
        assert any("EPISODES" in path for path in result["files_read"])
