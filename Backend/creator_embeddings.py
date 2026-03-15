"""Creator Embeddings — Gemini Embedding 2 Multimodal Video Search.

Embeds video chunks using Google's Gemini Embedding 2 model.
Stores embeddings in ChromaDB for semantic search.

BYOK: User provides GOOGLE_API_KEY.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import shutil
from typing import Any

logger = logging.getLogger(__name__)

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
EMBEDDING_MODEL = "gemini-embedding-2-preview"
MAX_CHUNK_DURATION_S = 120
DEFAULT_COLLECTION = "creator_video_embeddings"


def _get_google_api_key() -> str:
    """Get Google API key from env or config."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    # Check Bridge config
    for path in [
        os.path.join(os.environ.get("HOME", "/tmp"), ".config", "bridge", "google_api_key"),
        os.path.join(os.environ.get("HOME", "/tmp"), ".config", "bridge", "social_credentials", "google.json"),
    ]:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    content = f.read().strip()
                if content.startswith("{"):
                    data = json.loads(content)
                    return data.get("api_key", "")
                return content
            except (json.JSONDecodeError, OSError):
                continue
    return ""


# ---------------------------------------------------------------------------
# Video Chunking for Embedding
# ---------------------------------------------------------------------------


def _chunk_video(video_path: str, chunk_duration_s: int = 120) -> list[dict[str, Any]]:
    """Split video into chunks of max chunk_duration_s seconds.

    Returns list of {chunk_index, start_s, end_s, chunk_path}.
    """
    # Get duration
    cmd = [
        FFMPEG_BIN.replace("ffmpeg", "ffprobe"),
        "-v", "quiet", "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    duration = 0.0
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
        except (json.JSONDecodeError, ValueError):
            pass

    if duration <= 0:
        return [{"chunk_index": 0, "start_s": 0.0, "end_s": 0.0, "chunk_path": video_path}]

    tmpdir = tempfile.mkdtemp(prefix="creator_embed_chunks_")
    chunks: list[dict[str, Any]] = []
    pos = 0.0
    idx = 0

    while pos < duration:
        end = min(pos + chunk_duration_s, duration)
        chunk_path = os.path.join(tmpdir, f"chunk_{idx:04d}.mp4")

        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(pos), "-to", str(end),
            "-i", video_path,
            "-c", "copy",
            chunk_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if os.path.isfile(chunk_path) and os.path.getsize(chunk_path) > 0:
            chunks.append({
                "chunk_index": idx,
                "start_s": pos,
                "end_s": end,
                "chunk_path": chunk_path,
            })

        pos = end
        idx += 1

    return chunks


# ---------------------------------------------------------------------------
# Embedding via Gemini API
# ---------------------------------------------------------------------------


def _embed_video_chunk(api_key: str, chunk_path: str) -> list[float]:
    """Embed a single video chunk via Gemini Embedding 2 API."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # Upload video file
    video_file = client.files.upload(file=chunk_path)

    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[types.Part.from_uri(file_uri=video_file.uri, mime_type="video/mp4")],
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=768,  # Balanced quality/storage
        ),
    )

    # Clean up uploaded file
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    if result.embeddings and len(result.embeddings) > 0:
        return list(result.embeddings[0].values)
    raise RuntimeError("No embedding returned from Gemini API")


def _embed_text_query(api_key: str, query: str) -> list[float]:
    """Embed a text query via Gemini Embedding 2 API."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )

    if result.embeddings and len(result.embeddings) > 0:
        return list(result.embeddings[0].values)
    raise RuntimeError("No embedding returned")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_video(
    video_path: str,
    chunk_duration_s: int = 120,
) -> dict[str, Any]:
    """Embed a video by chunking and embedding each chunk.

    Returns: {video_path, embeddings: [{chunk_index, start_s, end_s, vector}], chunk_count}
    """
    api_key = _get_google_api_key()
    if not api_key:
        raise RuntimeError("No GOOGLE_API_KEY. Set env var or store in ~/.config/bridge/google_api_key")

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    chunks = _chunk_video(video_path, chunk_duration_s)
    embeddings: list[dict[str, Any]] = []

    for chunk in chunks:
        try:
            vector = _embed_video_chunk(api_key, chunk["chunk_path"])
            embeddings.append({
                "chunk_index": chunk["chunk_index"],
                "start_s": chunk["start_s"],
                "end_s": chunk["end_s"],
                "vector": vector,
            })
        except Exception as exc:
            logger.warning("Failed to embed chunk %d: %s", chunk["chunk_index"], exc)
            embeddings.append({
                "chunk_index": chunk["chunk_index"],
                "start_s": chunk["start_s"],
                "end_s": chunk["end_s"],
                "error": str(exc),
            })

    # Cleanup temp chunks
    if chunks and chunks[0].get("chunk_path", "").startswith(tempfile.gettempdir()):
        chunk_dir = os.path.dirname(chunks[0]["chunk_path"])
        shutil.rmtree(chunk_dir, ignore_errors=True)

    return {
        "video_path": video_path,
        "embeddings": embeddings,
        "chunk_count": len(chunks),
        "embedded_count": sum(1 for e in embeddings if "vector" in e),
    }


def embed_text(query: str) -> list[float]:
    """Embed a text query for search."""
    api_key = _get_google_api_key()
    if not api_key:
        raise RuntimeError("No GOOGLE_API_KEY")
    return _embed_text_query(api_key, query)


def store_embeddings(
    collection_name: str,
    embeddings: list[dict[str, Any]],
    video_path: str,
) -> int:
    """Store video embeddings in ChromaDB.

    Returns number of embeddings stored.
    """
    import chromadb

    client = chromadb.Client()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    ids = []
    vectors = []
    metadatas = []

    for emb in embeddings:
        if "vector" not in emb:
            continue
        chunk_id = f"{os.path.basename(video_path)}__chunk_{emb['chunk_index']}"
        ids.append(chunk_id)
        vectors.append(emb["vector"])
        metadatas.append({
            "video_path": video_path,
            "chunk_index": emb["chunk_index"],
            "start_s": emb["start_s"],
            "end_s": emb["end_s"],
        })

    if ids:
        collection.upsert(ids=ids, embeddings=vectors, metadatas=metadatas)

    return len(ids)


def search(
    collection_name: str,
    query_text: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Search embedded videos by text query.

    Returns list of {video_path, start_s, end_s, score, chunk_index}.
    """
    import chromadb

    api_key = _get_google_api_key()
    if not api_key:
        raise RuntimeError("No GOOGLE_API_KEY for search embedding")

    query_vector = _embed_text_query(api_key, query_text)

    client = chromadb.Client()
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        return []

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k,
    )

    hits: list[dict[str, Any]] = []
    if results and results.get("metadatas"):
        for i, meta in enumerate(results["metadatas"][0]):
            score = 1.0 - results["distances"][0][i] if results.get("distances") else 0.0
            hits.append({
                "video_path": meta.get("video_path", ""),
                "start_s": meta.get("start_s", 0),
                "end_s": meta.get("end_s", 0),
                "chunk_index": meta.get("chunk_index", 0),
                "score": round(score, 4),
            })

    return hits


def list_embedded_videos(collection_name: str = DEFAULT_COLLECTION) -> list[dict[str, Any]]:
    """List all embedded videos in a collection."""
    import chromadb

    client = chromadb.Client()
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        return []

    all_items = collection.get(include=["metadatas"])
    videos: dict[str, dict[str, Any]] = {}

    for meta in all_items.get("metadatas", []):
        vp = meta.get("video_path", "")
        if vp not in videos:
            videos[vp] = {"video_path": vp, "chunks": 0, "total_duration_s": 0}
        videos[vp]["chunks"] += 1
        end = meta.get("end_s", 0)
        if end > videos[vp]["total_duration_s"]:
            videos[vp]["total_duration_s"] = end

    return list(videos.values())
