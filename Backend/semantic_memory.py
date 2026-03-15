"""
Semantic Memory — Vector + BM25 hybrid retrieval for scoped memory.

Uses sentence-transformers for embeddings + numpy for vector similarity.
BM25 via simple TF-IDF implementation (no external deps).
Per-scope indexes are stored in ~/.config/bridge/memory/{scope_type}__{scope_id}/
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections import Counter
from typing import Any

import numpy as np

log = logging.getLogger("semantic_memory")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MEMORY_BASE_DIR = os.path.expanduser("~/.config/bridge/memory")
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
MAX_CHUNKS_PER_AGENT = 50_000
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
VALID_SCOPE_TYPES = {"user", "project", "team", "agent", "global"}

# ---------------------------------------------------------------------------
# Lazy model loader
# ---------------------------------------------------------------------------
_MODEL = None
_MODEL_LOCK = threading.Lock()


def _get_model():
    """Lazy-load sentence-transformers model on first use."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)
            log.info("Loaded embedding model: %s (dim=%d)", EMBEDDING_MODEL_NAME, EMBEDDING_DIM)
        except Exception as exc:
            log.error("Failed to load embedding model: %s", exc)
            raise
        return _MODEL


# ---------------------------------------------------------------------------
# Per-index lock
# ---------------------------------------------------------------------------
_AGENT_LOCKS: dict[str, threading.Lock] = {}
_AGENT_LOCKS_GLOBAL = threading.Lock()


def _agent_lock(index_key: str) -> threading.Lock:
    """Get or create a per-index lock."""
    with _AGENT_LOCKS_GLOBAL:
        if index_key not in _AGENT_LOCKS:
            _AGENT_LOCKS[index_key] = threading.Lock()
        return _AGENT_LOCKS[index_key]


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------
def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - chunk_overlap
    return chunks


# ---------------------------------------------------------------------------
# Simple BM25 (TF-IDF based, no external deps)
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    return re.findall(r"\w+", text.lower())


class SimpleBM25:
    """Minimal BM25 implementation."""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_freqs: dict[str, int] = {}
        self.doc_lens: list[int] = []
        self.tokenized: list[list[str]] = []

        for doc in corpus:
            tokens = _tokenize(doc)
            self.tokenized.append(tokens)
            self.doc_lens.append(len(tokens))
            seen = set(tokens)
            for token in seen:
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        self.avgdl = sum(self.doc_lens) / max(self.corpus_size, 1)

    def score(self, query: str) -> list[float]:
        """Score all documents against query."""
        query_tokens = _tokenize(query)
        scores = [0.0] * self.corpus_size
        for query_token in query_tokens:
            df = self.doc_freqs.get(query_token, 0)
            if df == 0:
                continue
            idf = math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1.0)
            for idx, doc_tokens in enumerate(self.tokenized):
                tf = Counter(doc_tokens).get(query_token, 0)
                dl = self.doc_lens[idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[idx] += idf * numerator / denominator
        return scores


# ---------------------------------------------------------------------------
# Index persistence
# ---------------------------------------------------------------------------
_SCOPE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _normalize_scope(scope_type: str, scope_id: str) -> tuple[str, str]:
    normalized_type = str(scope_type or "").strip().lower()
    normalized_id = str(scope_id or "").strip()
    if normalized_type not in VALID_SCOPE_TYPES:
        raise ValueError(f"invalid scope_type: {scope_type!r}")
    if normalized_type == "global" and not normalized_id:
        normalized_id = "global"
    if not normalized_id or not _SCOPE_ID_RE.match(normalized_id):
        raise ValueError(f"invalid scope_id: {scope_id!r}")
    return normalized_type, normalized_id


def _scope_key(scope_type: str, scope_id: str) -> str:
    normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
    return f"{normalized_type}__{normalized_id}"


def _index_dir(index_key: str) -> str:
    if not _SCOPE_ID_RE.match(index_key.replace("__", "_")):
        raise ValueError(f"invalid index key: {index_key!r}")
    directory = os.path.join(MEMORY_BASE_DIR, index_key)
    os.makedirs(directory, exist_ok=True)
    return directory


def _load_index(index_key: str) -> tuple[list[dict[str, Any]], np.ndarray | None]:
    """Load index from disk. Returns (entries, embeddings)."""
    directory = _index_dir(index_key)
    index_file = os.path.join(directory, "index.json")
    emb_file = os.path.join(directory, "embeddings.npy")

    entries: list[dict[str, Any]] = []
    embeddings = None

    if os.path.isfile(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, list):
                entries = loaded
        except (json.JSONDecodeError, OSError):
            entries = []

    if os.path.isfile(emb_file) and entries:
        try:
            embeddings = np.load(emb_file)
            if embeddings.shape[0] != len(entries):
                log.warning("Embedding/index size mismatch for %s, rebuilding", index_key)
                embeddings = None
        except (OSError, ValueError):
            embeddings = None

    return entries, embeddings


def _save_index(index_key: str, entries: list[dict[str, Any]], embeddings: np.ndarray) -> None:
    """Save index to disk (atomic)."""
    directory = _index_dir(index_key)
    index_file = os.path.join(directory, "index.json")
    emb_file = os.path.join(directory, "embeddings.npy")

    tmp_json = index_file + ".tmp"
    tmp_npy_base = os.path.join(directory, "embeddings_tmp")
    tmp_npy_actual = tmp_npy_base + ".npy"
    try:
        np.save(tmp_npy_base, embeddings)
        with open(tmp_json, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, ensure_ascii=False)
        os.replace(tmp_npy_actual, emb_file)
        os.replace(tmp_json, index_file)
    except OSError as exc:
        log.error("Failed to save index for %s: %s", index_key, exc)
        for tmp in (tmp_json, tmp_npy_actual):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _empty_embeddings(existing: np.ndarray | None = None) -> np.ndarray:
    if existing is not None and existing.ndim == 2:
        return np.empty((0, existing.shape[1]), dtype=existing.dtype)
    return np.empty((0, EMBEDDING_DIM), dtype=float)


def _remove_document_entries(
    entries: list[dict[str, Any]],
    embeddings: np.ndarray | None,
    document_id: str,
) -> tuple[list[dict[str, Any]], np.ndarray | None, int]:
    if not document_id:
        return entries, embeddings, 0

    keep_indices = [idx for idx, entry in enumerate(entries) if entry.get("document_id") != document_id]
    deleted_chunks = len(entries) - len(keep_indices)
    if deleted_chunks == 0:
        return entries, embeddings, 0

    filtered_entries = [entries[idx] for idx in keep_indices]
    filtered_embeddings = embeddings
    if embeddings is not None and embeddings.shape[0] == len(entries):
        if keep_indices:
            filtered_embeddings = embeddings[keep_indices]
        else:
            filtered_embeddings = _empty_embeddings(embeddings)
    return filtered_entries, filtered_embeddings, deleted_chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def index_scoped_text(
    scope_type: str,
    scope_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    document_id: str = "",
    replace_document: bool = True,
) -> dict[str, Any]:
    """Index text for a canonical scope. Supports document-level upsert."""
    if not text.strip():
        return {"ok": False, "error": "empty text"}

    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    index_key = _scope_key(scope_type, scope_id)
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    if not chunks:
        return {"ok": False, "error": "no chunks produced"}

    lock = _agent_lock(index_key)
    with lock:
        entries, existing_emb = _load_index(index_key)
        deleted_chunks = 0
        if document_id and replace_document:
            entries, existing_emb, deleted_chunks = _remove_document_entries(entries, existing_emb, document_id)

        if len(entries) + len(chunks) > MAX_CHUNKS_PER_AGENT:
            return {"ok": False, "error": f"chunk limit exceeded ({MAX_CHUNKS_PER_AGENT})"}

        model = _get_model()
        new_embeddings = model.encode(chunks, show_progress_bar=False)
        if not isinstance(new_embeddings, np.ndarray):
            new_embeddings = np.array(new_embeddings)

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta = dict(metadata or {})
        meta.setdefault("scope_type", scope_type)
        meta.setdefault("scope_id", scope_id)
        if document_id:
            meta.setdefault("document_id", document_id)

        chunk_count = len(chunks)
        new_entries = []
        for chunk_index, chunk in enumerate(chunks):
            new_entries.append(
                {
                    "text": chunk,
                    "metadata": meta,
                    "indexed_at": now_iso,
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "document_id": document_id,
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                }
            )

        entries.extend(new_entries)
        if existing_emb is not None and existing_emb.shape[0] > 0:
            all_embeddings = np.vstack([existing_emb, new_embeddings])
        else:
            all_embeddings = new_embeddings

        _save_index(index_key, entries, all_embeddings)

    return {
        "ok": True,
        "chunks_added": len(chunks),
        "total_chunks": len(entries),
        "scope_type": scope_type,
        "scope_id": scope_id,
        "document_id": document_id,
        "replaced_chunks": deleted_chunks,
    }


def index_text(
    agent_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> dict[str, Any]:
    """Legacy agent indexing API. Remains append-only for compatibility."""
    return index_scoped_text(
        "agent",
        agent_id,
        text,
        metadata=metadata,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        document_id=str((metadata or {}).get("document_id", "")),
        replace_document=False,
    )


def search_scope(
    scope_type: str,
    scope_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.3,
    alpha: float = 0.7,
) -> dict[str, Any]:
    """Hybrid search: alpha * cosine_sim + (1-alpha) * BM25 score."""
    if not query.strip():
        return {"ok": False, "error": "empty query"}

    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    index_key = _scope_key(scope_type, scope_id)
    lock = _agent_lock(index_key)
    with lock:
        entries, embeddings = _load_index(index_key)

    if not entries:
        return {"ok": True, "results": [], "total_indexed": 0}

    texts = [entry["text"] for entry in entries]

    vector_scores = np.zeros(len(entries))
    if embeddings is not None and embeddings.shape[0] == len(entries):
        model = _get_model()
        query_emb = model.encode([query], show_progress_bar=False)
        if not isinstance(query_emb, np.ndarray):
            query_emb = np.array(query_emb)
        norms_db = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms_db = np.where(norms_db == 0, 1, norms_db)
        norm_q = np.linalg.norm(query_emb)
        if norm_q > 0:
            vector_scores = (embeddings @ query_emb.T).flatten() / (norms_db.flatten() * norm_q)

    bm25 = SimpleBM25(texts)
    bm25_scores = np.array(bm25.score(query))
    bm25_max = bm25_scores.max() if len(bm25_scores) > 0 else 1.0
    if bm25_max > 0:
        bm25_scores = bm25_scores / bm25_max

    hybrid_scores = alpha * vector_scores + (1 - alpha) * bm25_scores
    ranked_indices = np.argsort(-hybrid_scores)
    results = []
    for idx in ranked_indices[:top_k]:
        score = float(hybrid_scores[idx])
        if score < min_score:
            continue
        entry = entries[idx]
        results.append(
            {
                "text": entry["text"],
                "metadata": entry.get("metadata", {}),
                "scope_type": entry.get("scope_type", scope_type),
                "scope_id": entry.get("scope_id", scope_id),
                "document_id": entry.get("document_id", ""),
                "score": round(score, 4),
                "vector_score": round(float(vector_scores[idx]), 4),
                "bm25_score": round(float(bm25_scores[idx]), 4),
                "indexed_at": entry.get("indexed_at", ""),
            }
        )

    return {"ok": True, "results": results, "total_indexed": len(entries)}


def search(
    agent_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.3,
    alpha: float = 0.7,
) -> dict[str, Any]:
    """Legacy agent search API."""
    return search_scope("agent", agent_id, query, top_k=top_k, min_score=min_score, alpha=alpha)


def delete_document(scope_type: str, scope_id: str, document_id: str) -> dict[str, Any]:
    """Delete all indexed chunks for a document inside a scope."""
    if not document_id:
        return {"ok": False, "error": "empty document_id"}

    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    index_key = _scope_key(scope_type, scope_id)
    lock = _agent_lock(index_key)
    with lock:
        entries, embeddings = _load_index(index_key)
        entries, embeddings, deleted_chunks = _remove_document_entries(entries, embeddings, document_id)
        if deleted_chunks == 0:
            return {
                "ok": True,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "document_id": document_id,
                "deleted_chunks": 0,
                "total_chunks": len(entries),
            }

        _save_index(index_key, entries, embeddings if embeddings is not None else _empty_embeddings())

    return {
        "ok": True,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "document_id": document_id,
        "deleted_chunks": deleted_chunks,
        "total_chunks": len(entries),
    }


def get_scope_stats(scope_type: str, scope_id: str) -> dict[str, Any]:
    """Get index statistics for a scope."""
    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    index_key = _scope_key(scope_type, scope_id)
    lock = _agent_lock(index_key)
    with lock:
        entries, embeddings = _load_index(index_key)

    directory = _index_dir(index_key)
    index_file = os.path.join(directory, "index.json")
    emb_file = os.path.join(directory, "embeddings.npy")

    index_size = os.path.getsize(index_file) if os.path.isfile(index_file) else 0
    emb_size = os.path.getsize(emb_file) if os.path.isfile(emb_file) else 0
    last_update = max((entry.get("indexed_at", "") for entry in entries), default="")
    document_ids = {entry.get("document_id", "") for entry in entries if entry.get("document_id")}

    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "total_chunks": len(entries),
        "total_documents": len(document_ids),
        "max_chunks": MAX_CHUNKS_PER_AGENT,
        "has_embeddings": embeddings is not None and embeddings.shape[0] == len(entries),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dim": EMBEDDING_DIM,
        "index_size_bytes": index_size,
        "embeddings_size_bytes": emb_size,
        "last_update": last_update,
    }


def get_stats(agent_id: str) -> dict[str, Any]:
    """Legacy agent stats API."""
    return get_scope_stats("agent", agent_id)
