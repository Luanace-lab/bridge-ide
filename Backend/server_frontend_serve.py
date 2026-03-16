from __future__ import annotations

import os
from typing import Callable

_frontend_dir = ""
_ui_session_token_getter: Callable[[], str] = lambda: ""
_is_within_directory: Callable[[str, str], bool] = lambda path, base_dir: False

_STATIC_EXTS = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2"}
_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def init(
    *,
    frontend_dir: str,
    ui_session_token_getter: Callable[[], str],
    is_within_directory: Callable[[str, str], bool],
) -> None:
    global _frontend_dir
    global _ui_session_token_getter
    global _is_within_directory

    _frontend_dir = frontend_dir
    _ui_session_token_getter = ui_session_token_getter
    _is_within_directory = is_within_directory


def _inject_ui_token(body: bytes) -> bytes:
    """Inject the frontend UI session token into served HTML."""
    ui_session_token = _ui_session_token_getter()
    if not ui_session_token:
        return body
    inject = f'<script>window.__BRIDGE_UI_TOKEN="{ui_session_token}";</script>'.encode("utf-8")
    lower = body.lower()
    idx = lower.find(b"</head>")
    if idx != -1:
        return body[:idx] + inject + body[idx:]
    return inject + body


def _serve_frontend_request(self, path: str) -> bool:
    """Serve root UI and static frontend assets. Returns True when handled."""
    if path in {"/", "/ui"}:
        landing = os.path.join(_frontend_dir, "landing.html")
        if not os.path.exists(landing):
            self._respond(404, {"error": "ui not found"})
            return True
        with open(landing, "rb") as handle:
            body = handle.read()
        self._respond_bytes(200, "text/html; charset=utf-8", _inject_ui_token(body))
        return True

    ext = os.path.splitext(path)[1].lower()
    if ext not in _STATIC_EXTS:
        return False

    safe_name = path.lstrip("/")
    file_path = os.path.join(_frontend_dir, safe_name)
    if not (_is_within_directory(file_path, _frontend_dir) and os.path.isfile(file_path)):
        return False

    with open(file_path, "rb") as handle:
        body = handle.read()
    if ext == ".html":
        body = _inject_ui_token(body)
    content_type = _STATIC_MIME.get(ext, "application/octet-stream")
    self._respond_bytes(200, content_type, body)
    return True
