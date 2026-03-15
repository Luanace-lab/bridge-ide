"""Creator Job Stage Functions — Wire job stages to creator_media.

Each stage function takes a job dict and returns an artifacts dict.
Stage functions are registered with creator_job.register_stages().
"""

from __future__ import annotations

import os
from typing import Any


def register_voiceover_stages() -> None:
    """Register stage functions for voiceover and voice_clone job types."""
    import creator_job

    creator_job.register_stages(
        "voiceover",
        [
            ("voiceover_resolve", _stage_voiceover_resolve),
            ("voiceover_generate", _stage_voiceover_generate),
            ("voiceover_merge", _stage_voiceover_merge),
        ],
    )

    creator_job.register_stages(
        "voice_clone",
        [
            ("clone_resolve", _stage_clone_resolve),
            ("clone_upload", _stage_clone_upload),
        ],
    )


def register_embed_stages() -> None:
    """Register stage functions for embed_content job type."""
    import creator_job

    creator_job.register_stages(
        "embed_content",
        [
            ("embed_resolve", _stage_embed_resolve),
            ("embed_chunks", _stage_embed_chunks),
            ("embed_store", _stage_embed_store),
        ],
    )


def register_render_stages() -> None:
    """Register stage functions for clip_export job type (template rendering)."""
    import creator_job

    creator_job.register_stages(
        "clip_export",
        [
            ("render_resolve", _stage_render_resolve),
            ("render_execute", _stage_render_execute),
        ],
    )


def register_publish_stages() -> None:
    """Register stage functions for publish job type."""
    import creator_job

    creator_job.register_stages(
        "publish",
        [
            ("publish_resolve", _stage_publish_resolve),
            ("publish_execute", _stage_publish_execute),
        ],
    )


def register_analysis_stages() -> None:
    """Register stage functions for analyze_content job type."""
    import creator_job

    creator_job.register_stages(
        "analyze_content",
        [
            ("analysis_execute", _stage_analysis_execute),
        ],
    )


def register_ingest_stages() -> None:
    """Register stage functions for local_ingest and url_ingest job types."""
    import creator_job

    creator_job.register_stages(
        "local_ingest",
        _build_ingest_stages(local=True),
    )

    creator_job.register_stages(
        "url_ingest",
        _build_ingest_stages(local=False),
    )

    creator_job.register_stages(
        "transcribe",
        [
            ("source_resolve", _stage_source_resolve_local),
            ("transcript_plan", _stage_transcript_plan),
            ("transcript_chunks", _stage_transcript_chunks),
            ("transcript_merge", _stage_transcript_merge),
        ],
    )


def _build_ingest_stages(local: bool = True) -> list[tuple[str, Any]]:
    """Build the stage list for ingest jobs, conditionally including STT."""
    # Base stages
    if local:
        stages: list[tuple[str, Any]] = [
            ("source_resolve", _stage_source_resolve_local),
            ("probe", _stage_probe),
            ("audio_extract", _stage_audio_extract),
        ]
    else:
        stages = [
            ("source_resolve", _stage_source_resolve_url),
            ("download", _stage_download),
            ("probe", _stage_probe),
            ("audio_extract", _stage_audio_extract),
        ]

    # STT stages — added dynamically based on job config at registration
    # We add them always; the stage functions check config.transcribe
    stages.extend([
        ("transcript_plan", _stage_transcript_plan_conditional),
        ("transcript_chunks", _stage_transcript_chunks_conditional),
        ("transcript_merge", _stage_transcript_merge_conditional),
        ("chapters", _stage_chapters_conditional),
        ("highlights", _stage_highlights_conditional),
    ])

    return stages


# ---------------------------------------------------------------------------
# Stage: source_resolve (local)
# ---------------------------------------------------------------------------


def _stage_source_resolve_local(job: dict[str, Any]) -> dict[str, Any]:
    """Validate that the local input file exists."""
    input_path = job["source"].get("input_path", "")
    if not input_path:
        raise ValueError("source.input_path is required")
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    return {"input_path": input_path, "exists": True}


# ---------------------------------------------------------------------------
# Stage: source_resolve (url)
# ---------------------------------------------------------------------------


def _stage_source_resolve_url(job: dict[str, Any]) -> dict[str, Any]:
    """Validate and classify the source URL."""
    import creator_media

    source_url = job["source"].get("source_url", "")
    if not source_url:
        raise ValueError("source.source_url is required")
    source_type = creator_media._detect_creator_source_type(source_url)
    return {"source_url": source_url, "source_type": source_type}


# ---------------------------------------------------------------------------
# Stage: download
# ---------------------------------------------------------------------------


def _stage_download(job: dict[str, Any]) -> dict[str, Any]:
    """Download media from URL."""
    import creator_media

    source_url = job["source"].get("source_url", "")
    source_type = job.get("artifacts", {}).get("source_resolve", {}).get("source_type", "url")

    download_dir = os.path.join(job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts")
    os.makedirs(download_dir, exist_ok=True)

    if source_type == "youtube":
        result = creator_media._download_youtube_source(source_url, download_dir)
    else:
        result = creator_media._download_direct_source(source_url, download_dir)

    # Store the local path in source for downstream stages
    job["source"]["local_path"] = result.get("local_path", "")
    return result


# ---------------------------------------------------------------------------
# Stage: probe
# ---------------------------------------------------------------------------


def _stage_probe(job: dict[str, Any]) -> dict[str, Any]:
    """Probe media metadata via ffprobe."""
    import creator_media

    # Determine input path: from download stage or source
    input_path = job["source"].get("local_path") or job["source"].get("input_path", "")
    if not input_path or not os.path.isfile(input_path):
        raise FileNotFoundError(f"Media file not found for probe: {input_path}")

    result = creator_media.probe_media(input_path)
    return result


# ---------------------------------------------------------------------------
# Stage: audio_extract
# ---------------------------------------------------------------------------


def _stage_audio_extract(job: dict[str, Any]) -> dict[str, Any]:
    """Extract audio for transcription."""
    import creator_media

    input_path = job["source"].get("local_path") or job["source"].get("input_path", "")
    if not input_path:
        raise ValueError("No input path available for audio extraction")

    job_artifacts_dir = os.path.join(
        job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts"
    )
    os.makedirs(job_artifacts_dir, exist_ok=True)
    audio_output = os.path.join(job_artifacts_dir, "audio.wav")

    result = creator_media.extract_audio_for_transcription(input_path, audio_output)
    return result


# ---------------------------------------------------------------------------
# Conditional wrappers — skip STT stages if transcribe=False
# ---------------------------------------------------------------------------

_SKIP_RESULT = {"skipped": True, "reason": "transcribe=False"}


def _should_transcribe(job: dict[str, Any]) -> bool:
    """Check if this job should run transcription stages."""
    return bool(job.get("config", {}).get("transcribe", True))


def _stage_transcript_plan_conditional(job: dict[str, Any]) -> dict[str, Any]:
    if not _should_transcribe(job):
        return _SKIP_RESULT
    return _stage_transcript_plan(job)


def _stage_transcript_chunks_conditional(job: dict[str, Any]) -> dict[str, Any]:
    if not _should_transcribe(job):
        return _SKIP_RESULT
    return _stage_transcript_chunks(job)


def _stage_transcript_merge_conditional(job: dict[str, Any]) -> dict[str, Any]:
    if not _should_transcribe(job):
        return _SKIP_RESULT
    return _stage_transcript_merge(job)


def _stage_chapters_conditional(job: dict[str, Any]) -> dict[str, Any]:
    if not _should_transcribe(job):
        return _SKIP_RESULT
    return _stage_chapters(job)


def _stage_highlights_conditional(job: dict[str, Any]) -> dict[str, Any]:
    if not _should_transcribe(job):
        return _SKIP_RESULT
    return _stage_highlights(job)


# ---------------------------------------------------------------------------
# Stage: transcript_plan
# ---------------------------------------------------------------------------


def _stage_transcript_plan(job: dict[str, Any]) -> dict[str, Any]:
    """Plan audio chunks for transcription."""
    from voice_stt import plan_chunks

    audio_path = _get_audio_path(job)
    config = job.get("config", {})
    chunk_duration_s = int(config.get("chunk_duration_s", 300))
    overlap_s = float(config.get("overlap_s", 1.0))

    chunks = plan_chunks(audio_path, chunk_duration_s=chunk_duration_s, overlap_s=overlap_s)
    return {"chunks": chunks, "chunk_count": len(chunks), "audio_path": audio_path}


# ---------------------------------------------------------------------------
# Stage: transcript_chunks
# ---------------------------------------------------------------------------


def _stage_transcript_chunks(job: dict[str, Any]) -> dict[str, Any]:
    """Transcribe each chunk. Saves results to chunks/ directory.

    Supports resume: skips chunks that already have result files.
    """
    from voice_stt import (
        _extract_chunk_audio,
        _get_faster_whisper_model,
        transcribe_chunk,
    )

    config = job.get("config", {})
    language = config.get("language", "de")
    model_size = config.get("model_size", "tiny")

    # Get chunk plan from previous stage
    plan = job.get("artifacts", {}).get("transcript_plan", {})
    chunks = plan.get("chunks", [])
    audio_path = plan.get("audio_path", _get_audio_path(job))

    if not chunks:
        raise ValueError("No chunk plan found — run transcript_plan first")

    model = _get_faster_whisper_model(model_size)

    chunks_dir = os.path.join(
        job["workspace_dir"], "creator_jobs", job["job_id"], "chunks"
    )
    os.makedirs(chunks_dir, exist_ok=True)

    completed_chunks: list[dict[str, Any]] = []
    failed_chunks: list[dict[str, Any]] = []

    import json
    import tempfile
    import shutil

    for chunk in chunks:
        idx = chunk["chunk_index"]
        result_path = os.path.join(chunks_dir, f"chunk_{idx:04d}.json")

        # Resume: skip already completed chunks
        if os.path.isfile(result_path):
            try:
                with open(result_path) as f:
                    existing = json.load(f)
                if existing.get("status") == "completed":
                    completed_chunks.append(existing)
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        # Extract chunk audio
        tmp_dir = tempfile.mkdtemp(prefix=f"chunk_{idx}_")
        try:
            chunk_wav = os.path.join(tmp_dir, f"chunk_{idx:04d}.wav")
            if chunk.get("end_s", 0) > 0:
                _extract_chunk_audio(audio_path, chunk["start_s"], chunk["end_s"], chunk_wav)
            else:
                # Single chunk = copy/convert whole file
                from voice_stt import _convert_to_wav
                _convert_to_wav(audio_path, tmp_dir)
                chunk_wav = os.path.join(tmp_dir, "audio.wav")

            # Transcribe
            result = transcribe_chunk(chunk_wav, model, language)
            result["chunk_index"] = idx
            result["start_offset_s"] = chunk["start_s"]
            result["status"] = "completed"
            completed_chunks.append(result)

            # Persist chunk result
            with open(result_path, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

        except Exception as exc:
            error_result = {
                "chunk_index": idx,
                "status": "failed",
                "error": str(exc),
            }
            failed_chunks.append(error_result)
            with open(result_path, "w") as f:
                json.dump(error_result, f, ensure_ascii=False, indent=2)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if failed_chunks and not completed_chunks:
        raise RuntimeError(
            f"All {len(failed_chunks)} chunks failed. "
            f"First error: {failed_chunks[0].get('error', 'unknown')}"
        )

    return {
        "completed_count": len(completed_chunks),
        "failed_count": len(failed_chunks),
        "total_count": len(chunks),
        "failed_chunks": [c["chunk_index"] for c in failed_chunks],
    }


# ---------------------------------------------------------------------------
# Stage: transcript_merge
# ---------------------------------------------------------------------------


def _stage_transcript_merge(job: dict[str, Any]) -> dict[str, Any]:
    """Merge chunk results into unified transcript."""
    from voice_stt import merge_chunk_results
    import json

    config = job.get("config", {})
    overlap_s = float(config.get("overlap_s", 1.0))

    chunks_dir = os.path.join(
        job["workspace_dir"], "creator_jobs", job["job_id"], "chunks"
    )

    chunk_results: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(chunks_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(chunks_dir, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            if data.get("status") == "completed":
                chunk_results.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    if not chunk_results:
        raise ValueError("No completed chunk results found for merge")

    merged = merge_chunk_results(chunk_results, overlap_s=overlap_s)
    return merged


# ---------------------------------------------------------------------------
# Stage: chapters
# ---------------------------------------------------------------------------


def _stage_chapters(job: dict[str, Any]) -> dict[str, Any]:
    """Group transcript segments into chapters."""
    import creator_media

    merge_result = job.get("artifacts", {}).get("transcript_merge", {})
    segments = merge_result.get("segments", [])
    if not segments:
        return {"chapters": [], "skipped": True, "reason": "no segments"}

    chapters = creator_media.group_segments_into_chapters(segments)
    return {"chapters": chapters, "chapter_count": len(chapters)}


# ---------------------------------------------------------------------------
# Stage: highlights
# ---------------------------------------------------------------------------


def _stage_highlights(job: dict[str, Any]) -> dict[str, Any]:
    """Pick highlight candidates from transcript segments."""
    import creator_media

    merge_result = job.get("artifacts", {}).get("transcript_merge", {})
    segments = merge_result.get("segments", [])
    if not segments:
        return {"highlights": [], "skipped": True, "reason": "no segments"}

    highlights = creator_media.pick_highlight_candidates(segments)
    return {"highlights": highlights, "highlight_count": len(highlights)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stage: analysis_execute (agent-based clip analysis with fallback)
# ---------------------------------------------------------------------------


def _stage_analysis_execute(job: dict[str, Any]) -> dict[str, Any]:
    """Run content analysis on transcript — with optional vision (frame analysis).

    Modes:
    - 'vision_api': Extract frames + send frames+transcript to Vision API (BYOK)
    - 'text': Send only transcript to agent (existing behavior)
    - default: auto-detect (vision_api if API key available, else text)

    Falls back to heuristic highlight selection if all analysis methods fail.
    """
    import creator_media

    transcript = job.get("artifacts", {}).get("transcript_merge", {})
    segments = transcript.get("segments", [])
    text = transcript.get("text", "")

    if not segments and not text:
        return {"clips": [], "error": "No transcript available", "fallback": True}

    config = job.get("config", {})
    target_platforms = config.get("target_platforms", ["youtube_short"])
    analysis_mode = config.get("analysis_mode", "auto")

    # Auto-detect mode
    if analysis_mode == "auto":
        analysis_mode = "vision_api" if _has_vision_api_key() else "text"

    # Mode 1: Vision API (frames + transcript)
    if analysis_mode == "vision_api":
        try:
            video_path = job.get("source", {}).get("input_path", "")
            local_path = job.get("source", {}).get("local_path", "")
            video = local_path or video_path

            frames = []
            if video and os.path.isfile(video):
                frame_dir = os.path.join(
                    job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts", "frames"
                )
                os.makedirs(frame_dir, exist_ok=True)
                frames = creator_media.extract_keyframes(
                    video, interval_s=2.0, max_frames=15, output_dir=frame_dir,
                )

            result = _call_vision_api(text, segments, target_platforms, frames)
            if isinstance(result, dict) and "clips" in result and isinstance(result["clips"], list):
                return {"clips": result["clips"], "fallback": False, "source": "vision", "frames_used": len(frames)}
        except Exception:
            pass  # Fall through to text mode

    # Mode 2: Text-only agent analysis
    if analysis_mode in ("text", "vision_api"):  # vision_api falls through here on failure
        try:
            result = _request_agent_analysis(text, segments, target_platforms, job)
            if isinstance(result, dict) and "clips" in result and isinstance(result["clips"], list):
                return {"clips": result["clips"], "fallback": False, "source": "agent"}
        except Exception:
            pass

    # Fallback: heuristic
    highlights = creator_media.pick_highlight_candidates(segments, max_candidates=5)
    clips = []
    for h in highlights:
        clips.append({
            "start_s": h["start"],
            "end_s": h["end"],
            "title": h["text"][:60],
            "reason": "Heuristic: word_count + duration score",
            "caption": "",
            "hashtags": [],
            "engagement_score": round(h.get("score", 0) / max(h.get("score", 1), 1), 2),
            "platforms": target_platforms,
        })
    return {"clips": clips, "fallback": True, "source": "heuristic"}


def _request_agent_analysis(
    text: str,
    segments: list[dict[str, Any]],
    target_platforms: list[str],
    job: dict[str, Any],
) -> dict[str, Any]:
    """Request content analysis from a Bridge agent via task system.

    Creates a task via HTTP POST to /task/create, polls for completion.
    Returns the agent's structured result.

    Raises on failure (caller handles fallback).
    """
    import json
    import time

    try:
        from common import http_post_json, http_get_json, build_bridge_auth_headers
    except ImportError:
        raise ConnectionError("Bridge common module not available")

    headers = build_bridge_auth_headers(agent_id="creator_pipeline")
    server_url = "http://127.0.0.1:9111"

    prompt = _build_analysis_prompt(text, segments, target_platforms)

    # Create task
    task_payload = {
        "type": "research",
        "title": f"Creator Clip-Analyse: {job.get('job_id', 'unknown')}",
        "description": prompt,
        "priority": "high",
        "labels": ["creator", "analysis"],
    }

    resp = http_post_json(f"{server_url}/task/create", task_payload, timeout=10, headers=headers)
    task_id = resp.get("task_id") or resp.get("id")
    if not task_id:
        raise RuntimeError(f"Task creation returned no task_id: {resp}")

    # Poll for completion (max 300s)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(5)
        try:
            task = http_get_json(f"{server_url}/task/{task_id}", timeout=10, headers=headers)
            status = task.get("status") or task.get("state", "")
            if status in ("done", "completed"):
                result_text = task.get("result", "") or task.get("output", "")
                if isinstance(result_text, str):
                    return json.loads(result_text)
                if isinstance(result_text, dict):
                    return result_text
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"Agent task {task_id} {status}")
        except (json.JSONDecodeError, KeyError):
            continue

    raise TimeoutError(f"Agent task {task_id} timed out after 300s")


def _has_vision_api_key() -> bool:
    """Check if an Anthropic API key is available for vision analysis."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return True
    # Check Bridge config
    config_path = os.path.join(
        os.environ.get("HOME", "/tmp"), ".config", "bridge", "anthropic_api_key"
    )
    return os.path.isfile(config_path)


def _get_vision_api_key() -> str:
    """Get the Anthropic API key."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    config_path = os.path.join(
        os.environ.get("HOME", "/tmp"), ".config", "bridge", "anthropic_api_key"
    )
    if os.path.isfile(config_path):
        with open(config_path) as f:
            return f.read().strip()
    raise RuntimeError("No ANTHROPIC_API_KEY found")


def _call_vision_api(
    text: str,
    segments: list[dict[str, Any]],
    target_platforms: list[str],
    frame_paths: list[str],
) -> dict[str, Any]:
    """Call Claude Vision API with frames + transcript for multimodal analysis.

    Sends keyframes as base64-encoded images alongside the transcript.
    Returns structured clip analysis.
    """
    import base64
    import json

    try:
        import httpx
    except ImportError:
        import requests as httpx  # type: ignore[no-redef]

    api_key = _get_vision_api_key()
    if not api_key:
        raise RuntimeError("No API key for vision analysis")

    # Build content blocks: images + text prompt
    content_blocks: list[dict[str, Any]] = []

    # Add frames (max 10 to control costs)
    for frame_path in frame_paths[:10]:
        if not os.path.isfile(frame_path):
            continue
        with open(frame_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_data,
            },
        })

    # Add text prompt
    segments_json = json.dumps(segments[:100], ensure_ascii=False, indent=1)
    platforms = ", ".join(target_platforms)

    prompt = f"""Analysiere die Video-Frames UND das Transkript. Identifiziere die besten Clip-Kandidaten.

TRANSKRIPT:
{text[:5000]}

SEGMENTE (mit Timestamps):
{segments_json}

ZIELPLATTFORMEN: {platforms}

Du siehst {len(content_blocks) - 1} Frames aus dem Video (gleichmaessig verteilt).

AUFGABE:
1. Identifiziere die 3-5 besten Clip-Kandidaten (15-60 Sekunden)
2. Nutze SOWOHL visuelle Cues (Gestik, Produkt-Nahaufnahmen, Szenenwechsel, Emotionen) ALS AUCH den Text
3. Begruende jede Auswahl mit visuellen UND inhaltlichen Argumenten
4. Generiere pro Clip: Caption, Hashtags fuer jede Zielplattform
5. Bewerte Engagement-Potenzial (0.0-1.0) basierend auf Hook-Staerke und visuellem Appeal

AUSGABEFORMAT (NUR JSON, keine Erklaerung):
{{
  "clips": [
    {{
      "start_s": 20.0,
      "end_s": 42.0,
      "title": "Kurzer Clip-Titel",
      "reason": "Visuelle + inhaltliche Begruendung",
      "caption": "Caption fuer Social Media",
      "hashtags": ["#tag1", "#tag2"],
      "engagement_score": 0.85,
      "platforms": ["youtube_short", "instagram_reel"]
    }}
  ]
}}"""

    content_blocks.append({"type": "text", "text": prompt})

    # Call Claude Vision API
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content_blocks}],
        },
        timeout=120,
    )

    resp_data = response.json() if hasattr(response, 'json') and callable(response.json) else json.loads(response.text)

    # Extract text content from response
    resp_text = ""
    for block in resp_data.get("content", []):
        if block.get("type") == "text":
            resp_text += block.get("text", "")

    # Parse JSON from response
    # Try to find JSON in the response text
    resp_text = resp_text.strip()
    if resp_text.startswith("```"):
        # Strip markdown code block
        lines = resp_text.split("\n")
        resp_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return json.loads(resp_text)


def _build_analysis_prompt(
    text: str,
    segments: list[dict[str, Any]],
    target_platforms: list[str],
) -> str:
    """Build the prompt for agent-based clip analysis."""
    import json

    segments_json = json.dumps(segments[:100], ensure_ascii=False, indent=1)
    platforms = ", ".join(target_platforms)

    return f"""Analysiere das folgende Transkript und identifiziere die besten Clip-Kandidaten.

TRANSKRIPT:
{text[:5000]}

SEGMENTE (mit Timestamps):
{segments_json}

ZIELPLATTFORMEN: {platforms}

AUFGABE:
1. Identifiziere die 3-5 besten Clip-Kandidaten (15-60 Sekunden)
2. Begruende jede Auswahl (Hook-Qualitaet, Ueberraschungsmoment, Standalone-Verstaendlichkeit)
3. Generiere pro Clip: Caption, Hashtags, CTA fuer jede Zielplattform
4. Bewerte Engagement-Potenzial (0.0-1.0)

AUSGABEFORMAT (JSON):
{{
  "clips": [
    {{
      "start_s": 20.0,
      "end_s": 42.0,
      "title": "Kurzer Clip-Titel",
      "reason": "Begruendung",
      "caption": "Caption fuer Social Media",
      "hashtags": ["#tag1", "#tag2"],
      "engagement_score": 0.85,
      "platforms": ["youtube_short", "instagram_reel"]
    }}
  ]
}}

Antworte NUR mit dem JSON. Keine Erklaerung ausserhalb des JSON."""


# ---------------------------------------------------------------------------
# Stage: render_resolve + render_execute
# ---------------------------------------------------------------------------


def _stage_render_resolve(job: dict[str, Any]) -> dict[str, Any]:
    """Validate render inputs."""
    input_path = job.get("source", {}).get("input_path", "")
    if not input_path or not os.path.isfile(input_path):
        raise FileNotFoundError(f"Video not found: {input_path}")
    config = job.get("config", {})
    template = config.get("template", "simple_clip")
    return {"input_path": input_path, "template": template}


def _stage_render_execute(job: dict[str, Any]) -> dict[str, Any]:
    """Render video using template."""
    from creator_video_edit import render_from_template

    config = job.get("config", {})
    resolve = job.get("artifacts", {}).get("render_resolve", {})
    input_path = resolve.get("input_path", job.get("source", {}).get("input_path", ""))
    template = config.get("template", "simple_clip")
    start_s = float(config.get("start_s", 0))
    end_s = float(config.get("end_s", 0))
    params = config.get("params", {})

    output_dir = os.path.join(
        job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts"
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"rendered_{template}.mp4")

    result = render_from_template(template, input_path, output_path, start_s, end_s, params)
    return result


# ---------------------------------------------------------------------------
# Stage: publish_resolve
# ---------------------------------------------------------------------------


def _stage_publish_resolve(job: dict[str, Any]) -> dict[str, Any]:
    """Validate that the source clip exists."""
    clip_path = job.get("source", {}).get("clip_path", "")
    source_job_id = job.get("source", {}).get("source_job_id", "")

    if clip_path and os.path.isfile(clip_path):
        return {"clip_path": clip_path, "source_job_id": source_job_id}

    # Try to resolve from source job
    if source_job_id:
        import creator_job

        source_job = creator_job.load_job(source_job_id, job["workspace_dir"])
        if source_job:
            # Look for clip in artifacts
            for key in ("clip_export", "social_export", "package_social"):
                artifact = source_job.get("artifacts", {}).get(key, {})
                path = artifact.get("output_path", "")
                if path and os.path.isfile(path):
                    return {"clip_path": path, "source_job_id": source_job_id}

    return {"clip_path": clip_path or "", "source_job_id": source_job_id, "warning": "clip not found on disk"}


# ---------------------------------------------------------------------------
# Stage: publish_execute
# ---------------------------------------------------------------------------


def _stage_publish_execute(job: dict[str, Any]) -> dict[str, Any]:
    """Execute multi-channel publishing."""
    from creator_publisher import publish_multi_channel

    config = job.get("config", {})
    channels = config.get("channels", [])

    if not channels:
        raise ValueError("No channels configured")

    resolve = job.get("artifacts", {}).get("publish_resolve", {})
    media_path = resolve.get("clip_path", "")

    results = publish_multi_channel(channels, media_path=media_path)

    sent = sum(1 for r in results if r.get("status") in ("sent", "scheduled", "pending_approval"))
    failed = sum(1 for r in results if r.get("status") == "error")
    if not results:
        raise RuntimeError("Publishing returned no channel results")
    if failed == len(results):
        errors = [
            r.get("error", "unknown publish error")
            for r in results
            if r.get("status") == "error"
        ]
        raise RuntimeError("All publish channels failed: " + "; ".join(errors[:3]))

    return {
        "results": results,
        "sent_count": sent,
        "failed_count": failed,
        "total_count": len(results),
    }


# ---------------------------------------------------------------------------
# Stage: voiceover
# ---------------------------------------------------------------------------


def _stage_voiceover_resolve(job: dict[str, Any]) -> dict[str, Any]:
    config = job.get("config", {})
    text = config.get("text", "")
    voice_id = config.get("voice_id", "")
    video_path = job.get("source", {}).get("video_path", "")
    if not text:
        raise ValueError("config.text is required for voiceover")
    if not voice_id:
        raise ValueError("config.voice_id is required for voiceover")
    return {"text": text, "voice_id": voice_id, "video_path": video_path}


def _stage_voiceover_generate(job: dict[str, Any]) -> dict[str, Any]:
    from creator_fish_audio import generate_voiceover

    resolve = job.get("artifacts", {}).get("voiceover_resolve", {})
    text = resolve.get("text", "")
    voice_id = resolve.get("voice_id", "")

    out_dir = os.path.join(job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts")
    os.makedirs(out_dir, exist_ok=True)
    audio_path = os.path.join(out_dir, "voiceover.wav")

    result = generate_voiceover(text, voice_id, audio_path)
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "Voiceover generation failed"))
    return result


def _stage_voiceover_merge(job: dict[str, Any]) -> dict[str, Any]:
    from creator_fish_audio import merge_audio_into_video

    resolve = job.get("artifacts", {}).get("voiceover_resolve", {})
    video_path = resolve.get("video_path", "")
    gen = job.get("artifacts", {}).get("voiceover_generate", {})
    audio_path = gen.get("output_path", "")

    if not video_path or not os.path.isfile(video_path):
        return {"status": "skipped", "reason": "No video_path for merge"}

    out_dir = os.path.join(job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts")
    output_path = os.path.join(out_dir, "video_with_voiceover.mp4")

    result = merge_audio_into_video(video_path, audio_path, output_path)
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "Audio merge failed"))
    return result


# ---------------------------------------------------------------------------
# Stage: voice_clone
# ---------------------------------------------------------------------------


def _stage_clone_resolve(job: dict[str, Any]) -> dict[str, Any]:
    config = job.get("config", {})
    audio_path = job.get("source", {}).get("audio_path", config.get("audio_path", ""))
    name = config.get("voice_name", config.get("name", "cloned_voice"))
    if not audio_path or not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio sample not found: {audio_path}")
    return {"audio_path": audio_path, "voice_name": name}


def _stage_clone_upload(job: dict[str, Any]) -> dict[str, Any]:
    from creator_fish_audio import clone_voice

    resolve = job.get("artifacts", {}).get("clone_resolve", {})
    audio_path = resolve.get("audio_path", "")
    name = resolve.get("voice_name", "cloned_voice")

    result = clone_voice(audio_path, name)
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "Voice clone failed"))
    return result


# ---------------------------------------------------------------------------
# Stage: embed_content (Gemini Embedding 2)
# ---------------------------------------------------------------------------


def _stage_embed_resolve(job: dict[str, Any]) -> dict[str, Any]:
    video_path = job.get("source", {}).get("video_path", job.get("source", {}).get("input_path", ""))
    if not video_path or not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    return {"video_path": video_path}


def _stage_embed_chunks(job: dict[str, Any]) -> dict[str, Any]:
    from creator_embeddings import embed_video

    resolve = job.get("artifacts", {}).get("embed_resolve", {})
    video_path = resolve.get("video_path", "")
    config = job.get("config", {})
    chunk_duration_s = int(config.get("chunk_duration_s", 120))

    result = embed_video(video_path, chunk_duration_s=chunk_duration_s)
    return result


def _stage_embed_store(job: dict[str, Any]) -> dict[str, Any]:
    from creator_embeddings import store_embeddings

    chunks = job.get("artifacts", {}).get("embed_chunks", {})
    embeddings = chunks.get("embeddings", [])
    video_path = chunks.get("video_path", "")
    config = job.get("config", {})
    collection_name = config.get("collection", "creator_video_embeddings")

    if not embeddings:
        return {"stored": 0, "collection": collection_name}

    count = store_embeddings(collection_name, embeddings, video_path)
    return {"stored": count, "collection": collection_name, "video_path": video_path}


def _get_audio_path(job: dict[str, Any]) -> str:
    """Get the extracted audio path from job artifacts."""
    audio_extract = job.get("artifacts", {}).get("audio_extract", {})
    audio_path = audio_extract.get("audio_path", "")
    if audio_path and os.path.isfile(audio_path):
        return audio_path

    # Fallback: look in job artifacts directory
    job_dir = os.path.join(job["workspace_dir"], "creator_jobs", job["job_id"], "artifacts")
    fallback = os.path.join(job_dir, "audio.wav")
    if os.path.isfile(fallback):
        return fallback

    raise FileNotFoundError("No audio file found for transcription")
