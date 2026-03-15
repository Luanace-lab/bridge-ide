from __future__ import annotations

import io
import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_http_io as http_io  # noqa: E402


class _DummyRateLimiter:
    def __init__(self):
        self.calls = []
        self.allow = True

    def check(self, key, limit):
        self.calls.append((key, limit))
        return self.allow


class _DummyHandler:
    def __init__(self):
        self.headers = {}
        self.client_address = ("127.0.0.1", 12345)
        self.response_code = None
        self.sent_headers: list[tuple[str, str]] = []
        self.ended = False
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO()

    _check_rate_limit = srv.BridgeHandler._check_rate_limit
    _send_cors_headers = srv.BridgeHandler._send_cors_headers
    _respond = srv.BridgeHandler._respond
    _respond_bytes = srv.BridgeHandler._respond_bytes
    _parse_json_body = srv.BridgeHandler._parse_json_body
    _parse_multipart = srv.BridgeHandler._parse_multipart

    def send_response(self, code):
        self.response_code = code

    def send_header(self, key, value):
        self.sent_headers.append((key, value))

    def end_headers(self):
        self.ended = True


class TestServerHttpIoContract(unittest.TestCase):
    def test_bridge_handler_reexports_extracted_http_helpers(self):
        self.assertIs(srv.BridgeHandler._check_rate_limit, http_io._check_rate_limit)
        self.assertIs(srv.BridgeHandler._send_cors_headers, http_io._send_cors_headers)
        self.assertIs(srv.BridgeHandler._respond, http_io._respond)
        self.assertIs(srv.BridgeHandler._respond_bytes, http_io._respond_bytes)
        self.assertIs(srv.BridgeHandler._parse_json_body, http_io._parse_json_body)
        self.assertIs(srv.BridgeHandler._parse_multipart, http_io._parse_multipart)

    def test_rate_limit_exempt_path_short_circuits(self):
        limiter = _DummyRateLimiter()
        old_exempt = set(srv.RATE_LIMIT_EXEMPT)
        old_limits = dict(srv.RATE_LIMITS)
        old_limiter = srv.RATE_LIMITER
        try:
            srv.RATE_LIMIT_EXEMPT.clear()
            srv.RATE_LIMIT_EXEMPT.add("/status")
            srv.RATE_LIMITS.clear()
            srv.RATE_LIMITS.update({"default": {"max": 1}})
            srv.RATE_LIMITER = limiter
            handler = _DummyHandler()
            allowed = srv.BridgeHandler._check_rate_limit(handler, "/status")
        finally:
            srv.RATE_LIMIT_EXEMPT.clear()
            srv.RATE_LIMIT_EXEMPT.update(old_exempt)
            srv.RATE_LIMITS.clear()
            srv.RATE_LIMITS.update(old_limits)
            srv.RATE_LIMITER = old_limiter

        self.assertTrue(allowed)
        self.assertEqual(limiter.calls, [])

    def test_send_cors_headers_emits_origin_and_private_network(self):
        handler = _DummyHandler()
        allowed_origin = next(iter(srv.ALLOWED_ORIGINS))
        handler.headers = {
            "Origin": allowed_origin,
            "Access-Control-Request-Private-Network": "true",
        }

        srv.BridgeHandler._send_cors_headers(handler)

        self.assertIn(("Access-Control-Allow-Origin", allowed_origin), handler.sent_headers)
        self.assertIn(("Access-Control-Allow-Private-Network", "true"), handler.sent_headers)

    def test_parse_json_body_reads_dict_payload(self):
        handler = _DummyHandler()
        raw = b'{"ok": true, "value": 1}'
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)

        data = srv.BridgeHandler._parse_json_body(handler)

        self.assertEqual(data, {"ok": True, "value": 1})

    def test_parse_multipart_reads_named_part(self):
        boundary = "slice41"
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="demo.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            "hello world\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        handler = _DummyHandler()
        handler.headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(payload)),
        }
        handler.rfile = io.BytesIO(payload)

        parts = srv.BridgeHandler._parse_multipart(handler)

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["name"], "file")
        self.assertEqual(parts[0]["filename"], "demo.txt")
        self.assertEqual(parts[0]["data"], b"hello world")

    def test_respond_writes_json_payload(self):
        handler = _DummyHandler()
        handler.headers = {}

        srv.BridgeHandler._respond(handler, 201, {"ok": True})

        self.assertEqual(handler.response_code, 201)
        self.assertTrue(handler.ended)
        self.assertIn(("Content-Type", "application/json; charset=utf-8"), handler.sent_headers)
        self.assertIn(b'"ok": true', handler.wfile.getvalue())
