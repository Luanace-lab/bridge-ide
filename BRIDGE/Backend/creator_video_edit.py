"""Creator Video Edit — FFmpeg-based template rendering.

Provides template-based video rendering using only ffmpeg (no Node.js deps).
Supports: title overlays, color intros, fade effects, caption styles.

Called by creator_job_stages.py for the render_template job type.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "creator_templates")


class RenderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------


def list_templates() -> list[dict[str, Any]]:
    """List available rendering templates."""
    templates = []
    if not os.path.isdir(TEMPLATES_DIR):
        return templates
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(TEMPLATES_DIR, fname)
            try:
                with open(path) as f:
                    tmpl = json.load(f)
                templates.append({
                    "name": tmpl.get("name", fname[:-5]),
                    "description": tmpl.get("description", ""),
                    "file": fname,
                })
            except (json.JSONDecodeError, OSError):
                continue
    return templates


def load_template(name: str) -> dict[str, Any]:
    """Load a template by name."""
    path = os.path.join(TEMPLATES_DIR, f"{name}.json")
    if not os.path.isfile(path):
        raise RenderError(f"Template not found: {name}")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Render Functions
# ---------------------------------------------------------------------------


def render_clip_with_title(
    input_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
    title: str = "",
    font_size: int = 48,
    font_color: str = "white",
    bg_opacity: float = 0.6,
    title_duration_s: float = 3.0,
    fade_in_s: float = 0.5,
    fade_out_s: float = 0.5,
    width: int = 1080,
    height: int = 1920,
) -> dict[str, Any]:
    """Render a clip with a title overlay and fade effects.

    - Scales/crops to target dimensions
    - Adds semi-transparent title overlay for first N seconds
    - Fade-in at start, fade-out at end
    """
    if not os.path.isfile(input_path):
        raise RenderError(f"Input not found: {input_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    duration = end_s - start_s
    filters = []

    # Scale and crop
    filters.append(f"scale={width}:{height}:force_original_aspect_ratio=increase")
    filters.append(f"crop={width}:{height}")

    # Fade in/out
    if fade_in_s > 0:
        filters.append(f"fade=t=in:st=0:d={fade_in_s}")
    if fade_out_s > 0:
        fade_start = max(0, duration - fade_out_s)
        filters.append(f"fade=t=out:st={fade_start}:d={fade_out_s}")

    # Title overlay
    if title:
        escaped_title = title.replace("'", "\\'").replace(":", "\\:")
        title_end = min(title_duration_s, duration)
        filters.append(
            f"drawtext=text='{escaped_title}'"
            f":fontsize={font_size}"
            f":fontcolor={font_color}"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":enable='between(t,0,{title_end})'"
            f":box=1:boxcolor=black@{bg_opacity}:boxborderw=20"
        )

    filter_str = ",".join(filters)

    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(start_s), "-to", str(end_s),
        "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RenderError(f"Render failed: {result.stderr[:500]}")

    return {
        "output_path": output_path,
        "duration_s": round(duration, 3),
        "width": width,
        "height": height,
        "title": title,
        "size_bytes": os.path.getsize(output_path),
    }


def render_with_intro(
    input_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
    intro_text: str = "",
    intro_duration_s: float = 3.0,
    intro_color: str = "black",
    intro_font_size: int = 56,
    intro_font_color: str = "white",
    width: int = 1080,
    height: int = 1920,
) -> dict[str, Any]:
    """Render a clip with a color intro card.

    Strategy: Render intro + clip as separate files, then concat via demuxer.
    This avoids the ffmpeg filter_complex concat hang on older versions.
    """
    import tempfile
    import shutil

    if not os.path.isfile(input_path):
        raise RenderError(f"Input not found: {input_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="creator_intro_")
    try:
        intro_path = os.path.join(tmpdir, "intro.mp4")
        clip_path = os.path.join(tmpdir, "clip.mp4")

        escaped_text = intro_text.replace("'", "\\'").replace(":", "\\:")

        # Step 1: Render intro card (color + text)
        intro_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "lavfi", "-i", f"color=c={intro_color}:s={width}x{height}:d={intro_duration_s}:r=10",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
            "-t", str(intro_duration_s),
            "-vf", (
                f"drawtext=text='{escaped_text}'"
                f":fontsize={intro_font_size}:fontcolor={intro_font_color}"
                f":x=(w-text_w)/2:y=(h-text_h)/2"
            ),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "64k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            intro_path,
        ]
        r1 = subprocess.run(intro_cmd, capture_output=True, text=True, timeout=30)
        if r1.returncode != 0:
            raise RenderError(f"Intro render failed: {r1.stderr[:500]}")

        # Step 2: Render clip (scaled/cropped)
        clip_cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(start_s), "-to", str(end_s),
            "-i", input_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            clip_path,
        ]
        r2 = subprocess.run(clip_cmd, capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            raise RenderError(f"Clip render failed: {r2.stderr[:500]}")

        # Step 3: Concat via demuxer
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            f.write(f"file '{intro_path}'\nfile '{clip_path}'\n")

        concat_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        r3 = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=30)
        if r3.returncode != 0:
            raise RenderError(f"Concat failed: {r3.stderr[:500]}")

        clip_duration = end_s - start_s
        return {
            "output_path": output_path,
            "duration_s": round(intro_duration_s + clip_duration, 3),
            "width": width,
            "height": height,
            "intro_text": intro_text,
            "intro_duration_s": intro_duration_s,
            "size_bytes": os.path.getsize(output_path),
        }

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def render_from_template(
    template_name: str,
    input_path: str,
    output_path: str,
    start_s: float,
    end_s: float,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render using a named template with parameters.

    Template JSON defines which render function to call and default params.
    User params override template defaults.
    """
    tmpl = load_template(template_name)
    render_type = tmpl.get("render_type", "clip_with_title")
    defaults = tmpl.get("defaults", {})

    # Merge: template defaults < user params
    merged = {**defaults, **(params or {})}

    if render_type == "clip_with_title":
        return render_clip_with_title(
            input_path, output_path, start_s, end_s,
            title=merged.get("title", ""),
            font_size=merged.get("font_size", 48),
            font_color=merged.get("font_color", "white"),
            bg_opacity=merged.get("bg_opacity", 0.6),
            title_duration_s=merged.get("title_duration_s", 3.0),
            fade_in_s=merged.get("fade_in_s", 0.5),
            fade_out_s=merged.get("fade_out_s", 0.5),
            width=merged.get("width", 1080),
            height=merged.get("height", 1920),
        )
    elif render_type == "with_intro":
        return render_with_intro(
            input_path, output_path, start_s, end_s,
            intro_text=merged.get("intro_text", merged.get("title", "")),
            intro_duration_s=merged.get("intro_duration_s", 3.0),
            intro_color=merged.get("intro_color", "black"),
            intro_font_size=merged.get("intro_font_size", 56),
            intro_font_color=merged.get("intro_font_color", "white"),
            width=merged.get("width", 1080),
            height=merged.get("height", 1920),
        )
    else:
        raise RenderError(f"Unknown render_type: {render_type}")
