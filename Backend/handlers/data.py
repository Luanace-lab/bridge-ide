"""Data Platform HTTP route handler.

Handles /data/* endpoints for Source Registry, Ingestion, Datasets, Runs, Queries.
Follows the same pattern as handlers/creator.py — no imports from server.py.
"""

from __future__ import annotations

import os
from typing import Any


def handle_get(handler: Any, path: str) -> bool:
    """Handle GET requests for /data/* paths."""

    # GET /data/sources
    if path == "/data/sources":
        try:
            from data_platform.source_registry import list_sources
            sources = list_sources()
            handler._respond(200, {"items": sources, "count": len(sources)})
        except Exception as exc:
            handler._respond(500, {"error": f"list sources failed: {exc}"})
        return True

    # GET /data/datasets
    if path == "/data/datasets":
        try:
            from data_platform.source_registry import list_datasets
            datasets = list_datasets()
            handler._respond(200, {"items": datasets, "count": len(datasets)})
        except Exception as exc:
            handler._respond(500, {"error": f"list datasets failed: {exc}"})
        return True

    # GET /data/datasets/{dataset_id}
    if path.startswith("/data/datasets/") and "/profile" not in path:
        dataset_id = path.split("/data/datasets/")[1].strip("/")
        if not dataset_id:
            handler._respond(400, {"error": "dataset_id is required"})
            return True
        try:
            from data_platform.source_registry import list_datasets
            datasets = list_datasets()
            found = next((d for d in datasets if d.get("dataset_id") == dataset_id), None)
            if not found:
                handler._respond(404, {"error": f"Dataset {dataset_id} not found"})
                return True
            handler._respond(200, found)
        except Exception as exc:
            handler._respond(500, {"error": f"get dataset failed: {exc}"})
        return True

    # GET /data/datasets/{dataset_id}/profile
    if path.startswith("/data/datasets/") and path.endswith("/profile"):
        parts = path.split("/")
        dataset_id = parts[3] if len(parts) > 3 else ""
        if not dataset_id:
            handler._respond(400, {"error": "dataset_id is required"})
            return True
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        version_id = ""
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
            version_id = qs.get("version_id", [""])[0]
        try:
            from data_platform.source_registry import get_dataset_profile
            profile = get_dataset_profile(dataset_id, version_id)
            if not profile:
                handler._respond(404, {"error": f"Profile not found for {dataset_id}"})
                return True
            handler._respond(200, profile)
        except Exception as exc:
            handler._respond(500, {"error": f"get profile failed: {exc}"})
        return True

    # GET /data/runs
    if path == "/data/runs":
        try:
            from data_platform.analysis_pipeline import list_runs
            runs = list_runs()
            handler._respond(200, {"items": runs, "count": len(runs)})
        except Exception as exc:
            handler._respond(500, {"error": f"list runs failed: {exc}"})
        return True

    # GET /data/runs/{run_id}
    if path.startswith("/data/runs/") and "/evidence" not in path and "/artifacts" not in path:
        run_id = path.split("/data/runs/")[1].strip("/")
        if not run_id:
            handler._respond(400, {"error": "run_id is required"})
            return True
        try:
            from data_platform.analysis_pipeline import get_run
            run = get_run(run_id)
            if not run:
                handler._respond(404, {"error": f"Run {run_id} not found"})
                return True
            handler._respond(200, run)
        except Exception as exc:
            handler._respond(500, {"error": f"get run failed: {exc}"})
        return True

    # GET /data/runs/{run_id}/evidence
    if path.startswith("/data/runs/") and path.endswith("/evidence"):
        run_id = path.split("/data/runs/")[1].split("/evidence")[0]
        try:
            import json as _json
            from data_platform.analysis_pipeline import DATA_PLATFORM_DIR
            evidence_path = os.path.join(DATA_PLATFORM_DIR, "runs", run_id, "artifacts", "evidence.json")
            if not os.path.isfile(evidence_path):
                handler._respond(404, {"error": f"Evidence not found for run {run_id}"})
                return True
            with open(evidence_path) as f:
                handler._respond(200, _json.load(f))
        except Exception as exc:
            handler._respond(500, {"error": f"get evidence failed: {exc}"})
        return True

    # GET /data/runs/{run_id}/artifacts
    if path.startswith("/data/runs/") and path.endswith("/artifacts"):
        run_id = path.split("/data/runs/")[1].split("/artifacts")[0]
        try:
            from data_platform.analysis_pipeline import DATA_PLATFORM_DIR
            artifacts_dir = os.path.join(DATA_PLATFORM_DIR, "runs", run_id, "artifacts")
            if not os.path.isdir(artifacts_dir):
                handler._respond(404, {"error": f"Artifacts not found for run {run_id}"})
                return True
            items = [
                {"name": f, "path": os.path.join(artifacts_dir, f)}
                for f in sorted(os.listdir(artifacts_dir))
                if not f.startswith(".")
            ]
            handler._respond(200, {"items": items, "count": len(items)})
        except Exception as exc:
            handler._respond(500, {"error": f"list artifacts failed: {exc}"})
        return True

    # GET /data/sources/{source_id}
    if path.startswith("/data/sources/"):
        source_id = path.split("/data/sources/")[1].strip("/")
        if not source_id:
            handler._respond(400, {"error": "source_id is required"})
            return True
        try:
            from data_platform.source_registry import get_source
            source = get_source(source_id)
            if not source:
                handler._respond(404, {"error": f"Source {source_id} not found"})
                return True
            handler._respond(200, source)
        except Exception as exc:
            handler._respond(500, {"error": f"get source failed: {exc}"})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    """Handle POST requests for /data/* paths."""

    # POST /data/sources
    if path == "/data/sources":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        name = str(data.get("name", "")).strip()
        kind = str(data.get("kind", "")).strip()
        location = str(data.get("location", "")).strip()
        if not name or not kind or not location:
            handler._respond(400, {"error": "'name', 'kind', and 'location' are required"})
            return True
        try:
            from data_platform.source_registry import register_source
            source = register_source(
                name=name,
                kind=kind,
                location=location,
                ingestion_policy=data.get("ingestion_policy"),
            )
            handler._respond(201, {"source_id": source["source_id"], "status": "created"})
        except (ValueError, FileNotFoundError) as exc:
            handler._respond(400, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"register source failed: {exc}"})
        return True

    # POST /data/sources/{source_id}/ingest
    if path.startswith("/data/sources/") and path.endswith("/ingest"):
        source_id = path.split("/data/sources/")[1].split("/ingest")[0]
        data = handler._parse_json_body()
        if data is None:
            data = {}
        try:
            from data_platform.source_registry import ingest_source
            result = ingest_source(
                source_id,
                profile_mode=str(data.get("profile_mode", "fast")),
            )
            handler._respond(200, {
                "source_id": source_id,
                "dataset_id": result["dataset_id"],
                "dataset_version_id": result["dataset_version_id"],
                "row_count": result["row_count"],
                "reject_count": result["reject_count"],
                "status": "ingested",
            })
        except (ValueError, FileNotFoundError) as exc:
            handler._respond(400, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"ingestion failed: {exc}"})
        return True

    # POST /data/runs
    if path == "/data/runs":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        question = str(data.get("question", "")).strip()
        dataset_version_ids = data.get("dataset_version_ids", [])
        if not question or not dataset_version_ids:
            handler._respond(400, {"error": "'question' and 'dataset_version_ids' are required"})
            return True
        try:
            from data_platform.analysis_pipeline import create_run, execute_run
            import threading

            run = create_run(
                question=question,
                dataset_version_ids=dataset_version_ids,
                mode=str(data.get("mode", "single_agent")),
                report_formats=data.get("report_formats", ["html"]),
                narration=bool(data.get("narration", False)),
                execution_policy=data.get("execution_policy"),
            )

            # Execute in background thread
            def _bg_execute(rid: str) -> None:
                try:
                    execute_run(rid)
                except Exception:
                    pass

            t = threading.Thread(target=_bg_execute, args=(run["run_id"],), daemon=True)
            t.start()

            handler._respond(202, {"run_id": run["run_id"], "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"create run failed: {exc}"})
        return True

    # POST /data/runs/{run_id}/cancel
    if path.startswith("/data/runs/") and path.endswith("/cancel"):
        run_id = path.split("/data/runs/")[1].split("/cancel")[0]
        handler._respond(200, {"run_id": run_id, "status": "cancelling"})
        return True

    # POST /data/runs/{run_id}/retry
    if path.startswith("/data/runs/") and path.endswith("/retry"):
        run_id = path.split("/data/runs/")[1].split("/retry")[0]
        data = handler._parse_json_body() or {}
        try:
            from data_platform.analysis_pipeline import get_run, execute_run, create_run
            import threading

            old_run = get_run(run_id)
            if not old_run:
                handler._respond(404, {"error": f"Run {run_id} not found"})
                return True

            new_run = create_run(
                question=old_run.get("question", ""),
                dataset_version_ids=old_run.get("dataset_version_ids", []),
                mode=old_run.get("mode", "single_agent"),
                report_formats=old_run.get("report_formats", ["html"]),
                execution_policy=old_run.get("execution_policy"),
            )

            def _bg_execute(rid: str) -> None:
                try:
                    execute_run(rid)
                except Exception:
                    pass

            t = threading.Thread(target=_bg_execute, args=(new_run["run_id"],), daemon=True)
            t.start()

            handler._respond(202, {"run_id": new_run["run_id"], "retry_of": run_id, "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"retry failed: {exc}"})
        return True

    # POST /data/query/dry-run
    if path == "/data/query/dry-run":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        sql = str(data.get("sql", "")).strip()
        if not sql:
            handler._respond(400, {"error": "'sql' is required"})
            return True
        allowed_tables = data.get("allowed_tables", [])
        if not allowed_tables:
            # Auto-detect from datasets
            from data_platform.source_registry import list_datasets
            allowed_tables = [d["dataset_id"] for d in list_datasets()]
        try:
            from data_platform.source_registry import guard_sql
            result = guard_sql(sql, allowed_tables)
            handler._respond(200, result)
        except Exception as exc:
            handler._respond(500, {"error": f"dry-run failed: {exc}"})
        return True

    # POST /data/query
    if path == "/data/query":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        sql = str(data.get("sql", "")).strip()
        dataset_version_ids = data.get("dataset_version_ids", [])
        if not sql or not dataset_version_ids:
            handler._respond(400, {"error": "'sql' and 'dataset_version_ids' are required"})
            return True
        try:
            from data_platform.source_registry import execute_query
            result = execute_query(
                sql,
                dataset_version_ids,
                timeout_s=int(data.get("timeout_s", 60)),
                result_row_limit=int(data.get("result_row_limit", 100000)),
            )
            handler._respond(200, result)
        except (ValueError, FileNotFoundError) as exc:
            handler._respond(400, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"query failed: {exc}"})
        return True

    # DELETE /data/sources/{source_id} — handled via POST with _method=delete
    if path.startswith("/data/sources/") and not path.endswith("/ingest"):
        source_id = path.split("/data/sources/")[1].strip("/")
        data = handler._parse_json_body()
        if data and data.get("_method") == "delete":
            try:
                from data_platform.source_registry import delete_source
                ok = delete_source(source_id)
                if not ok:
                    handler._respond(404, {"error": f"Source {source_id} not found"})
                    return True
                handler._respond(200, {"ok": True, "deleted": source_id})
            except Exception as exc:
                handler._respond(500, {"error": f"delete failed: {exc}"})
            return True

    return False
