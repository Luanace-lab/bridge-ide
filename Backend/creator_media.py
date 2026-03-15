from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from voice_stt import FFMPEG_BIN, transcribe_audio_sync


FFPROBE_BIN = FFMPEG_BIN.replace("ffmpeg", "ffprobe")
YT_DLP_BIN = shutil.which("yt-dlp") or "yt-dlp"
SOCIAL_PRESETS: dict[str, dict[str, Any]] = {
    "youtube_short": {
        "platform": "youtube",
        "surface": "shorts",
        "width": 1080,
        "height": 1920,
    },
    "instagram_reel": {
        "platform": "instagram",
        "surface": "reel",
        "width": 1080,
        "height": 1920,
    },
    "square_post": {
        "platform": "generic",
        "surface": "square",
        "width": 1080,
        "height": 1080,
    },
    "landscape_video": {
        "platform": "generic",
        "surface": "landscape",
        "width": 1920,
        "height": 1080,
    },
}


class CreatorMediaError(Exception):
    pass


def _run_command(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CreatorMediaError(f"command timed out after {timeout}s: {' '.join(cmd[:4])}") from exc
    except OSError as exc:
        raise CreatorMediaError(str(exc)) from exc
    if result.returncode != 0:
        raise CreatorMediaError(result.stderr[:500] or f"command failed: {' '.join(cmd[:4])}")
    return result


def extract_keyframes(
    input_path: str,
    interval_s: float = 2.0,
    max_frames: int = 15,
    output_dir: str = "",
) -> list[str]:
    """Extract keyframes from video at regular intervals.

    Returns list of JPEG file paths.
    """
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"Video not found: {input_path}")

    if not output_dir:
        output_dir = os.path.dirname(input_path)
    os.makedirs(output_dir, exist_ok=True)

    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        FFPROBE_BIN.replace("ffprobe", "ffmpeg"),
        "-i", input_path,
        "-vf", f"fps=1/{interval_s}",
        "-frames:v", str(max_frames),
        "-q:v", "3",
        "-y",
        pattern,
    ]
    _run_command(cmd, timeout=60)

    frames = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )
    return frames[:max_frames]


def probe_media(input_path: str) -> dict[str, Any]:
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"file not found: {input_path}")
    result = _run_command(
        [
            FFPROBE_BIN,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            input_path,
        ],
        timeout=30,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CreatorMediaError(f"ffprobe parse error: {exc}") from exc

    fmt = payload.get("format", {})
    streams = payload.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]

    return {
        "path": input_path,
        "format_name": fmt.get("format_name", ""),
        "duration_s": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "raw": payload,
    }


def list_social_presets() -> dict[str, dict[str, Any]]:
    presets: dict[str, dict[str, Any]] = {}
    for name, preset in SOCIAL_PRESETS.items():
        presets[name] = {
            **preset,
            "aspect_ratio": f"{preset['width']}:{preset['height']}",
        }
    return presets


def extract_audio_for_transcription(input_path: str, output_path: str) -> dict[str, Any]:
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"file not found: {input_path}")
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(output_dir):
        raise CreatorMediaError(f"output directory does not exist: {output_dir}")

    _run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-i",
            input_path,
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            output_path,
        ],
        timeout=60,
    )
    audio_info = probe_media(output_path)
    return {
        "audio_path": output_path,
        "duration_s": audio_info["duration_s"],
        "size_bytes": os.path.getsize(output_path),
    }


def _normalize_segments(segments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in segments or []:
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        normalized.append(
            {
                "start": float(raw.get("start", 0) or 0),
                "end": float(raw.get("end", 0) or 0),
                "text": text,
            }
        )
    return normalized


def _detect_creator_source_type(source_url: str) -> str:
    parsed = urlparse((source_url or "").strip())
    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.lower()
        if host.endswith("youtube.com") or host.endswith("youtu.be"):
            return "youtube"
        return "url"
    if parsed.scheme == "file":
        return "file"
    raise CreatorMediaError("source_url must use http, https, or file")


def _guess_download_filename(source_url: str) -> str:
    parsed = urlparse((source_url or "").strip())
    basename = os.path.basename(parsed.path) or "source.bin"
    stem = Path(basename).stem or "source"
    suffix = Path(basename).suffix or ".bin"
    safe_stem = _sanitize_package_name(stem)
    return f"{safe_stem}{suffix}"


def _download_direct_source(source_url: str, download_dir: str) -> dict[str, Any]:
    os.makedirs(download_dir, exist_ok=True)
    output_path = os.path.join(download_dir, _guess_download_filename(source_url))
    request = Request(source_url, headers={"User-Agent": "BridgeCreator/1.0"})
    try:
        with urlopen(request, timeout=180) as response, open(output_path, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
            resolved_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
    except OSError as exc:
        raise CreatorMediaError(str(exc)) from exc
    return {
        "method": "direct",
        "local_path": output_path,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "size_bytes": os.path.getsize(output_path),
    }


def _download_youtube_source(source_url: str, download_dir: str) -> dict[str, Any]:
    os.makedirs(download_dir, exist_ok=True)
    output_template = os.path.join(download_dir, "youtube_source.%(ext)s")
    metadata_cmd = [
        YT_DLP_BIN,
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        source_url,
    ]
    metadata_result = _run_command(metadata_cmd, timeout=300)
    try:
        metadata = json.loads(metadata_result.stdout)
    except json.JSONDecodeError as exc:
        raise CreatorMediaError(f"yt-dlp metadata parse error: {exc}") from exc

    download_cmd = [
        YT_DLP_BIN,
        "--no-progress",
        "--no-playlist",
        "--print",
        "after_move:filepath",
        "-o",
        output_template,
        source_url,
    ]
    download_result = _run_command(download_cmd, timeout=900)
    lines = [line.strip() for line in download_result.stdout.splitlines() if line.strip()]
    local_path = lines[-1] if lines else ""
    if not local_path or not os.path.isfile(local_path):
        raise CreatorMediaError("yt-dlp did not produce a downloadable file")

    return {
        "method": "yt-dlp",
        "local_path": local_path,
        "resolved_url": str(metadata.get("webpage_url") or source_url),
        "title": str(metadata.get("title", "")),
        "source_id": str(metadata.get("id", "")),
        "channel": str(metadata.get("channel", "") or metadata.get("uploader", "")),
        "duration_s": float(metadata.get("duration", 0) or 0),
        "size_bytes": os.path.getsize(local_path),
    }


def group_segments_into_chapters(
    segments: list[dict[str, Any]],
    *,
    target_duration_s: float = 45.0,
) -> list[dict[str, Any]]:
    if target_duration_s <= 0:
        raise CreatorMediaError("target_duration_s must be > 0")
    chapters: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []
    bucket_start = 0.0

    for segment in segments:
        if not bucket:
            bucket_start = float(segment["start"])
        bucket.append(segment)
        bucket_end = float(bucket[-1]["end"])
        bucket_text = " ".join(item["text"] for item in bucket).strip()
        if bucket_end - bucket_start < target_duration_s:
            continue
        chapters.append(
            {
                "start": bucket_start,
                "end": bucket_end,
                "title": " ".join(bucket_text.split()[:8]).strip(),
                "text": bucket_text,
            }
        )
        bucket = []

    if bucket:
        bucket_end = float(bucket[-1]["end"])
        bucket_text = " ".join(item["text"] for item in bucket).strip()
        chapters.append(
            {
                "start": bucket_start,
                "end": bucket_end,
                "title": " ".join(bucket_text.split()[:8]).strip(),
                "text": bucket_text,
            }
        )

    return chapters


def pick_highlight_candidates(
    segments: list[dict[str, Any]],
    *,
    max_candidates: int = 3,
    min_duration_s: float = 2.0,
) -> list[dict[str, Any]]:
    if max_candidates <= 0:
        raise CreatorMediaError("max_candidates must be > 0")
    normalized = _normalize_segments(segments)
    scored: list[dict[str, Any]] = []
    for segment in normalized:
        duration = max(0.0, float(segment["end"]) - float(segment["start"]))
        if duration < min_duration_s:
            continue
        word_count = len(segment["text"].split())
        score = word_count + duration
        scored.append(
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": segment["text"],
                "duration_s": round(duration, 3),
                "word_count": word_count,
                "score": round(score, 3),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:max_candidates]


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: list[dict[str, Any]], output_path: str) -> dict[str, Any]:
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(output_dir):
        raise CreatorMediaError(f"output directory does not exist: {output_dir}")
    lines: list[str] = []
    normalized = _normalize_segments(segments)
    for index, segment in enumerate(normalized, start=1):
        lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(segment['start'])} --> {_format_srt_timestamp(segment['end'])}",
                segment["text"],
                "",
            ]
        )
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return {
        "output_path": output_path,
        "segment_count": len(normalized),
        "size_bytes": os.path.getsize(output_path),
    }


def _clip_segments_to_window(
    segments: list[dict[str, Any]],
    *,
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    for segment in _normalize_segments(segments):
        segment_start = float(segment["start"])
        segment_end = float(segment["end"])
        if segment_end <= start_s or segment_start >= end_s:
            continue
        clipped.append(
            {
                "start": max(segment_start, start_s) - start_s,
                "end": min(segment_end, end_s) - start_s,
                "text": segment["text"],
            }
        )
    return clipped


def _escape_filter_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
    )


def _sanitize_package_name(value: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("._")
    return sanitized or "creator_package"


def _normalize_package_metadata_map(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise CreatorMediaError("package metadata must be a JSON object")
    return dict(payload)


def _build_metadata_sidecar_payload(
    *,
    package_name: str,
    preset_name: str,
    asset: dict[str, Any],
    default_metadata: dict[str, Any],
    metadata_by_preset: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(default_metadata)
    preset_metadata = metadata_by_preset.get(preset_name)
    if preset_metadata is not None:
        if not isinstance(preset_metadata, dict):
            raise CreatorMediaError(f"metadata for preset '{preset_name}' must be a JSON object")
        merged.update(preset_metadata)

    hashtags_raw = merged.pop("hashtags", [])
    if hashtags_raw is None:
        hashtags_raw = []
    if not isinstance(hashtags_raw, list):
        raise CreatorMediaError("metadata field 'hashtags' must be a list when provided")
    hashtags = [str(tag).strip() for tag in hashtags_raw if str(tag).strip()]

    title = str(merged.pop("title", "")).strip()
    caption = str(merged.pop("caption", "")).strip()
    description = str(merged.pop("description", "")).strip()

    return {
        "package_name": package_name,
        "preset_name": preset_name,
        "platform": asset["platform"],
        "surface": asset["surface"],
        "asset_path": asset["output_path"],
        "title": title,
        "caption": caption,
        "description": description,
        "hashtags": hashtags,
        "metadata": dict(merged),
    }


def export_clip(
    input_path: str,
    output_path: str,
    *,
    start_s: float,
    end_s: float,
) -> dict[str, Any]:
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"file not found: {input_path}")
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(output_dir):
        raise CreatorMediaError(f"output directory does not exist: {output_dir}")
    start_s = float(start_s)
    end_s = float(end_s)
    if start_s < 0 or end_s <= start_s:
        raise CreatorMediaError("invalid clip range")

    _run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-ss",
            f"{start_s:.3f}",
            "-to",
            f"{end_s:.3f}",
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            output_path,
        ],
        timeout=120,
    )
    info = probe_media(output_path)
    return {
        "output_path": output_path,
        "start_s": start_s,
        "end_s": end_s,
        "duration_s": info["duration_s"],
        "size_bytes": os.path.getsize(output_path),
    }


def export_social_clip(
    input_path: str,
    output_path: str,
    *,
    start_s: float,
    end_s: float,
    preset_name: str = "youtube_short",
    segments: list[dict[str, Any]] | None = None,
    burn_subtitles: bool = False,
) -> dict[str, Any]:
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"file not found: {input_path}")
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(output_dir):
        raise CreatorMediaError(f"output directory does not exist: {output_dir}")
    if preset_name not in SOCIAL_PRESETS:
        raise CreatorMediaError(f"unknown preset: {preset_name}")

    start_s = float(start_s)
    end_s = float(end_s)
    if start_s < 0 or end_s <= start_s:
        raise CreatorMediaError("invalid clip range")

    preset = SOCIAL_PRESETS[preset_name]
    width = int(preset["width"])
    height = int(preset["height"])
    filter_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    subtitle_segment_count = 0

    with tempfile.TemporaryDirectory(prefix="bridge_creator_social_") as tmp_dir:
        if burn_subtitles:
            if not segments:
                raise CreatorMediaError("segments are required when burn_subtitles=True")
            clipped_segments = _clip_segments_to_window(segments, start_s=start_s, end_s=end_s)
            if not clipped_segments:
                raise CreatorMediaError("no subtitle segments overlap the requested clip range")
            subtitle_path = os.path.join(tmp_dir, "clip_subtitles.srt")
            write_srt(clipped_segments, subtitle_path)
            subtitle_segment_count = len(clipped_segments)
            subtitle_style = (
                "FontName=DejaVu Sans,"
                "Alignment=2,"
                "FontSize=32,"
                "PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00202020,"
                "BorderStyle=1,"
                "Outline=2,"
                "Shadow=0,"
                "MarginV=72"
            )
            filter_parts.append(
                f"subtitles='{_escape_filter_value(subtitle_path)}'"
                f":force_style='{subtitle_style}'"
            )

        _run_command(
            [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{start_s:.3f}",
                "-to",
                f"{end_s:.3f}",
                "-i",
                input_path,
                "-vf",
                ",".join(filter_parts),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                output_path,
            ],
            timeout=180,
        )

    info = probe_media(output_path)
    video_stream = info["video_streams"][0] if info["video_streams"] else {}
    return {
        "output_path": output_path,
        "start_s": start_s,
        "end_s": end_s,
        "duration_s": info["duration_s"],
        "size_bytes": os.path.getsize(output_path),
        "preset_name": preset_name,
        "platform": preset["platform"],
        "surface": preset["surface"],
        "width": int(video_stream.get("width", 0) or width),
        "height": int(video_stream.get("height", 0) or height),
        "burned_subtitles": burn_subtitles,
        "subtitle_segment_count": subtitle_segment_count,
    }


def create_social_package(
    input_path: str,
    output_dir: str,
    *,
    package_name: str,
    start_s: float,
    end_s: float,
    preset_names: list[str] | None = None,
    segments: list[dict[str, Any]] | None = None,
    burn_subtitles: bool = True,
    write_sidecar_srt: bool = True,
    default_metadata: dict[str, Any] | None = None,
    metadata_by_preset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not os.path.isfile(input_path):
        raise CreatorMediaError(f"file not found: {input_path}")
    if not os.path.isdir(output_dir):
        raise CreatorMediaError(f"output directory does not exist: {output_dir}")

    safe_name = _sanitize_package_name(package_name)
    normalized_default_metadata = _normalize_package_metadata_map(default_metadata)
    normalized_metadata_by_preset = _normalize_package_metadata_map(metadata_by_preset)
    selected_presets = list(preset_names or ["youtube_short", "square_post", "landscape_video"])
    if not selected_presets:
        raise CreatorMediaError("at least one preset is required")
    for preset_name in selected_presets:
        if preset_name not in SOCIAL_PRESETS:
            raise CreatorMediaError(f"unknown preset: {preset_name}")

    clipped_segments: list[dict[str, Any]] = []
    if segments:
        clipped_segments = _clip_segments_to_window(segments, start_s=float(start_s), end_s=float(end_s))
    if burn_subtitles and not clipped_segments:
        raise CreatorMediaError("subtitle segments are required for a burned-subtitle package")
    if write_sidecar_srt and segments is not None and not clipped_segments:
        raise CreatorMediaError("no subtitle segments overlap the requested package range")

    assets: list[dict[str, Any]] = []
    for preset_name in selected_presets:
        asset_path = os.path.join(output_dir, f"{safe_name}_{preset_name}.mp4")
        asset = export_social_clip(
            input_path,
            asset_path,
            start_s=float(start_s),
            end_s=float(end_s),
            preset_name=preset_name,
            segments=clipped_segments,
            burn_subtitles=burn_subtitles,
        )
        assets.append(asset)

    srt_result: dict[str, Any] | None = None
    if write_sidecar_srt and clipped_segments:
        srt_path = os.path.join(output_dir, f"{safe_name}.srt")
        srt_result = write_srt(clipped_segments, srt_path)

    metadata_sidecars: list[dict[str, Any]] = []
    for asset in assets:
        preset_name = str(asset["preset_name"])
        sidecar_payload = _build_metadata_sidecar_payload(
            package_name=safe_name,
            preset_name=preset_name,
            asset=asset,
            default_metadata=normalized_default_metadata,
            metadata_by_preset=normalized_metadata_by_preset,
        )
        if not any(
            [
                sidecar_payload["title"],
                sidecar_payload["caption"],
                sidecar_payload["description"],
                sidecar_payload["hashtags"],
                sidecar_payload["metadata"],
            ]
        ):
            continue
        sidecar_path = os.path.join(output_dir, f"{safe_name}_{preset_name}.metadata.json")
        with open(sidecar_path, "w", encoding="utf-8") as handle:
            json.dump(sidecar_payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
        metadata_sidecars.append(
            {
                "preset_name": preset_name,
                "path": sidecar_path,
                "title": sidecar_payload["title"],
                "caption": sidecar_payload["caption"],
                "description": sidecar_payload["description"],
                "hashtags": sidecar_payload["hashtags"],
            }
        )

    manifest = {
        "package_name": safe_name,
        "input_path": input_path,
        "output_dir": output_dir,
        "start_s": float(start_s),
        "end_s": float(end_s),
        "preset_names": selected_presets,
        "burn_subtitles": burn_subtitles,
        "write_sidecar_srt": write_sidecar_srt,
        "assets": assets,
        "sidecar_srt": srt_result,
        "default_metadata": normalized_default_metadata,
        "metadata_by_preset": normalized_metadata_by_preset,
        "metadata_sidecars": metadata_sidecars,
    }
    manifest_path = os.path.join(output_dir, f"{safe_name}_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
    manifest["manifest_path"] = manifest_path
    return manifest


def ingest_url_media(
    source_url: str,
    workspace_dir: str,
    *,
    language: str = "de",
    model: str | None = None,
    transcribe: bool = True,
) -> dict[str, Any]:
    if not os.path.isdir(workspace_dir):
        raise CreatorMediaError(f"workspace directory does not exist: {workspace_dir}")

    source_url = (source_url or "").strip()
    if not source_url:
        raise CreatorMediaError("source_url is required")

    source_type = _detect_creator_source_type(source_url)
    download_dir = os.path.join(workspace_dir, "downloads")
    if source_type == "youtube":
        download_info = _download_youtube_source(source_url, download_dir)
    else:
        download_info = _download_direct_source(source_url, download_dir)

    result = ingest_local_media(
        download_info["local_path"],
        workspace_dir,
        language=language,
        model=model,
        transcribe=transcribe,
    )
    result["source"] = {
        "type": source_type,
        "original_url": source_url,
        "resolved_url": str(download_info.get("resolved_url") or source_url),
        "provider": "youtube" if source_type == "youtube" else source_type,
        "title": str(download_info.get("title", "")),
        "source_id": str(download_info.get("source_id", "")),
        "channel": str(download_info.get("channel", "")),
    }
    result["download"] = {
        "method": str(download_info.get("method", "")),
        "local_path": str(download_info["local_path"]),
        "size_bytes": int(download_info.get("size_bytes", os.path.getsize(download_info["local_path"]))),
        "content_type": str(download_info.get("content_type", "")),
    }
    return result


def ingest_local_media(
    input_path: str,
    workspace_dir: str,
    *,
    language: str = "de",
    model: str | None = None,
    transcribe: bool = True,
) -> dict[str, Any]:
    if not os.path.isdir(workspace_dir):
        raise CreatorMediaError(f"workspace directory does not exist: {workspace_dir}")

    media_info = probe_media(input_path)
    stem = Path(input_path).stem
    audio_path = os.path.join(workspace_dir, f"{stem}_audio.wav")
    audio_info = extract_audio_for_transcription(input_path, audio_path)

    result: dict[str, Any] = {
        "input_path": input_path,
        "workspace_dir": workspace_dir,
        "media": media_info,
        "audio": audio_info,
        "transcript": None,
        "chapters": [],
        "highlights": [],
        "artifacts": {"audio_path": audio_path},
    }

    if not transcribe:
        return result

    stt = transcribe_audio_sync(audio_path, language=language, model=model or "base")
    segments = _normalize_segments(stt.get("segments"))
    result["transcript"] = {
        **stt,
        "segments": segments,
    }
    result["chapters"] = group_segments_into_chapters(segments) if segments else []
    result["highlights"] = pick_highlight_candidates(segments) if segments else []
    return result
