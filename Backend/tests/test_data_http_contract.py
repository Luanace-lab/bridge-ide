from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import data_platform.analysis_pipeline as ap  # noqa: E402
import data_platform.source_registry as sr  # noqa: E402
import server as srv  # noqa: E402


class TestDataHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="data_http_contract_")
        self.csv_path = os.path.join(self.tmpdir, "sales.csv")
        with open(self.csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "region", "amount"])
            for i in range(9):
                writer.writerow([i, ["North", "South", "East"][i % 3], 100 + i])

        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self._orig_sr_dir = sr.DATA_PLATFORM_DIR
        self._orig_ap_dir = ap.DATA_PLATFORM_DIR
        platform_dir = os.path.join(self.tmpdir, "data_platform")
        sr.DATA_PLATFORM_DIR = platform_dir
        ap.DATA_PLATFORM_DIR = platform_dir

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        sr.DATA_PLATFORM_DIR = self._orig_sr_dir
        ap.DATA_PLATFORM_DIR = self._orig_ap_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_data_register_list_and_get_source(self) -> None:
        base_url = self._start_server()

        status_code, body = self._post(
            base_url,
            "/data/sources",
            {"name": "sales", "kind": "csv", "location": self.csv_path},
        )
        self.assertEqual(status_code, 201)
        source_id = body["source_id"]

        status_code, body = self._get(base_url, "/data/sources")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["source_id"], source_id)

        status_code, body = self._get(base_url, f"/data/sources/{source_id}")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["source_id"], source_id)
        self.assertEqual(body["kind"], "csv")

    def test_data_ingest_profile_and_query(self) -> None:
        base_url = self._start_server()

        _, body = self._post(
            base_url,
            "/data/sources",
            {"name": "sales", "kind": "csv", "location": self.csv_path},
        )
        source_id = body["source_id"]

        status_code, body = self._post(
            base_url,
            f"/data/sources/{source_id}/ingest",
            {"profile_mode": "full"},
        )
        self.assertEqual(status_code, 200)
        dataset_id = body["dataset_id"]
        version_id = body["dataset_version_id"]

        status_code, body = self._get(base_url, f"/data/datasets/{dataset_id}/profile?version_id={version_id}")
        self.assertEqual(status_code, 200)
        self.assertEqual(len(body["columns"]), 3)
        self.assertGreater(len(body["sample_rows"]), 0)

        status_code, body = self._post(
            base_url,
            "/data/query/dry-run",
            {
                "sql": f"SELECT region, SUM(amount) AS total FROM {dataset_id} GROUP BY region",
                "allowed_tables": [dataset_id],
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(body["status"], "approved")

        status_code, body = self._post(
            base_url,
            "/data/query",
            {
                "sql": f"SELECT region, SUM(amount) AS total FROM {dataset_id} GROUP BY region ORDER BY region",
                "dataset_version_ids": [version_id],
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(body["columns"], ["region", "total"])
        self.assertEqual(len(body["rows"]), 3)

    def test_data_run_creates_evidence_and_artifacts(self) -> None:
        base_url = self._start_server()

        _, body = self._post(
            base_url,
            "/data/sources",
            {"name": "sales", "kind": "csv", "location": self.csv_path},
        )
        source_id = body["source_id"]
        _, body = self._post(base_url, f"/data/sources/{source_id}/ingest", {"profile_mode": "fast"})
        version_id = body["dataset_version_id"]

        status_code, body = self._post(
            base_url,
            "/data/runs",
            {"question": "Umsatz pro Region", "dataset_version_ids": [version_id]},
        )
        self.assertEqual(status_code, 202)
        run_id = body["run_id"]

        final_body = None
        for _ in range(120):
            _, current = self._get(base_url, f"/data/runs/{run_id}")
            if current.get("status") in {"completed", "failed"}:
                final_body = current
                break
            time.sleep(0.1)
        self.assertIsNotNone(final_body)
        self.assertEqual(final_body["status"], "completed")

        status_code, body = self._get(base_url, f"/data/runs/{run_id}/evidence")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["status"], "pass")
        self.assertIn("reproducibility", body)

        status_code, body = self._get(base_url, f"/data/runs/{run_id}/artifacts")
        self.assertEqual(status_code, 200)
        self.assertGreaterEqual(body["count"], 3)


if __name__ == "__main__":
    unittest.main()
