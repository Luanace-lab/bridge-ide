#!/usr/bin/env python3
"""
Regression tests for the canonical memory scope model.

The target architecture is:
- human-readable knowledge vault as canonical source of truth
- semantic retrieval indexed by explicit scopes
- supported scopes: user, project, team, agent, global
- legacy agent_id flows remain backward compatible
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False):
        rows = []
        for text in texts:
            rows.append(
                [
                    float(len(text)),
                    float(sum(ord(ch) for ch in text) % 97 + 1),
                    1.0,
                ]
            )
        return np.array(rows, dtype=float)


@pytest.fixture
def semantic_env(tmp_path, monkeypatch):
    import semantic_memory as sm

    monkeypatch.setattr(sm, "MEMORY_BASE_DIR", str(tmp_path / "semantic"), raising=False)
    monkeypatch.setattr(sm, "_MODEL", _FakeEmbeddingModel(), raising=False)
    monkeypatch.setattr(sm, "_get_model", lambda: sm._MODEL, raising=False)
    sm._AGENT_LOCKS.clear()
    return sm


@pytest.fixture
def knowledge_env(tmp_path, monkeypatch, semantic_env):
    import knowledge_engine as ke

    vault_dir = tmp_path / "Knowledge"
    monkeypatch.setattr(ke, "_VAULT_DIR", str(vault_dir), raising=False)
    return ke


class TestCanonicalKnowledgeScopes:
    def test_init_vault_creates_canonical_scope_dirs(self, knowledge_env):
        result = knowledge_env.init_vault()

        assert result["ok"]
        assert (Path(knowledge_env._VAULT_DIR) / "Users").is_dir()
        assert (Path(knowledge_env._VAULT_DIR) / "Projects").is_dir()
        assert (Path(knowledge_env._VAULT_DIR) / "Teams").is_dir()
        assert (Path(knowledge_env._VAULT_DIR) / "Agents").is_dir()
        assert (Path(knowledge_env._VAULT_DIR) / "Shared").is_dir()

    def test_init_user_vault_creates_user_profile(self, knowledge_env):
        knowledge_env.init_vault()

        result = knowledge_env.init_user_vault("testuser")

        assert result["ok"]
        user_dir = Path(knowledge_env._VAULT_DIR) / "Users" / "testuser"
        assert (user_dir / "USER.md").exists()
        assert (user_dir / "DAILY").is_dir()


class TestScopedSemanticMemory:
    def test_scope_upsert_and_delete_document(self, semantic_env):
        first = semantic_env.index_scoped_text(
            "user",
            "testuser",
            "Testuser likes direct status summaries.",
            metadata={"source": "test"},
            document_id="Users/testuser/USER.md",
        )
        assert first["ok"]
        assert first["chunks_added"] == 1

        original = semantic_env.search_scope(
            "user",
            "testuser",
            "status summaries",
            alpha=0.0,
        )
        assert original["results"]
        assert original["results"][0]["document_id"] == "Users/testuser/USER.md"

        second = semantic_env.index_scoped_text(
            "user",
            "testuser",
            "Testuser prefers concise German briefings.",
            metadata={"source": "test"},
            document_id="Users/testuser/USER.md",
        )
        assert second["ok"]
        assert second["total_chunks"] == 1

        updated = semantic_env.search_scope("user", "testuser", "German briefings", alpha=0.0)
        assert updated["results"]
        assert "concise German" in updated["results"][0]["text"]

        old_term = semantic_env.search_scope("user", "testuser", "status summaries", alpha=0.0)
        assert not old_term["results"]

        deleted = semantic_env.delete_document("user", "testuser", "Users/testuser/USER.md")
        assert deleted["ok"]
        assert deleted["deleted_chunks"] == 1

        after_delete = semantic_env.search_scope("user", "testuser", "German briefings", alpha=0.0)
        assert after_delete["results"] == []

    def test_legacy_agent_indexing_remains_compatible(self, semantic_env):
        indexed = semantic_env.index_text("kai", "Kai solved the DNS issue.", metadata={"source": "legacy"})
        assert indexed["ok"]

        result = semantic_env.search("kai", "DNS issue", alpha=0.0)
        assert result["results"]
        assert result["results"][0]["scope_type"] == "agent"
        assert result["results"][0]["scope_id"] == "kai"


class TestKnowledgeToSemanticSync:
    def test_user_note_write_and_delete_syncs_to_semantic_memory(self, knowledge_env, semantic_env):
        knowledge_env.init_vault()
        knowledge_env.init_user_vault("testuser")

        write_result = knowledge_env.write_note(
            "Users/testuser/USER",
            "Testuser likes concise replies and German summaries.",
            {"language": "de"},
        )
        assert write_result["ok"]

        indexed = semantic_env.search_scope("user", "testuser", "German summaries", alpha=0.0)
        assert indexed["results"]
        assert indexed["results"][0]["metadata"]["note_path"] == "Users/testuser/USER.md"

        knowledge_env.search_replace("Users/testuser/USER", "concise", "extremely concise")
        updated = semantic_env.search_scope("user", "testuser", "extremely concise", alpha=0.0)
        assert updated["results"]

        delete_result = knowledge_env.delete_note("Users/testuser/USER")
        assert delete_result["ok"]

        after_delete = semantic_env.search_scope("user", "testuser", "extremely concise", alpha=0.0)
        assert after_delete["results"] == []


class _CapturingHttpClient:
    def __init__(self):
        self.calls = []

    async def post(self, path, json=None, headers=None):
        self.calls.append({"path": path, "json": json, "headers": headers})
        return _FakeResponse({"ok": True})


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestBridgeMcpScopePayloads:
    def _mod(self):
        try:
            import bridge_mcp  # type: ignore
        except ImportError as exc:
            pytest.skip(f"bridge_mcp import skipped: {exc}")
        return bridge_mcp

    def test_memory_index_can_send_explicit_scope(self):
        mod = self._mod()
        http = _CapturingHttpClient()
        old_agent_id = mod._agent_id
        old_get_http = mod._get_http
        try:
            mod._agent_id = "buddy"
            mod._get_http = lambda: http
            raw = asyncio.run(
                mod.bridge_memory_index(
                    text="Testuser profile",
                    source="knowledge",
                    scope_type="user",
                    scope_id="testuser",
                    document_id="Users/testuser/USER.md",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._get_http = old_get_http

        payload = http.calls[0]["json"]
        assert payload["scope_type"] == "user"
        assert payload["scope_id"] == "testuser"
        assert payload["document_id"] == "Users/testuser/USER.md"
        assert "agent_id" not in payload
        assert json.loads(raw)["ok"] is True

    def test_memory_search_defaults_to_current_agent_scope(self):
        mod = self._mod()
        http = _CapturingHttpClient()
        old_agent_id = mod._agent_id
        old_get_http = mod._get_http
        try:
            mod._agent_id = "viktor"
            mod._get_http = lambda: http
            raw = asyncio.run(mod.bridge_memory_search(query="architecture"))
        finally:
            mod._agent_id = old_agent_id
            mod._get_http = old_get_http

        payload = http.calls[0]["json"]
        assert payload["agent_id"] == "viktor"
        assert "scope_type" not in payload
        assert json.loads(raw)["ok"] is True

    def test_memory_delete_can_send_explicit_scope(self):
        mod = self._mod()
        http = _CapturingHttpClient()
        old_agent_id = mod._agent_id
        old_get_http = mod._get_http
        try:
            mod._agent_id = "buddy"
            mod._get_http = lambda: http
            raw = asyncio.run(
                mod.bridge_memory_delete(
                    document_id="Users/testuser/USER.md",
                    scope_type="user",
                    scope_id="testuser",
                )
            )
        finally:
            mod._agent_id = old_agent_id
            mod._get_http = old_get_http

        payload = http.calls[0]["json"]
        assert payload["document_id"] == "Users/testuser/USER.md"
        assert payload["scope_type"] == "user"
        assert payload["scope_id"] == "testuser"
        assert "agent_id" not in payload
        assert json.loads(raw)["ok"] is True
