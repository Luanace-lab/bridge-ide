#!/usr/bin/env python3
"""
Phase-2 regression tests for legacy .agent memory sync into the canonical vault.
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
                    float(sum(ord(ch) for ch in text) % 101 + 1),
                    1.0,
                ]
            )
        return np.array(rows, dtype=float)


@pytest.fixture
def scoped_memory_env(tmp_path, monkeypatch):
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


class TestLegacyMemoryCanonicalSync:
    def test_project_memory_write_mirrors_to_project_scope(self, tmp_path, scoped_memory_env):
        ke, sm = scoped_memory_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        result = srv.write_agent_memory(
            str(project_path),
            "alex",
            "project",
            "Project context from legacy memory.",
            mode="replace",
        )

        assert result["ok"]
        project_scope = result["knowledge_sync"]["project_scope"]
        note_path = Path(ke._VAULT_DIR) / "Projects" / project_scope / "PROJECT.md"
        assert note_path.exists()
        assert "Project context from legacy memory." in note_path.read_text(encoding="utf-8")

        searched = sm.search_scope("project", project_scope, "legacy memory", alpha=0.0)
        assert searched["results"]
        assert searched["results"][0]["metadata"]["note_path"] == f"Projects/{project_scope}/PROJECT.md"

    def test_agent_private_memory_write_mirrors_to_agent_scope(self, tmp_path, scoped_memory_env):
        ke, sm = scoped_memory_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        result = srv.write_agent_memory(
            str(project_path),
            "kai",
            "agent_private",
            "Private operational preference for Kai.",
            mode="replace",
        )

        assert result["ok"]
        project_scope = result["knowledge_sync"]["project_scope"]
        note_path = Path(ke._VAULT_DIR) / "Agents" / "kai" / "PROJECT_MEMORY" / f"{project_scope}.md"
        assert note_path.exists()

        searched = sm.search_scope("agent", "kai", "operational preference", alpha=0.0)
        assert searched["results"]
        assert searched["results"][0]["metadata"]["note_path"] == f"Agents/kai/PROJECT_MEMORY/{project_scope}.md"

    def test_episode_write_mirrors_to_project_scope(self, tmp_path, scoped_memory_env):
        ke, sm = scoped_memory_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        result = srv.write_episode(
            str(project_path),
            "codex",
            "Implemented canonical scope sync for memory.",
            task="scope-sync",
            metadata={"ticket": "PA-2"},
        )

        assert result["ok"]
        project_scope = result["knowledge_sync"]["project_scope"]
        knowledge_note = Path(result["knowledge_sync"]["note_file"])
        assert knowledge_note.exists()
        assert knowledge_note.parts[-4:-1] == ("Projects", project_scope, "EPISODES")

        searched = sm.search_scope("project", project_scope, "canonical scope sync", alpha=0.0)
        assert searched["results"]
        assert searched["results"][0]["document_id"].startswith(f"Projects/{project_scope}/EPISODES/")

    def test_scaffold_reports_canonical_project_scope(self, tmp_path, scoped_memory_env):
        ke, _sm = scoped_memory_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        result = srv.scaffold_agent_memory(str(project_path))

        assert result["ok"]
        project_scope = result["knowledge_sync"]["project_scope"]
        project_dir = Path(ke._VAULT_DIR) / "Projects" / project_scope
        assert project_dir.is_dir()
        assert (project_dir / "PROJECT.md").exists()

    def test_memory_status_exposes_canonical_scope_metadata(self, tmp_path, scoped_memory_env):
        _ke, _sm = scoped_memory_env
        project_path = tmp_path / "Bridge Project"
        project_path.mkdir()

        srv.scaffold_agent_memory(str(project_path))
        status = srv.get_memory_status(str(project_path))

        assert status["initialized"] is True
        assert "knowledge_sync" in status
        assert status["knowledge_sync"]["project_scope"]
