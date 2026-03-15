from __future__ import annotations

import io
import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.chat_files as files_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.response_code = None
        self.response_payload = None
        self.headers_sent: list[tuple[str, str]] = []
        self.sent_code = None
        self.ended = False
        self.wfile = io.BytesIO()

    def _respond(self, code: int, payload):
        self.response_code = code
        self.response_payload = payload

    def send_response(self, code: int) -> None:
        self.sent_code = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, value))

    def end_headers(self) -> None:
        self.ended = True


class TestChatFilesContract(unittest.TestCase):
    def test_server_uses_extracted_chat_files_get_handler(self) -> None:
        self.assertIs(srv._handle_chat_files_get, files_mod.handle_get)

    def test_chat_files_handler_returns_false_for_non_matching_route(self) -> None:
        dummy = _DummyHandler()
        self.assertFalse(files_mod.handle_get(dummy, "/not-files"))
        self.assertIsNone(dummy.response_code)


if __name__ == "__main__":
    unittest.main()
