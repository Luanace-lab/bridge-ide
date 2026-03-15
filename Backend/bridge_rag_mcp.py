#!/usr/bin/env python3
"""RAG MCP Server — ChromaDB-backed retrieval-augmented generation layer.

Provides 3 tools for agent access to persistent vector knowledge:
  - rag_store:  Store documents with scope + metadata
  - rag_query:  Semantic search across scoped collections
  - rag_delete: Remove documents by ID

Scopes:
  - global:           Shared across all agents/projects
  - project:<name>:   Per-project knowledge
  - agent:<agent_id>: Per-agent private knowledge

Storage: ~/.config/bridge/rag/ (ChromaDB persistent client)
Embedding: ChromaDB default (all-MiniLM-L6-v2 via ONNX)
Transport: stdio (FastMCP)
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import time
from typing import Any

import chromadb
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RAG_DATA_DIR = os.path.expanduser("~/.config/bridge/rag")
MAX_DOCUMENT_SIZE = 50_000  # chars
MAX_RESULTS = 50
DEFAULT_RESULTS = 10
VALID_SCOPES = ("global", "project", "agent")

log = logging.getLogger("bridge_rag_mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [rag_mcp] %(message)s")

# ---------------------------------------------------------------------------
# ChromaDB client (lazy singleton)
# ---------------------------------------------------------------------------
_CLIENT: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    os.makedirs(RAG_DATA_DIR, exist_ok=True)
    _CLIENT = chromadb.PersistentClient(path=RAG_DATA_DIR)
    log.info("ChromaDB client initialized at %s", RAG_DATA_DIR)
    return _CLIENT


def _collection_name(scope: str) -> str:
    """Map scope string to ChromaDB collection name.

    Valid formats: 'global', 'project:<name>', 'agent:<agent_id>'
    Collection names: 'rag_global', 'rag_project_<name>', 'rag_agent_<id>'
    """
    if scope == "global":
        return "rag_global"
    if ":" not in scope:
        raise ValueError(f"Invalid scope: {scope!r}. Use 'global', 'project:<name>', or 'agent:<id>'")
    prefix, _, name = scope.partition(":")
    name = name.strip()
    if prefix not in VALID_SCOPES or not name:
        raise ValueError(f"Invalid scope: {scope!r}. Use 'global', 'project:<name>', or 'agent:<id>'")
    # ChromaDB collection names: 3-63 chars, alphanumeric + underscore/hyphen
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:50]
    return f"rag_{prefix}_{safe_name}"


def _make_id(content: str, scope: str) -> str:
    """Generate deterministic document ID from content + scope."""
    h = hashlib.sha256(f"{scope}:{content}".encode("utf-8")).hexdigest()[:16]
    return f"doc_{h}"


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP("bridge-rag")


@mcp.tool()
def rag_store(
    content: str,
    scope: str = "global",
    source: str = "",
    tags: str = "",
    doc_id: str = "",
) -> dict[str, Any]:
    """Store a document in the RAG knowledge base.

    Args:
        content: The text content to store (max 50k chars).
        scope: 'global', 'project:<name>', or 'agent:<agent_id>'.
        source: Optional source identifier (file path, URL, etc.).
        tags: Optional comma-separated tags for filtering.
        doc_id: Optional custom document ID (auto-generated if empty).

    Returns:
        dict with stored document ID and collection info.
    """
    if not content or not content.strip():
        return {"ok": False, "error": "Content must not be empty"}
    if len(content) > MAX_DOCUMENT_SIZE:
        return {"ok": False, "error": f"Content exceeds {MAX_DOCUMENT_SIZE} char limit ({len(content)} chars)"}

    try:
        col_name = _collection_name(scope)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # Sanitize metadata
    safe_source = html.escape(source)[:500] if source else ""
    safe_tags = html.escape(tags)[:500] if tags else ""
    final_id = doc_id.strip() if doc_id else _make_id(content, scope)

    client = _get_client()
    collection = client.get_or_create_collection(name=col_name)

    metadata: dict[str, str] = {
        "scope": scope,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if safe_source:
        metadata["source"] = safe_source
    if safe_tags:
        metadata["tags"] = safe_tags

    collection.upsert(
        ids=[final_id],
        documents=[content],
        metadatas=[metadata],
    )

    log.info("Stored doc %s in %s (%d chars)", final_id, col_name, len(content))
    return {
        "ok": True,
        "doc_id": final_id,
        "collection": col_name,
        "scope": scope,
        "chars": len(content),
    }


@mcp.tool()
def rag_query(
    query: str,
    scope: str = "global",
    n_results: int = 10,
    tags_filter: str = "",
) -> dict[str, Any]:
    """Search the RAG knowledge base with semantic similarity.

    Args:
        query: The search query text.
        scope: 'global', 'project:<name>', or 'agent:<agent_id>'.
        n_results: Number of results to return (1-50, default 10).
        tags_filter: Optional — only return docs matching this tag substring.

    Returns:
        dict with matching documents, scores, and metadata.
    """
    if not query or not query.strip():
        return {"ok": False, "error": "Query must not be empty"}

    n_results = max(1, min(n_results, MAX_RESULTS))

    try:
        col_name = _collection_name(scope)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    client = _get_client()
    try:
        collection = client.get_collection(name=col_name)
    except Exception:
        return {"ok": True, "results": [], "count": 0, "scope": scope,
                "note": f"No data in scope {scope!r} yet"}

    count = collection.count()
    if count == 0:
        return {"ok": True, "results": [], "count": 0, "scope": scope}

    # Don't request more than available
    actual_n = min(n_results, count)

    where_filter = None
    if tags_filter:
        where_filter = {"tags": {"$contains": tags_filter}}

    try:
        result = collection.query(
            query_texts=[query],
            n_results=actual_n,
            where=where_filter if tags_filter else None,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Query failed: {exc}"}

    results = []
    if result["ids"] and result["ids"][0]:
        for i, doc_id in enumerate(result["ids"][0]):
            entry: dict[str, Any] = {"doc_id": doc_id}
            if result["documents"] and result["documents"][0]:
                entry["content"] = result["documents"][0][i]
            if result["distances"] and result["distances"][0]:
                entry["distance"] = round(result["distances"][0][i], 4)
            if result["metadatas"] and result["metadatas"][0]:
                entry["metadata"] = result["metadatas"][0][i]
            results.append(entry)

    return {
        "ok": True,
        "results": results,
        "count": len(results),
        "scope": scope,
        "total_docs": count,
    }


@mcp.tool()
def rag_delete(
    doc_id: str = "",
    scope: str = "global",
    delete_all: bool = False,
) -> dict[str, Any]:
    """Delete document(s) from the RAG knowledge base.

    Args:
        doc_id: The document ID to delete. Required unless delete_all=True.
        scope: 'global', 'project:<name>', or 'agent:<agent_id>'.
        delete_all: If True, delete ALL documents in the scope (dangerous!).

    Returns:
        dict confirming deletion.
    """
    if not doc_id and not delete_all:
        return {"ok": False, "error": "Provide doc_id or set delete_all=True"}

    try:
        col_name = _collection_name(scope)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    client = _get_client()
    try:
        collection = client.get_collection(name=col_name)
    except Exception:
        return {"ok": True, "deleted": 0, "note": f"Collection {col_name} does not exist"}

    if delete_all:
        count_before = collection.count()
        client.delete_collection(name=col_name)
        log.info("Deleted collection %s (%d docs)", col_name, count_before)
        return {"ok": True, "deleted": count_before, "scope": scope, "action": "collection_deleted"}

    try:
        collection.delete(ids=[doc_id])
    except Exception as exc:
        return {"ok": False, "error": f"Delete failed: {exc}"}

    log.info("Deleted doc %s from %s", doc_id, col_name)
    return {"ok": True, "deleted": 1, "doc_id": doc_id, "scope": scope}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting RAG MCP Server (ChromaDB @ %s)", RAG_DATA_DIR)
    mcp.run(transport="stdio")
