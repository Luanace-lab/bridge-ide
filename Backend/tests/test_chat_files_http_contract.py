from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestChatFilesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="chat_files_http_contract_")
        self._orig_uploads_dir = srv.CHAT_UPLOADS_DIR
        srv.CHAT_UPLOADS_DIR = self._tmpdir

    def tearDown(self) -> None:
        srv.CHAT_UPLOADS_DIR = self._orig_uploads_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_files_endpoint_serves_uploaded_file(self) -> None:
        base_url = self._start_server()
        file_path = os.path.join(self._tmpdir, "slice61.txt")
        with open(file_path, "wb") as handle:
            handle.write(b"slice61 file body")

        req = urllib.request.Request(f"{base_url}/files/slice61.txt", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertEqual(body, b"slice61 file body")
            self.assertEqual(resp.headers.get_content_type(), "text/plain")
            self.assertIn('attachment; filename="slice61.txt"', resp.headers.get("Content-Disposition", ""))

    def test_files_endpoint_rejects_missing_file(self) -> None:
        base_url = self._start_server()
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{base_url}/files/does-not-exist.txt", timeout=5)
        self.assertEqual(missing.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
