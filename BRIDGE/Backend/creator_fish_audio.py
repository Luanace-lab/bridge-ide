"""Creator Fish Audio — TTS, Voice Cloning, Audio Merge.

Integrates Fish Audio API for text-to-speech and voice cloning.
BYOK: User provides their own API key in credentials.

Credential storage: ~/.config/bridge/social_credentials/fish_audio.json
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")

CREDENTIALS_DIR = os.path.join(
    os.environ.get("HOME", "/tmp"),
    ".config", "bridge", "social_credentials",
)


def _load_credentials() -> dict[str, Any] | None:
    path = os.path.join(CREDENTIALS_DIR, "fish_audio.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _get_api_key() -> str:
    creds = _load_credentials()
    if creds and creds.get("api_key"):
        return creds["api_key"]
    key = os.environ.get("FISH_AUDIO_API_KEY", "")
    return key


def _error(msg: str) -> dict[str, Any]:
    logger.error("Fish Audio: %s", msg)
    return {"status": "error", "error": msg}


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


def generate_voiceover(
    text: str,
    voice_id: str,
    output_path: str,
    emotions: bool = True,
) -> dict[str, Any]:
    """Generate speech audio from text using Fish Audio TTS.

    Args:
        text: Text to synthesize (supports emotion tags like [laugh])
        voice_id: Fish Audio voice/model ID
        output_path: Where to save the audio file
        emotions: Whether to process emotion tags
    """
    api_key = _get_api_key()
    if not api_key:
        return _error("No credentials. Store API key in ~/.config/bridge/social_credentials/fish_audio.json")

    try:
        audio_data = _call_fish_tts(api_key, text, voice_id)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        return {
            "status": "ok",
            "output_path": output_path,
            "size_bytes": len(audio_data),
            "voice_id": voice_id,
        }
    except Exception as exc:
        return _error(str(exc))


def _call_fish_tts(api_key: str, text: str, voice_id: str) -> bytes:
    """Call Fish Audio TTS API. Returns raw audio bytes."""
    from fish_audio_sdk import Session, TTSRequest

    session = Session(api_key)
    request = TTSRequest(text=text, reference_id=voice_id)

    audio_chunks = []
    for chunk in session.tts(request):
        audio_chunks.append(chunk)

    return b"".join(audio_chunks)


# ---------------------------------------------------------------------------
# Voice Cloning
# ---------------------------------------------------------------------------


def clone_voice(
    audio_path: str,
    name: str = "cloned_voice",
) -> dict[str, Any]:
    """Clone a voice from an audio sample.

    Args:
        audio_path: Path to audio sample (WAV, MP3, etc.)
        name: Display name for the cloned voice
    """
    api_key = _get_api_key()
    if not api_key:
        return _error("No credentials")

    if not os.path.isfile(audio_path):
        return _error(f"Audio file not found: {audio_path}")

    try:
        result = _call_fish_clone(api_key, audio_path, name)
        return {
            "status": "ok",
            "voice_id": result.get("voice_id", ""),
            "name": result.get("name", name),
        }
    except Exception as exc:
        return _error(str(exc))


def _call_fish_clone(api_key: str, audio_path: str, name: str) -> dict[str, Any]:
    """Call Fish Audio voice clone API."""
    from fish_audio_sdk import Session

    session = Session(api_key)

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    # Use the model creation endpoint
    result = session.create_model(
        title=name,
        voices=[audio_data],
    )

    return {
        "voice_id": getattr(result, "id", str(result)),
        "name": name,
    }


# ---------------------------------------------------------------------------
# Voice List
# ---------------------------------------------------------------------------


def list_voices() -> list[dict[str, Any]]:
    """List available voices (both cloned and catalog)."""
    api_key = _get_api_key()
    if not api_key:
        return []

    try:
        return _call_fish_list_voices(api_key)
    except Exception as exc:
        logger.error("Fish Audio list voices: %s", exc)
        return []


def _call_fish_list_voices(api_key: str) -> list[dict[str, Any]]:
    """Call Fish Audio API to list voices."""
    from fish_audio_sdk import Session

    session = Session(api_key)
    models = session.list_models()

    voices = []
    for model in models.items if hasattr(models, 'items') else models:
        voices.append({
            "id": getattr(model, "id", ""),
            "name": getattr(model, "title", getattr(model, "name", "")),
        })
    return voices


# ---------------------------------------------------------------------------
# Audio Merge (Voiceover into Video)
# ---------------------------------------------------------------------------


def merge_audio_into_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    replace_audio: bool = True,
) -> dict[str, Any]:
    """Merge voiceover audio into a video file.

    Args:
        replace_audio: If True, replaces original audio. If False, mixes.
    """
    if not os.path.isfile(video_path):
        return _error(f"Video not found: {video_path}")
    if not os.path.isfile(audio_path):
        return _error(f"Audio not found: {audio_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if replace_audio:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path,
        ]
    else:
        # Mix original + voiceover
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=shortest[a]",
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return _error(f"Merge failed: {result.stderr[:500]}")

    return {
        "status": "ok",
        "output_path": output_path,
        "size_bytes": os.path.getsize(output_path),
    }
