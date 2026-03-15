from __future__ import annotations

import os
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_frontend_serve as frontend_serve  # noqa: E402


class _DummyHandler:
    def __init__(self):
        self.response_code = None
        self.response_payload = None
        self.response_content_type = None
        self.response_body = None

    _serve_frontend_request = srv.BridgeHandler._serve_frontend_request

    def _respond(self, code, payload):
        self.response_code = code
        self.response_payload = payload

    def _respond_bytes(self, code, content_type, body):
        self.response_code = code
        self.response_content_type = content_type
        self.response_body = body


class TestServerFrontendServeContract(unittest.TestCase):
    def _restore(self, old_frontend_dir, old_getter, old_guard):
        frontend_serve.init(
            frontend_dir=old_frontend_dir,
            ui_session_token_getter=old_getter,
            is_within_directory=old_guard,
        )

    def test_server_reexports_frontend_serve_helpers(self):
        self.assertIs(srv._inject_ui_token, frontend_serve._inject_ui_token)
        self.assertIs(srv.BridgeHandler._serve_frontend_request, frontend_serve._serve_frontend_request)

    def test_root_serves_control_center_with_ui_token(self):
        old_frontend_dir = frontend_serve._frontend_dir
        old_getter = frontend_serve._ui_session_token_getter
        old_guard = frontend_serve._is_within_directory
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "control_center.html")
                with open(path, "wb") as handle:
                    handle.write(b"<html><head><title>Bridge</title></head><body>ok</body></html>")
                frontend_serve.init(
                    frontend_dir=tmp,
                    ui_session_token_getter=lambda: "ui-test-token",
                    is_within_directory=srv.is_within_directory,
                )
                handler = _DummyHandler()
                handled = srv.BridgeHandler._serve_frontend_request(handler, "/")
        finally:
            self._restore(old_frontend_dir, old_getter, old_guard)

        self.assertTrue(handled)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_content_type, "text/html; charset=utf-8")
        self.assertIn(b'window.__BRIDGE_UI_TOKEN="ui-test-token"', handler.response_body)

    def test_static_html_serves_with_injected_token(self):
        old_frontend_dir = frontend_serve._frontend_dir
        old_getter = frontend_serve._ui_session_token_getter
        old_guard = frontend_serve._is_within_directory
        try:
            with tempfile.TemporaryDirectory() as tmp:
                page = os.path.join(tmp, "buddy_landing.html")
                with open(page, "wb") as handle:
                    handle.write(b"<html><head></head><body>landing</body></html>")
                frontend_serve.init(
                    frontend_dir=tmp,
                    ui_session_token_getter=lambda: "ui-test-token",
                    is_within_directory=srv.is_within_directory,
                )
                handler = _DummyHandler()
                handled = srv.BridgeHandler._serve_frontend_request(handler, "/buddy_landing.html")
        finally:
            self._restore(old_frontend_dir, old_getter, old_guard)

        self.assertTrue(handled)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_content_type, "text/html; charset=utf-8")
        self.assertIn(b'window.__BRIDGE_UI_TOKEN="ui-test-token"', handler.response_body)

    def test_static_js_serves_without_html_rewrite(self):
        old_frontend_dir = frontend_serve._frontend_dir
        old_getter = frontend_serve._ui_session_token_getter
        old_guard = frontend_serve._is_within_directory
        try:
            with tempfile.TemporaryDirectory() as tmp:
                script = os.path.join(tmp, "bridge_runtime_urls.js")
                with open(script, "wb") as handle:
                    handle.write(b"console.log('bridge');")
                frontend_serve.init(
                    frontend_dir=tmp,
                    ui_session_token_getter=lambda: "ui-test-token",
                    is_within_directory=srv.is_within_directory,
                )
                handler = _DummyHandler()
                handled = srv.BridgeHandler._serve_frontend_request(handler, "/bridge_runtime_urls.js")
        finally:
            self._restore(old_frontend_dir, old_getter, old_guard)

        self.assertTrue(handled)
        self.assertEqual(handler.response_code, 200)
        self.assertEqual(handler.response_content_type, "application/javascript; charset=utf-8")
        self.assertEqual(handler.response_body, b"console.log('bridge');")

    def test_root_returns_404_when_control_center_is_missing(self):
        old_frontend_dir = frontend_serve._frontend_dir
        old_getter = frontend_serve._ui_session_token_getter
        old_guard = frontend_serve._is_within_directory
        try:
            with tempfile.TemporaryDirectory() as tmp:
                frontend_serve.init(
                    frontend_dir=tmp,
                    ui_session_token_getter=lambda: "ui-test-token",
                    is_within_directory=srv.is_within_directory,
                )
                handler = _DummyHandler()
                handled = srv.BridgeHandler._serve_frontend_request(handler, "/")
        finally:
            self._restore(old_frontend_dir, old_getter, old_guard)

        self.assertTrue(handled)
        self.assertEqual(handler.response_code, 404)
        self.assertEqual(handler.response_payload, {"error": "ui not found"})

    def test_static_path_outside_frontend_dir_is_rejected(self):
        old_frontend_dir = frontend_serve._frontend_dir
        old_getter = frontend_serve._ui_session_token_getter
        old_guard = frontend_serve._is_within_directory
        try:
            with tempfile.TemporaryDirectory() as tmp:
                secret = os.path.join(tmp, "..", "secret.js")
                with open(secret, "wb") as handle:
                    handle.write(b"secret")
                frontend_serve.init(
                    frontend_dir=tmp,
                    ui_session_token_getter=lambda: "ui-test-token",
                    is_within_directory=srv.is_within_directory,
                )
                handler = _DummyHandler()
                handled = srv.BridgeHandler._serve_frontend_request(handler, "/../secret.js")
        finally:
            self._restore(old_frontend_dir, old_getter, old_guard)

        self.assertFalse(handled)
        self.assertIsNone(handler.response_code)


if __name__ == "__main__":
    unittest.main()
