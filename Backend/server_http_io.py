from __future__ import annotations

import json
import re
from typing import Any

_allowed_origins: set[str] = set()
_rate_limit_exempt: set[str] = set()
_rate_limits: dict[str, Any] = {}
_rate_limiter: Any = None


def init(
    *,
    allowed_origins: set[str],
    rate_limit_exempt: set[str],
    rate_limits: dict[str, Any],
    rate_limiter: Any,
) -> None:
    global _allowed_origins
    global _rate_limit_exempt
    global _rate_limits
    global _rate_limiter

    _allowed_origins = allowed_origins
    _rate_limit_exempt = rate_limit_exempt
    _rate_limits = rate_limits
    _rate_limiter = rate_limiter


def _check_rate_limit(self, path: str) -> bool:
    if path in _rate_limit_exempt:
        return True
    client_ip = self.client_address[0]
    key = f"{client_ip}:{path}"
    limit = _rate_limits.get(path, _rate_limits["default"])
    return _rate_limiter.check(key, limit)


def _send_cors_headers(self) -> None:
    origin = self.headers.get("Origin", "")
    if origin in _allowed_origins:
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Client, X-Bridge-Agent, X-Bridge-Token, Authorization")
    if self.headers.get("Access-Control-Request-Private-Network") == "true":
        self.send_header("Access-Control-Allow-Private-Network", "true")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("X-Frame-Options", "DENY")
    self.send_header("X-XSS-Protection", "1; mode=block")
    self.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:9111 http://localhost:9111 ws://127.0.0.1:9112 ws://localhost:9112; frame-ancestors 'none'",
    )


def _respond(self, code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self._send_cors_headers()
    self.end_headers()
    try:
        self.wfile.write(body)
    except BrokenPipeError:
        return


def _respond_bytes(self, code: int, content_type: str, body: bytes) -> None:
    self.send_response(code)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    if content_type.lower().startswith("text/html"):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
    self._send_cors_headers()
    self.end_headers()
    try:
        self.wfile.write(body)
    except BrokenPipeError:
        return


def _parse_json_body(self, max_bytes: int = 1_048_576) -> dict[str, Any] | None:
    raw_length = self.headers.get("Content-Length")
    if not raw_length:
        return None
    try:
        length = int(raw_length)
    except ValueError:
        return None
    if length <= 0 or length > max_bytes:
        return None
    raw = self.rfile.read(length)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_multipart(self) -> list[dict[str, Any]]:
    max_upload = 50 * 1024 * 1024
    content_type = self.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        return []
    boundary_match = re.search(r"boundary=([^\s;]+)", content_type)
    if not boundary_match:
        return []
    boundary = boundary_match.group(1).encode("utf-8")
    raw_length = self.headers.get("Content-Length")
    if not raw_length:
        return []
    try:
        length = int(raw_length)
    except ValueError:
        return []
    if length <= 0 or length > max_upload:
        return []
    body = self.rfile.read(length)
    parts: list[dict[str, Any]] = []
    delimiter = b"--" + boundary
    segments = body.split(delimiter)
    for segment in segments:
        if segment in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        if segment.startswith(b"--"):
            continue
        header_end = segment.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        header_block = segment[:header_end].decode("utf-8", errors="replace")
        data_block = segment[header_end + 4 :]
        if data_block.endswith(b"\r\n"):
            data_block = data_block[:-2]
        name = ""
        filename = ""
        name_match = re.search(r'name="([^"]*)"', header_block)
        if name_match:
            name = name_match.group(1)
        fname_match = re.search(r'filename="([^"]*)"', header_block)
        if fname_match:
            filename = fname_match.group(1)
        parts.append({"name": name, "filename": filename, "data": data_block})
    return parts
