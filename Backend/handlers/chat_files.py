"""Chat upload file-serving route extraction from server.py."""

from __future__ import annotations

import mimetypes
import os
import re
from typing import Any, Callable


_chat_uploads_dir_getter: Callable[[], str] | None = None
_is_within_directory: Callable[[str, str], bool] | None = None
_FILES_RE = re.compile(r"^/files/([^/]+)$")


def init(
    *,
    chat_uploads_dir_getter: Callable[[], str],
    is_within_directory_fn: Callable[[str, str], bool],
) -> None:
    global _chat_uploads_dir_getter, _is_within_directory
    _chat_uploads_dir_getter = chat_uploads_dir_getter
    _is_within_directory = is_within_directory_fn


def _chat_uploads_dir() -> str:
    if _chat_uploads_dir_getter is None:
        raise RuntimeError("handlers.chat_files.init() not called: chat_uploads_dir_getter missing")
    return _chat_uploads_dir_getter()


def _within_directory(path: str, base_dir: str) -> bool:
    if _is_within_directory is None:
        raise RuntimeError("handlers.chat_files.init() not called: is_within_directory_fn missing")
    return _is_within_directory(path, base_dir)


def handle_get(handler: Any, path: str) -> bool:
    match = _FILES_RE.match(path)
    if not match:
        return False

    filename = match.group(1)
    if not re.match(r"^[A-Za-z0-9._-]+$", filename):
        handler._respond(400, {"error": "invalid filename"})
        return True

    uploads_dir = _chat_uploads_dir()
    file_path = os.path.join(uploads_dir, filename)
    if not _within_directory(file_path, uploads_dir):
        handler._respond(403, {"error": "path traversal denied"})
        return True
    if not os.path.isfile(file_path):
        handler._respond(404, {"error": f"file not found: {filename}"})
        return True

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"
    try:
        with open(file_path, "rb") as handle:
            data = handle.read()
        handler.send_response(200)
        handler.send_header("Content-Type", mime_type)
        handler.send_header("Content-Length", str(len(data)))
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            handler.send_header("Content-Disposition", f'inline; filename="{filename}"')
        else:
            handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.send_header("Cache-Control", "public, max-age=3600")
        handler.end_headers()
        handler.wfile.write(data)
    except OSError:
        handler._respond(500, {"error": "failed to read file"})
    return True
