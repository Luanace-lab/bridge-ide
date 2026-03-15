#!/usr/bin/env python3
"""
Regression tests for migrating existing legacy .agent memory into canonical notes.
"""

from __future__ import annotations

import json
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
                    float(sum(ord(ch) for ch in text) % 89 + 1),
                    1.0,
                ]
            )
        return np.array(rows, dtype=float)


@pytest.fixture
def migration_env(tmp_path, monkeypatch):
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


class TestLegacyMemoryMigration:
    def test_migrate_legacy_memory_syncs_project_and_agent_notes(self, tmp_path, migration_env):
        ke, sm = migration_env
        project_path = tmp_path / "Bridge Project"
        (project_path / ".agent" / "project").mkdir(parents=True)
        (project_path / ".agent" / "agents").mkdir(parents=True)
        (project_path / ".agent" / "episodes").mkdir(parents=True)
        (project_path / ".agent" / "project" / "PROJECT.md").write_text(
            "Legacy project context to migrate.", encoding="utf-8"
        )
        (project_path / ".agent" / "project" / "DECISIONS.md").write_text(
            "Legacy decision log.", encoding="utf-8"
        )
        (project_path / ".agent" / "agents" / "kai.md").write_text(
            "Legacy private Kai context.", encoding="utf-8"
        )
        (project_path / ".agent" / "episodes" / "index.jsonl").write_text("", encoding="utf-8")

        result = srv.migrate_legacy_agent_memory(str(project_path))

        assert result["ok"]
        assert result["project_notes_synced"] == 2
        assert result["agent_notes_synced"] == 1

        project_scope = result["knowledge_sync"]["project_scope"]
        assert (Path(ke._VAULT_DIR) / "Projects" / project_scope / "PROJECT.md").exists()
        assert (Path(ke._VAULT_DIR) / "Agents" / "kai" / "PROJECT_MEMORY" / f"{project_scope}.md").exists()

        searched = sm.search_scope("project", project_scope, "project context to migrate", alpha=0.0)
        assert searched["results"]
        agent_search = sm.search_scope("agent", "kai", "private Kai context", alpha=0.0)
        assert agent_search["results"]

    def test_migrate_legacy_memory_syncs_indexed_episodes(self, tmp_path, migration_env):
        ke, sm = migration_env
        project_path = tmp_path / "Bridge Project"
        base = project_path / ".agent" / "episodes"
        base.mkdir(parents=True)
        episode_name = "2026-03-09__workflow__done.md"
        (base / episode_name).write_text("Workflow finished successfully.", encoding="utf-8")
        (base / "index.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-09T12:00:00Z",
                    "agent_id": "kai",
                    "task": "workflow deploy",
                    "summary_file": episode_name,
                    "summary_bullets": ["Workflow finished successfully."],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = srv.migrate_legacy_agent_memory(str(project_path))

        assert result["ok"]
        assert result["episodes_synced"] == 1
        project_scope = result["knowledge_sync"]["project_scope"]
        episode_dir = Path(ke._VAULT_DIR) / "Projects" / project_scope / "EPISODES"
        assert any(path.name.startswith("kai__") for path in episode_dir.iterdir())

        searched = sm.search_scope("project", project_scope, "Workflow finished successfully", alpha=0.0)
        assert searched["results"]

    def test_memory_status_reports_migration_required_for_unmigrated_legacy_data(
        self, tmp_path, migration_env
    ):
        _ke, _sm = migration_env
        project_path = tmp_path / "Bridge Project"
        (project_path / ".agent" / "project").mkdir(parents=True)
        (project_path / ".agent" / "project" / "PROJECT.md").write_text(
            "Legacy project context waiting for migration.", encoding="utf-8"
        )

        status = srv.get_memory_status(str(project_path))

        assert status["initialized"] is True
        assert status["knowledge_sync"]["migration_required"] is True
        assert status["knowledge_sync"]["legacy_candidates"] >= 1
