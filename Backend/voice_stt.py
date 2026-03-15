"""Voice STT — Speech-to-Text via local Whisper CLI.

Standalone module. No WhatsApp dependency.
Input: audio file (.ogg, .m4a, .mp3, .wav)
Output: {"text": str, "language": str, "duration_s": float, "model": str}
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

WHISPER_BIN = os.environ.get("WHISPER_BIN", shutil.which("whisper") or "whisper")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", shutil.which("ffmpeg") or "/usr/bin/ffmpeg")
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "base")
DEFAULT_LANGUAGE = "de"
MAX_AUDIO_SIZE_MB = 25


class TranscribeError(Exception):
    pass


def _convert_to_wav(input_path: str, tmp_dir: str) -> str:
    """Convert audio to 16kHz mono WAV via ffmpeg. Returns path to WAV."""
    out_path = os.path.join(tmp_dir, "audio.wav")
    cmd = [
        FFMPEG_BIN, "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise TranscribeError(f"ffmpeg conversion failed: {result.stderr[:300]}")
        return out_path
    except subprocess.TimeoutExpired:
        raise TranscribeError("ffmpeg conversion timed out (15s)")


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
        cmd = [
            FFMPEG_BIN.replace("ffmpeg", "ffprobe"),
            "-v", "quiet", "-show_entries", "format=duration",
            "-of", "json", audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


async def transcribe_audio(
    audio_path: str,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict:
    """Transcribe audio file via local Whisper CLI.

    Returns: {"text": str, "language": str, "duration_s": float, "model": str}
    Raises: TranscribeError on failure.
    """
    if not os.path.exists(audio_path):
        raise TranscribeError(f"Audio file not found: {audio_path}")

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb > MAX_AUDIO_SIZE_MB:
        raise TranscribeError(f"Audio file too large: {size_mb:.1f}MB (max {MAX_AUDIO_SIZE_MB}MB)")

    if not os.path.exists(WHISPER_BIN):
        raise TranscribeError(f"Whisper binary not found: {WHISPER_BIN}")

    duration_s = _get_audio_duration(audio_path)

    tmp_dir = tempfile.mkdtemp(prefix="bridge_stt_")
    try:
        ext = Path(audio_path).suffix.lower()
        if ext in (".wav",):
            work_path = audio_path
        else:
            work_path = _convert_to_wav(audio_path, tmp_dir)

        out_dir = os.path.join(tmp_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        cmd = [
            WHISPER_BIN,
            work_path,
            "--model", model,
            "--language", language,
            "--output_dir", out_dir,
            "--output_format", "json",
            "--fp16", "False",
        ]

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TranscribeError(f"Whisper timed out after {timeout}s")

        elapsed = time.monotonic() - start

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")[:300] if stderr else "unknown error"
            raise TranscribeError(f"Whisper failed (rc={proc.returncode}): {err_msg}")

        # Parse JSON output
        json_files = list(Path(out_dir).glob("*.json"))
        if not json_files:
            # Fallback: try to get text from stdout
            text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
            if not text:
                raise TranscribeError("No output from Whisper")
            return {
                "text": text,
                "language": language,
                "duration_s": duration_s,
                "model": model,
                "elapsed_s": round(elapsed, 2),
            }

        with open(json_files[0], "r") as f:
            whisper_out = json.load(f)

        text = whisper_out.get("text", "").strip()
        detected_lang = whisper_out.get("language", language)
        segments_raw = whisper_out.get("segments", [])
        segments = []
        if isinstance(segments_raw, list):
            for raw in segments_raw:
                if not isinstance(raw, dict):
                    continue
                segment_text = str(raw.get("text", "")).strip()
                if not segment_text:
                    continue
                segments.append(
                    {
                        "start": float(raw.get("start", 0) or 0),
                        "end": float(raw.get("end", 0) or 0),
                        "text": segment_text,
                    }
                )

        return {
            "text": text,
            "language": detected_lang,
            "duration_s": duration_s,
            "model": model,
            "elapsed_s": round(elapsed, 2),
            "segments": segments,
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Sync wrapper for non-async callers
def transcribe_audio_sync(
    audio_path: str,
    language: str = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict:
    """Synchronous wrapper for transcribe_audio."""
    return asyncio.run(transcribe_audio(audio_path, language, model, timeout))


# ---------------------------------------------------------------------------
# Chunked faster-whisper transcription
# ---------------------------------------------------------------------------

import threading
from typing import Any, Callable

_FW_MODEL: Any = None
_FW_MODEL_LOCK = threading.Lock()
_FW_MODEL_SIZE: str = ""


def _get_faster_whisper_model(model_size: str = "base") -> Any:
    """Lazy singleton for faster-whisper model.

    Thread-safe. Model is loaded once and reused.
    Returns None if faster-whisper is not installed.
    """
    global _FW_MODEL, _FW_MODEL_SIZE
    with _FW_MODEL_LOCK:
        if _FW_MODEL is not None and _FW_MODEL_SIZE == model_size:
            return _FW_MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("faster-whisper is not installed. Run: pip install faster-whisper")
        _FW_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
        _FW_MODEL_SIZE = model_size
        return _FW_MODEL


def plan_chunks(
    audio_path: str,
    chunk_duration_s: int = 300,
    overlap_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Plan audio chunks for transcription.

    Returns list of chunk descriptors with start_s, end_s, chunk_index.
    Does NOT create chunk files — that happens during transcription.
    """
    duration = _get_audio_duration(audio_path)
    if duration <= 0:
        # Fallback: single chunk
        return [{"chunk_index": 0, "start_s": 0.0, "end_s": 0.0}]

    chunks: list[dict[str, Any]] = []
    pos = 0.0
    idx = 0
    while pos < duration:
        end = min(pos + chunk_duration_s, duration)
        chunks.append({
            "chunk_index": idx,
            "start_s": pos,
            "end_s": end,
        })
        idx += 1
        pos = end - overlap_s
        if pos >= duration:
            break
        if end >= duration:
            break

    return chunks


def _extract_chunk_audio(
    audio_path: str,
    start_s: float,
    end_s: float,
    output_path: str,
) -> str:
    """Extract a time-bounded chunk from audio via ffmpeg."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", audio_path,
        "-ss", str(start_s),
    ]
    if end_s > 0:
        cmd.extend(["-to", str(end_s)])
    cmd.extend(["-ar", "16000", "-ac", "1", "-f", "wav", output_path])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise TranscribeError(f"Chunk extraction failed: {result.stderr[:300]}")
    return output_path


def transcribe_chunk(
    chunk_audio_path: str,
    model: Any,
    language: str = "de",
) -> dict[str, Any]:
    """Transcribe a single audio chunk using faster-whisper.

    Returns: {segments: [...], text: str, duration_s: float}
    """
    segments_iter, info = model.transcribe(
        chunk_audio_path,
        language=language,
        beam_size=5,
        vad_filter=True,
    )

    segments = []
    texts = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": text,
            })
            texts.append(text)

    return {
        "segments": segments,
        "text": " ".join(texts),
        "duration_s": round(info.duration, 3) if info.duration else 0.0,
        "language": info.language or language,
    }


def merge_chunk_results(
    chunk_results: list[dict[str, Any]],
    overlap_s: float = 1.0,
) -> dict[str, Any]:
    """Merge chunk transcription results, deduplicating overlap segments.

    Segments from overlapping regions are deduplicated by checking if a
    segment's start time (adjusted to global time) falls within the
    overlap window of the previous chunk's end.
    """
    if not chunk_results:
        return {"text": "", "segments": [], "duration_s": 0.0, "language": ""}

    all_segments: list[dict[str, Any]] = []
    prev_end_global = 0.0

    for chunk in sorted(chunk_results, key=lambda c: c.get("chunk_index", 0)):
        offset = chunk.get("start_offset_s", 0.0)
        for seg in chunk.get("segments", []):
            global_start = seg["start"] + offset
            global_end = seg["end"] + offset

            # Skip segments that fall within the overlap zone of previous chunk
            if all_segments and global_start < prev_end_global - overlap_s * 0.5:
                # Check if this segment's text matches last segment — dedup
                if all_segments[-1]["text"].strip() == seg["text"].strip():
                    continue

            all_segments.append({
                "start": round(global_start, 3),
                "end": round(global_end, 3),
                "text": seg["text"],
            })
            prev_end_global = global_end

    full_text = " ".join(s["text"] for s in all_segments)
    total_duration = max((s["end"] for s in all_segments), default=0.0)
    language = chunk_results[0].get("language", "") if chunk_results else ""

    return {
        "text": full_text,
        "segments": all_segments,
        "duration_s": round(total_duration, 3),
        "language": language,
    }


def transcribe_audio_chunked(
    audio_path: str,
    *,
    language: str = "de",
    model_size: str = "base",
    chunk_duration_s: int = 300,
    overlap_s: float = 1.0,
    on_chunk_complete: Callable | None = None,
) -> dict[str, Any]:
    """Full chunked transcription pipeline using faster-whisper.

    1. Plan chunks
    2. Extract and transcribe each chunk
    3. Merge results with overlap deduplication

    Args:
        on_chunk_complete: Optional callback(chunk_index, total_chunks, chunk_result)
    """
    if not os.path.isfile(audio_path):
        raise TranscribeError(f"Audio file not found: {audio_path}")

    model = _get_faster_whisper_model(model_size)
    chunks = plan_chunks(audio_path, chunk_duration_s, overlap_s)
    total = len(chunks)

    tmp_dir = tempfile.mkdtemp(prefix="bridge_chunked_stt_")
    try:
        chunk_results: list[dict[str, Any]] = []

        for chunk in chunks:
            idx = chunk["chunk_index"]

            # Extract chunk audio
            chunk_path = os.path.join(tmp_dir, f"chunk_{idx:04d}.wav")
            if chunk["end_s"] > 0:
                _extract_chunk_audio(audio_path, chunk["start_s"], chunk["end_s"], chunk_path)
            else:
                # Single chunk = whole file, just convert
                _convert_to_wav(audio_path, tmp_dir)
                chunk_path = os.path.join(tmp_dir, "audio.wav")

            # Transcribe
            result = transcribe_chunk(chunk_path, model, language)
            result["chunk_index"] = idx
            result["start_offset_s"] = chunk["start_s"]
            chunk_results.append(result)

            if on_chunk_complete:
                on_chunk_complete(idx, total, result)

        # Merge
        merged = merge_chunk_results(chunk_results, overlap_s)
        merged["model"] = model_size
        merged["chunk_count"] = total
        return merged

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python voice_stt.py <audio_file> [language] [model]")
        sys.exit(1)
    path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LANGUAGE
    mdl = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
    result = transcribe_audio_sync(path, lang, mdl)
    print(json.dumps(result, indent=2, ensure_ascii=False))
