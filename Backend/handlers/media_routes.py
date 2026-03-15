"""Media pipeline POST routes extracted from server.py."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from typing import Any

from creator_media import FFMPEG_BIN, FFPROBE_BIN


def handle_post(handler: Any, path: str) -> bool:
    if path == "/media/info":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("path", "")).strip()
        if not input_path:
            handler._respond(400, {"error": "'path' is required"})
            return True
        if not os.path.isfile(input_path):
            handler._respond(404, {"error": f"file not found: {input_path}"})
            return True
        try:
            proc = subprocess.run(
                [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", input_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                handler._respond(500, {"error": "ffprobe failed", "stderr": proc.stderr[:2000]})
                return True
            info = json.loads(proc.stdout)
            handler._respond(200, {"ok": True, "info": info})
        except subprocess.TimeoutExpired:
            handler._respond(504, {"error": "ffprobe timed out (30s)"})
        except (json.JSONDecodeError, OSError) as exc:
            handler._respond(500, {"error": f"ffprobe parse error: {exc}"})
        return True

    if path == "/media/convert":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input", "")).strip()
        output_path = str(data.get("output", "")).strip()
        if not input_path or not output_path:
            handler._respond(400, {"error": "'input' and 'output' are required"})
            return True
        if not os.path.isfile(input_path):
            handler._respond(404, {"error": f"input file not found: {input_path}"})
            return True
        output_dir = os.path.dirname(os.path.abspath(output_path))
        if not os.path.isdir(output_dir):
            handler._respond(400, {"error": f"output directory does not exist: {output_dir}"})
            return True
        codec_args: list[str] = []
        if data.get("video_codec"):
            codec_args.extend(["-c:v", str(data["video_codec"])])
        if data.get("audio_codec"):
            codec_args.extend(["-c:a", str(data["audio_codec"])])
        if data.get("bitrate"):
            codec_args.extend(["-b:a", str(data["bitrate"])])
        extra = data.get("extra_args")
        if isinstance(extra, list):
            codec_args.extend([str(a) for a in extra[:20]])
        try:
            timeout_s = min(float(data.get("timeout", 300)), 300)
        except (ValueError, TypeError):
            timeout_s = 300.0
        cmd = [FFMPEG_BIN, "-y", "-i", input_path] + codec_args + [output_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            if proc.returncode != 0:
                handler._respond(500, {"error": "ffmpeg convert failed", "stderr": proc.stderr[:2000]})
                return True
            file_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
            handler._respond(200, {"ok": True, "output": output_path, "size_bytes": file_size})
        except subprocess.TimeoutExpired:
            handler._respond(504, {"error": f"ffmpeg timed out ({timeout_s}s)"})
        except OSError as exc:
            handler._respond(500, {"error": f"ffmpeg error: {exc}"})
        return True

    if path == "/media/extract":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input", "")).strip()
        output_path = str(data.get("output", "")).strip()
        extract_type = str(data.get("type", "audio")).strip()
        if not input_path or not output_path:
            handler._respond(400, {"error": "'input' and 'output' are required"})
            return True
        if not os.path.isfile(input_path):
            handler._respond(404, {"error": f"input file not found: {input_path}"})
            return True
        output_dir = os.path.dirname(os.path.abspath(output_path))
        if not os.path.isdir(output_dir):
            handler._respond(400, {"error": f"output directory does not exist: {output_dir}"})
            return True
        if extract_type == "audio":
            cmd = [FFMPEG_BIN, "-y", "-i", input_path, "-vn", "-acodec", "copy", output_path]
        elif extract_type == "frames":
            fps = str(data.get("fps", "1"))
            if not re.match(r"^\d+(\.\d+)?(/\d+)?$", fps):
                handler._respond(400, {"error": "fps must be numeric (e.g. '1', '0.5', '30/1')"})
                return True
            cmd = [FFMPEG_BIN, "-y", "-i", input_path, "-vf", f"fps={fps}", output_path]
        elif extract_type == "video":
            cmd = [FFMPEG_BIN, "-y", "-i", input_path, "-an", "-c:v", "copy", output_path]
        else:
            handler._respond(400, {"error": f"unknown extract type: {extract_type}. Use 'audio', 'video', or 'frames'."})
            return True
        try:
            timeout_s = min(float(data.get("timeout", 300)), 300)
        except (ValueError, TypeError):
            timeout_s = 300.0
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            if proc.returncode != 0:
                handler._respond(500, {"error": "ffmpeg extract failed", "stderr": proc.stderr[:2000]})
                return True
            if extract_type == "frames":
                pattern = output_path.replace("%04d", "*").replace("%03d", "*").replace("%d", "*")
                frame_count = len(glob.glob(pattern))
                handler._respond(200, {"ok": True, "type": "frames", "output_pattern": output_path, "frame_count": frame_count})
            else:
                file_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
                handler._respond(200, {"ok": True, "type": extract_type, "output": output_path, "size_bytes": file_size})
        except subprocess.TimeoutExpired:
            handler._respond(504, {"error": f"ffmpeg timed out ({timeout_s}s)"})
        except OSError as exc:
            handler._respond(500, {"error": f"ffmpeg error: {exc}"})
        return True

    return False
