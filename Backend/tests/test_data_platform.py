"""Tests for data_platform — Source Registry, Ingestion, Profiling, SQL Guard, Query."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import unittest


class TestDataPlatformSourceRegistry(unittest.TestCase):
    """Test source registration, listing, deletion."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="dp_test_")
        import data_platform.source_registry as sr
        self._orig_dir = sr.DATA_PLATFORM_DIR
        sr.DATA_PLATFORM_DIR = os.path.join(self.tmpdir, "data_platform")

    def tearDown(self) -> None:
        import data_platform.source_registry as sr
        sr.DATA_PLATFORM_DIR = self._orig_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_csv(self, name: str = "test.csv", rows: int = 100) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "amount", "date"])
            for i in range(rows):
                writer.writerow([i, f"item_{i}", round(10.0 + i * 0.5, 2), f"2026-01-{(i % 28) + 1:02d}"])
        return path

    def test_register_source(self) -> None:
        from data_platform.source_registry import register_source
        csv_path = self._make_csv()
        src = register_source("test_data", "csv", csv_path)
        self.assertTrue(src["source_id"].startswith("src_"))
        self.assertEqual(src["kind"], "csv")
        self.assertEqual(src["name"], "test_data")

    def test_register_unsupported_kind_raises(self) -> None:
        from data_platform.source_registry import register_source
        with self.assertRaises(ValueError):
            register_source("bad", "xml", "/tmp/fake.xml")

    def test_register_nonexistent_file_raises(self) -> None:
        from data_platform.source_registry import register_source
        with self.assertRaises(FileNotFoundError):
            register_source("missing", "csv", "/nonexistent/data.csv")

    def test_list_sources(self) -> None:
        from data_platform.source_registry import register_source, list_sources
        csv1 = self._make_csv("a.csv")
        csv2 = self._make_csv("b.csv")
        register_source("data_a", "csv", csv1)
        register_source("data_b", "csv", csv2)
        sources = list_sources()
        self.assertEqual(len(sources), 2)

    def test_get_source(self) -> None:
        from data_platform.source_registry import register_source, get_source
        csv_path = self._make_csv()
        src = register_source("test", "csv", csv_path)
        loaded = get_source(src["source_id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["source_id"], src["source_id"])

    def test_delete_source(self) -> None:
        from data_platform.source_registry import register_source, delete_source, get_source
        csv_path = self._make_csv()
        src = register_source("test", "csv", csv_path)
        self.assertTrue(delete_source(src["source_id"]))
        self.assertIsNone(get_source(src["source_id"]))


class TestDataPlatformIngestion(unittest.TestCase):
    """Test ingestion: CSV → Parquet + Profiling."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="dp_ingest_")
        import data_platform.source_registry as sr
        self._orig_dir = sr.DATA_PLATFORM_DIR
        sr.DATA_PLATFORM_DIR = os.path.join(self.tmpdir, "data_platform")

    def tearDown(self) -> None:
        import data_platform.source_registry as sr
        sr.DATA_PLATFORM_DIR = self._orig_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_csv(self, rows: int = 100) -> str:
        path = os.path.join(self.tmpdir, "data.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "amount", "region"])
            for i in range(rows):
                writer.writerow([i, f"product_{i}", round(10.0 + i * 1.5, 2), ["North", "South", "East", "West"][i % 4]])
        return path

    def test_ingest_csv_creates_parquet(self) -> None:
        from data_platform.source_registry import register_source, ingest_source
        csv_path = self._make_csv()
        src = register_source("products", "csv", csv_path)
        result = ingest_source(src["source_id"])

        self.assertIn("dataset_id", result)
        self.assertIn("dataset_version_id", result)
        self.assertEqual(result["row_count"], 100)
        self.assertTrue(os.path.isfile(result["parquet_path"]))

    def test_ingest_profiles_columns(self) -> None:
        from data_platform.source_registry import register_source, ingest_source
        csv_path = self._make_csv()
        src = register_source("products", "csv", csv_path)
        result = ingest_source(src["source_id"])

        profile = result["profile"]
        self.assertIn("columns", profile)
        col_names = [c["name"] for c in profile["columns"]]
        self.assertIn("id", col_names)
        self.assertIn("name", col_names)
        self.assertIn("amount", col_names)
        self.assertIn("region", col_names)

    def test_ingest_creates_sample_rows(self) -> None:
        from data_platform.source_registry import register_source, ingest_source
        csv_path = self._make_csv()
        src = register_source("products", "csv", csv_path)
        result = ingest_source(src["source_id"])

        self.assertGreater(len(result["profile"]["sample_rows"]), 0)

    def test_ingest_json_source(self) -> None:
        from data_platform.source_registry import register_source, ingest_source
        json_path = os.path.join(self.tmpdir, "data.json")
        data = [{"id": i, "value": i * 10} for i in range(50)]
        with open(json_path, "w") as f:
            json.dump(data, f)

        src = register_source("json_data", "json", json_path)
        result = ingest_source(src["source_id"])
        self.assertEqual(result["row_count"], 50)

    def test_ingest_nonexistent_source_raises(self) -> None:
        from data_platform.source_registry import ingest_source
        with self.assertRaises(ValueError):
            ingest_source("src_nonexistent")

    def test_list_datasets_after_ingest(self) -> None:
        from data_platform.source_registry import register_source, ingest_source, list_datasets
        csv_path = self._make_csv()
        src = register_source("products", "csv", csv_path)
        ingest_source(src["source_id"])

        datasets = list_datasets()
        self.assertGreater(len(datasets), 0)
        self.assertIn("dataset_id", datasets[0])


class TestDataPlatformSQLGuard(unittest.TestCase):
    """Test SQL guard — block unsafe queries."""

    def test_select_approved(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql("SELECT * FROM orders", ["orders"])
        self.assertEqual(result["status"], "approved")

    def test_insert_blocked(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql("INSERT INTO orders VALUES (1, 'x')", ["orders"])
        self.assertEqual(result["status"], "blocked")

    def test_drop_blocked(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql("DROP TABLE orders", ["orders"])
        self.assertEqual(result["status"], "blocked")

    def test_unknown_table_blocked(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql("SELECT * FROM secret_data", ["orders"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("not allowed", result["reason"])

    def test_copy_blocked(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql("COPY orders TO '/tmp/stolen.csv'", ["orders"])
        self.assertEqual(result["status"], "blocked")

    def test_aggregate_approved(self) -> None:
        from data_platform.source_registry import guard_sql
        result = guard_sql(
            "SELECT region, SUM(amount) FROM products GROUP BY region",
            ["products"],
        )
        self.assertEqual(result["status"], "approved")


class TestDataPlatformQueryExecution(unittest.TestCase):
    """Test sandboxed query execution against ingested data."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="dp_query_")
        import data_platform.source_registry as sr
        self._orig_dir = sr.DATA_PLATFORM_DIR
        sr.DATA_PLATFORM_DIR = os.path.join(self.tmpdir, "data_platform")

    def tearDown(self) -> None:
        import data_platform.source_registry as sr
        sr.DATA_PLATFORM_DIR = self._orig_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ingest_csv(self, rows: int = 100) -> dict:
        from data_platform.source_registry import register_source, ingest_source
        csv_path = os.path.join(self.tmpdir, "query_data.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "product", "amount", "region"])
            for i in range(rows):
                writer.writerow([i, f"p_{i}", round(10 + i * 0.5, 2), ["N", "S", "E", "W"][i % 4]])
        src = register_source("query_test", "csv", csv_path)
        return ingest_source(src["source_id"])

    def test_simple_select(self) -> None:
        from data_platform.source_registry import execute_query
        ingest_result = self._ingest_csv()
        ds_id = ingest_result["dataset_id"]
        dsv_id = ingest_result["dataset_version_id"]

        result = execute_query(
            f"SELECT COUNT(*) AS cnt FROM {ds_id}",
            [dsv_id],
        )
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["rows"][0][0], 100)

    def test_aggregation_query(self) -> None:
        from data_platform.source_registry import execute_query
        ingest_result = self._ingest_csv()
        ds_id = ingest_result["dataset_id"]
        dsv_id = ingest_result["dataset_version_id"]

        result = execute_query(
            f"SELECT region, SUM(amount) AS total FROM {ds_id} GROUP BY region ORDER BY total DESC",
            [dsv_id],
        )
        self.assertEqual(result["row_count"], 4)  # N, S, E, W
        self.assertEqual(result["columns"], ["region", "total"])


if __name__ == "__main__":
    unittest.main()
