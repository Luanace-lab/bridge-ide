"""Voice TTS — Text-to-Speech via ElevenLabs API.

Standalone module. No WhatsApp dependency.
Input: text string
Output: {"audio_path": str, "duration_s": float, "chars_used": int}
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid

import httpx

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", shutil.which("ffmpeg") or "/usr/bin/ffmpeg")

_ELEVENLABS_KEY_PATH = os.environ.get(
    "ELEVENLABS_KEY_PATH",
    os.path.expanduser("~/.config/bridge/elevenlabs_api_key"),
)
_DEFAULT_VOICE_ID = "REDACTED_VOICE_ID"  # Carla Blum
_MODEL_ID = "eleven_flash_v2_5"
_OUTPUT_DIR = os.environ.get("BRIDGE_TTS_DIR", "/tmp/bridge_tts")
_API_BASE = "https://api.elevenlabs.io/v1"
_MAX_TEXT_LENGTH = 5000


class SynthesizeError(Exception):
    pass


def _load_api_key() -> str:
    """Load ElevenLabs API key. Fail-closed: no key = error."""
    env_val = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if env_val:
        return env_val
    if os.path.exists(_ELEVENLABS_KEY_PATH):
        try:
            with open(_ELEVENLABS_KEY_PATH, "r") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    raise SynthesizeError("ElevenLabs API key not found")


def _ensure_output_dir() -> None:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)


def _convert_to_opus(input_path: str) -> str:
    """Convert audio to Ogg Opus via ffmpeg. Required because ElevenLabs
    returns MP3 despite requesting ogg_opus format. Go Bridge validates
    OggS signature and rejects MP3.

    Returns path to converted .ogg file (replaces original).
    """
    out_path = input_path + ".opus.ogg"
    cmd = [
        FFMPEG_BIN, "-y", "-i", input_path,
        "-c:a", "libopus", "-b:a", "48k", out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise SynthesizeError(f"ffmpeg opus conversion failed: {result.stderr[:300]}")
        # Replace original with converted
        os.replace(out_path, input_path)
        return input_path
    except subprocess.TimeoutExpired:
        raise SynthesizeError("ffmpeg opus conversion timed out (15s)")
    finally:
        # Cleanup temp file if still exists
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


async def synthesize_speech(
    text: str,
    voice_id: str = _DEFAULT_VOICE_ID,
    output_format: str = "ogg_opus",
    timeout: float = 10.0,
) -> dict:
    """Synthesize text to audio via ElevenLabs API.

    Returns: {"audio_path": str, "duration_s": float, "chars_used": int}
    Raises: SynthesizeError on failure.
    """
    if not text or not text.strip():
        raise SynthesizeError("Empty text")
    if len(text) > _MAX_TEXT_LENGTH:
        raise SynthesizeError(f"Text too long: {len(text)} chars (max {_MAX_TEXT_LENGTH})")

    api_key = _load_api_key()
    _ensure_output_dir()

    url = f"{_API_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/ogg",
    }
    # Map output_format to ElevenLabs format parameter
    format_map = {
        "ogg_opus": "ogg_opus",
        "mp3": "mp3_44100_128",
        "wav": "pcm_16000",
    }
    el_format = format_map.get(output_format, "ogg_opus")

    body = {
        "text": text.strip(),
        "model_id": _MODEL_ID,
        "voice_settings": {
            "stability": 1.0,
            "similarity_boost": 0.5,
            "style": 0.75,
        },
        "output_format": el_format,
    }

    ext = ".ogg" if "ogg" in el_format else (".mp3" if "mp3" in el_format else ".wav")
    out_file = os.path.join(_OUTPUT_DIR, f"{uuid.uuid4().hex}{ext}")

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise SynthesizeError(f"ElevenLabs API timed out after {timeout}s")
        except httpx.RequestError as e:
            raise SynthesizeError(f"ElevenLabs API request error: {e}")

    elapsed = time.monotonic() - start

    if response.status_code == 401:
        raise SynthesizeError("ElevenLabs API: Invalid API key")
    if response.status_code == 429:
        raise SynthesizeError("ElevenLabs API: Rate limit or quota exceeded")
    if response.status_code != 200:
        detail = response.text[:300] if response.text else f"HTTP {response.status_code}"
        raise SynthesizeError(f"ElevenLabs API error: {detail}")

    with open(out_file, "wb") as f:
        f.write(response.content)

    # ElevenLabs returns MP3 despite ogg_opus parameter — convert to real Ogg Opus
    if "ogg" in el_format:
        _convert_to_opus(out_file)

    file_size = os.path.getsize(out_file)
    # Rough duration estimate: ogg_opus ~48kbps
    duration_s = (file_size * 8) / 48000 if file_size > 0 else 0.0

    return {
        "audio_path": out_file,
        "duration_s": round(duration_s, 2),
        "chars_used": len(text.strip()),
        "elapsed_s": round(elapsed, 2),
    }


async def get_quota() -> dict:
    """Get ElevenLabs subscription quota.

    Returns: {"used": int, "limit": int, "remaining": int, "tier": str}
    """
    api_key = _load_api_key()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_API_BASE}/user/subscription",
            headers={"xi-api-key": api_key},
        )
    if r.status_code != 200:
        raise SynthesizeError(f"ElevenLabs quota check failed: HTTP {r.status_code}")
    d = r.json()
    used = d.get("character_count", 0)
    limit = d.get("character_limit", 0)
    return {
        "used": used,
        "limit": limit,
        "remaining": limit - used,
        "tier": d.get("tier", "unknown"),
    }


async def list_voices() -> list[dict]:
    """List available ElevenLabs voices.

    Returns: [{"id": str, "name": str, "language": str}]
    """
    api_key = _load_api_key()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_API_BASE}/voices",
            headers={"xi-api-key": api_key},
        )
    if r.status_code != 200:
        raise SynthesizeError(f"ElevenLabs voices failed: HTTP {r.status_code}")
    voices = r.json().get("voices", [])
    return [{"id": v["voice_id"], "name": v["name"]} for v in voices]


# Sync wrappers
def synthesize_speech_sync(text: str, voice_id: str = _DEFAULT_VOICE_ID, **kwargs) -> dict:
    return asyncio.run(synthesize_speech(text, voice_id, **kwargs))


def get_quota_sync() -> dict:
    return asyncio.run(get_quota())


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python voice_tts.py <text> [voice_id]")
        print("       python voice_tts.py --quota")
        print("       python voice_tts.py --voices")
        sys.exit(1)

    if sys.argv[1] == "--quota":
        result = get_quota_sync()
        print(json.dumps(result, indent=2))
    elif sys.argv[1] == "--voices":
        voices = asyncio.run(list_voices())
        for v in voices:
            print(f"  {v['name']} ({v['id']})")
    else:
        text = sys.argv[1]
        vid = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_VOICE_ID
        result = synthesize_speech_sync(text, vid)
        print(json.dumps(result, indent=2, ensure_ascii=False))
