"""Data Platform — Analysis Pipeline.

Implements the 10-stage analysis run based on GPT-5.4 v2 architecture.
Agents are Control Plane only (A1, A1B, A9). Everything else is deterministic Engine.

Uses the existing creator_job.py Worker/Queue infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from data_platform.source_registry import (
    DATA_PLATFORM_DIR,
    execute_query,
    get_dataset_profile,
    guard_sql,
    _atomic_write_json,
    _safe_json,
)


# ---------------------------------------------------------------------------
# Run Management
# ---------------------------------------------------------------------------


def create_run(
    question: str,
    dataset_version_ids: list[str],
    mode: str = "single_agent",
    report_formats: list[str] | None = None,
    narration: bool = False,
    execution_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new analysis run."""
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    policy = execution_policy or {
        "memory_limit_mb": 2048,
        "cpu_threads": 4,
        "timeout_s": 60,
        "spill_limit_mb": 4096,
        "result_row_limit": 100000,
    }

    run = {
        "run_id": run_id,
        "question": question,
        "dataset_version_ids": dataset_version_ids,
        "mode": mode,
        "report_formats": report_formats or ["html"],
        "narration": narration,
        "execution_policy": policy,
        "status": "initialized",
        "current_stage": None,
        "stages": [],
        "created_at": now,
        "updated_at": now,
        "random_seed": 42,
        "timezone": "UTC",
    }

    # Persist
    run_dir = _run_dir(run_id)
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.join(run_dir, "stages"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "artifacts"), exist_ok=True)
    _save_run(run)

    return run


def get_run(run_id: str) -> dict[str, Any] | None:
    """Get a run by ID."""
    path = os.path.join(_run_dir(run_id), "run_manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def list_runs(status: str = "") -> list[dict[str, Any]]:
    """List all runs."""
    runs_dir = os.path.join(DATA_PLATFORM_DIR, "runs")
    if not os.path.isdir(runs_dir):
        return []
    results = []
    for entry in sorted(os.listdir(runs_dir), reverse=True):
        if not entry.startswith("run_"):
            continue
        run = get_run(entry)
        if run and (not status or run.get("status") == status):
            results.append(run)
    return results


def execute_run(run_id: str) -> dict[str, Any]:
    """Execute all stages of an analysis run sequentially.

    This is the main entry point — runs all 10 stages.
    """
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")

    run["status"] = "running"
    _save_run(run)

    stages = [
        ("A0_RUN_INIT", _stage_a0_run_init),
        ("A1_PLAN_REQUEST", _stage_a1_plan_request),
        ("A3_COMPILE_SQL", _stage_a3_compile_sql),
        ("A4_SQL_GUARD", _stage_a4_sql_guard),
        ("A5_EXECUTE", _stage_a5_execute),
        ("A6_VALIDATE_RESULTS", _stage_a6_validate_results),
        ("A7_BUILD_EVIDENCE", _stage_a7_build_evidence),
        ("A8_RENDER_ARTIFACTS", _stage_a8_render_artifacts),
        ("A10_PUBLISH_RUN", _stage_a10_publish_run),
    ]

    for stage_name, stage_fn in stages:
        run["current_stage"] = stage_name
        _save_run(run)

        stage_result = {
            "name": stage_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            output = stage_fn(run)
            stage_result["status"] = "completed"
            stage_result["completed_at"] = datetime.now(timezone.utc).isoformat()
            stage_result["output"] = output

            # Save stage checkpoint
            _atomic_write_json(
                os.path.join(_run_dir(run_id), "stages", f"{stage_name}.json"),
                stage_result,
            )
            run["stages"].append({"name": stage_name, "status": "completed"})

        except Exception as exc:
            stage_result["status"] = "failed"
            stage_result["error"] = str(exc)
            stage_result["completed_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_write_json(
                os.path.join(_run_dir(run_id), "stages", f"{stage_name}.json"),
                stage_result,
            )
            run["stages"].append({"name": stage_name, "status": "failed"})
            run["status"] = "failed"
            run["error"] = str(exc)
            _save_run(run)
            return run

    run["status"] = "completed"
    run["current_stage"] = None
    _save_run(run)
    return run


# ---------------------------------------------------------------------------
# Stage A0: RUN_INIT — Engine
# ---------------------------------------------------------------------------


def _stage_a0_run_init(run: dict[str, Any]) -> dict[str, Any]:
    """Freeze inputs, create environment snapshot."""
    import duckdb
    import sqlglot

    env = {
        "bridge_version": "dev",
        "python_version": _get_python_version(),
        "duckdb_version": duckdb.__version__,
        "sqlglot_version": sqlglot.__version__,
    }

    # Collect dataset profiles
    profiles = {}
    for dsv_id in run.get("dataset_version_ids", []):
        # Find dataset_id for this version
        from data_platform.source_registry import _dataset_id_from_version
        ds_id = _dataset_id_from_version(dsv_id)
        profile = get_dataset_profile(ds_id, dsv_id)
        if profile:
            profiles[dsv_id] = profile

    return {
        "environment": env,
        "pinned_dataset_versions": run.get("dataset_version_ids", []),
        "profiles": profiles,
        "random_seed": run.get("random_seed", 42),
        "execution_policy": run.get("execution_policy", {}),
    }


# ---------------------------------------------------------------------------
# Stage A1: PLAN_REQUEST — Agent Control Plane
# ---------------------------------------------------------------------------


def _stage_a1_plan_request(run: dict[str, Any]) -> dict[str, Any]:
    """Convert natural language question into an AnalysisSpec.

    In single_agent mode: deterministic SQL generation from question + profiles.
    In multi_agent mode: would delegate to agent (not implemented yet).
    """
    question = run.get("question", "")
    profiles = {}

    # Load profiles from A0
    a0_path = os.path.join(_run_dir(run["run_id"]), "stages", "A0_RUN_INIT.json")
    if os.path.isfile(a0_path):
        with open(a0_path) as f:
            a0 = json.load(f)
        profiles = a0.get("output", {}).get("profiles", {})

    # Build analysis spec
    # For MVP: deterministic SQL generation from question + column names
    all_tables = []
    all_columns = []
    for dsv_id, profile in profiles.items():
        from data_platform.source_registry import _dataset_id_from_version
        ds_id = _dataset_id_from_version(dsv_id)
        all_tables.append(ds_id)
        for col in profile.get("columns", []):
            all_columns.append(f"{ds_id}.{col['name']}")

    # Simple heuristic SQL generation
    # For a real implementation, this would call an LLM agent
    sql = _generate_sql_from_question(question, all_tables, profiles)

    analysis_spec = {
        "question": question,
        "datasets": all_tables,
        "generated_sql": sql,
        "columns_available": all_columns,
    }

    return analysis_spec


def _generate_sql_from_question(
    question: str,
    tables: list[str],
    profiles: dict[str, Any],
) -> str:
    """Generate SQL from a natural language question.

    MVP: Simple pattern matching. Production: LLM agent.
    """
    if not tables:
        return "SELECT 1 AS no_data"

    table = tables[0]
    q_lower = question.lower()

    # Get columns for the first table
    columns = []
    for dsv_id, profile in profiles.items():
        columns = [c["name"] for c in profile.get("columns", [])]
        break

    if not columns:
        return f"SELECT * FROM {table} LIMIT 10"

    # Pattern: count/how many
    if any(w in q_lower for w in ("count", "wie viele", "anzahl", "how many")):
        return f"SELECT COUNT(*) AS count FROM {table}"

    # Pattern: sum/total/umsatz
    if any(w in q_lower for w in ("sum", "total", "umsatz", "summe", "revenue")):
        numeric_cols = [c for c in columns if c.lower() in ("amount", "umsatz", "revenue", "total", "price", "value")]
        if numeric_cols:
            return f"SELECT SUM({numeric_cols[0]}) AS total FROM {table}"

    # Pattern: group by / per / pro / nach
    if any(w in q_lower for w in ("group", "per", "pro", "nach", "by")):
        # Find a categorical column
        cat_cols = [c for c in columns if c.lower() in ("region", "category", "type", "status", "channel", "product", "name")]
        numeric_cols = [c for c in columns if c.lower() in ("amount", "umsatz", "revenue", "total", "price", "value", "count")]
        if cat_cols and numeric_cols:
            return f"SELECT {cat_cols[0]}, SUM({numeric_cols[0]}) AS total FROM {table} GROUP BY {cat_cols[0]} ORDER BY total DESC"

    # Pattern: top/best/highest
    if any(w in q_lower for w in ("top", "best", "highest", "hoechst", "groesst")):
        return f"SELECT * FROM {table} ORDER BY {columns[-1]} DESC LIMIT 10"

    # Default: sample
    return f"SELECT * FROM {table} LIMIT 20"


# ---------------------------------------------------------------------------
# Stage A3: COMPILE_SQL — Engine
# ---------------------------------------------------------------------------


def _stage_a3_compile_sql(run: dict[str, Any]) -> dict[str, Any]:
    """Compile analysis spec into SQL bundle."""
    a1_path = os.path.join(_run_dir(run["run_id"]), "stages", "A1_PLAN_REQUEST.json")
    if not os.path.isfile(a1_path):
        raise RuntimeError("No plan found (A1 not completed)")

    with open(a1_path) as f:
        a1 = json.load(f)

    spec = a1.get("output", {})
    main_sql = spec.get("generated_sql", "")

    if not main_sql:
        raise RuntimeError("No SQL generated in plan")

    # Build validation queries
    tables = spec.get("datasets", [])
    validation_queries = []
    for table in tables:
        validation_queries.append(f"SELECT COUNT(*) AS row_count FROM {table}")

    sql_bundle = {
        "main_query": main_sql,
        "validation_queries": validation_queries,
    }

    return sql_bundle


# ---------------------------------------------------------------------------
# Stage A4: SQL_GUARD — Engine
# ---------------------------------------------------------------------------


def _stage_a4_sql_guard(run: dict[str, Any]) -> dict[str, Any]:
    """Guard SQL via SQLGlot."""
    a3_path = os.path.join(_run_dir(run["run_id"]), "stages", "A3_COMPILE_SQL.json")
    if not os.path.isfile(a3_path):
        raise RuntimeError("No SQL bundle found (A3 not completed)")

    with open(a3_path) as f:
        a3 = json.load(f)

    sql_bundle = a3.get("output", {})
    main_sql = sql_bundle.get("main_query", "")

    # Get allowed tables from A1
    a1_path = os.path.join(_run_dir(run["run_id"]), "stages", "A1_PLAN_REQUEST.json")
    allowed_tables = []
    if os.path.isfile(a1_path):
        with open(a1_path) as f:
            a1 = json.load(f)
        allowed_tables = a1.get("output", {}).get("datasets", [])

    # Guard main query
    guard_result = guard_sql(main_sql, allowed_tables)
    if guard_result["status"] != "approved":
        raise RuntimeError(f"SQL blocked: {guard_result.get('reason')}")

    # Guard validation queries
    for vq in sql_bundle.get("validation_queries", []):
        vr = guard_sql(vq, allowed_tables)
        if vr["status"] != "approved":
            raise RuntimeError(f"Validation SQL blocked: {vr.get('reason')}")

    return guard_result


# ---------------------------------------------------------------------------
# Stage A5: EXECUTE — Engine
# ---------------------------------------------------------------------------


def _stage_a5_execute(run: dict[str, Any]) -> dict[str, Any]:
    """Execute SQL against DuckDB in sandbox."""
    a3_path = os.path.join(_run_dir(run["run_id"]), "stages", "A3_COMPILE_SQL.json")
    with open(a3_path) as f:
        a3 = json.load(f)

    sql_bundle = a3.get("output", {})
    main_sql = sql_bundle.get("main_query", "")
    dsv_ids = run.get("dataset_version_ids", [])
    policy = run.get("execution_policy", {})

    start = time.monotonic()
    result = execute_query(
        main_sql,
        dsv_ids,
        timeout_s=policy.get("timeout_s", 60),
        result_row_limit=policy.get("result_row_limit", 100000),
    )
    elapsed = time.monotonic() - start

    # Execute validation queries
    validation_results = []
    for vq in sql_bundle.get("validation_queries", []):
        try:
            vr = execute_query(vq, dsv_ids, timeout_s=30)
            validation_results.append({"sql": vq, "result": vr, "status": "pass"})
        except Exception as exc:
            validation_results.append({"sql": vq, "error": str(exc), "status": "fail"})

    return {
        "main_result": result,
        "validation_results": validation_results,
        "wall_time_ms": round(elapsed * 1000),
        "rows_returned": result.get("row_count", 0),
    }


# ---------------------------------------------------------------------------
# Stage A6: VALIDATE_RESULTS — Engine
# ---------------------------------------------------------------------------


def _stage_a6_validate_results(run: dict[str, Any]) -> dict[str, Any]:
    """Validate execution results."""
    a5_path = os.path.join(_run_dir(run["run_id"]), "stages", "A5_EXECUTE.json")
    with open(a5_path) as f:
        a5 = json.load(f)

    exec_result = a5.get("output", {})
    main_result = exec_result.get("main_result", {})
    validation_results = exec_result.get("validation_results", [])

    checks = []

    # Check: non-empty result
    row_count = main_result.get("row_count", 0)
    checks.append({
        "name": "row_count_nonzero",
        "status": "pass" if row_count > 0 else "warn",
        "detail": f"{row_count} rows returned",
    })

    # Check: validation queries passed
    for vr in validation_results:
        checks.append({
            "name": f"validation_{vr.get('sql', '')[:40]}",
            "status": vr.get("status", "unknown"),
        })

    # Check: no truncation
    if main_result.get("truncated"):
        checks.append({
            "name": "result_not_truncated",
            "status": "warn",
            "detail": "Result was truncated at row limit",
        })

    blocking = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warn"]

    overall = "pass"
    if blocking:
        overall = "fail"
    elif warnings:
        overall = "warn"

    return {
        "status": overall,
        "checks": checks,
        "blocking_failures": [c["name"] for c in blocking],
        "warnings": [c.get("detail", c["name"]) for c in warnings],
    }


# ---------------------------------------------------------------------------
# Stage A7: BUILD_EVIDENCE — Engine
# ---------------------------------------------------------------------------


def _stage_a7_build_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Build Evidence Bundle from all stage outputs."""
    run_id = run["run_id"]
    stages_dir = os.path.join(_run_dir(run_id), "stages")

    # Load A5 and A6
    a5 = _load_stage(stages_dir, "A5_EXECUTE")
    a6 = _load_stage(stages_dir, "A6_VALIDATE_RESULTS")

    exec_output = a5.get("output", {})
    val_output = a6.get("output", {})

    evidence = {
        "run_id": run_id,
        "status": val_output.get("status", "unknown"),
        "data_basis": {
            "dataset_versions": run.get("dataset_version_ids", []),
            "rows_returned": exec_output.get("rows_returned", 0),
            "wall_time_ms": exec_output.get("wall_time_ms", 0),
        },
        "validation": {
            "checks": val_output.get("checks", []),
            "blocking_failures": val_output.get("blocking_failures", []),
            "warnings": val_output.get("warnings", []),
        },
        "assumptions": [],
        "limitations": [],
        "reproducibility": {
            "replayable": True,
            "run_id": run_id,
            "random_seed": run.get("random_seed", 42),
        },
    }

    # Save evidence
    evidence_path = os.path.join(_run_dir(run_id), "artifacts", "evidence.json")
    _atomic_write_json(evidence_path, evidence)

    return evidence


# ---------------------------------------------------------------------------
# Stage A8: RENDER_ARTIFACTS — Engine
# ---------------------------------------------------------------------------


def _stage_a8_render_artifacts(run: dict[str, Any]) -> dict[str, Any]:
    """Render report artifacts: Markdown, HTML, charts."""
    run_id = run["run_id"]
    artifacts_dir = os.path.join(_run_dir(run_id), "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # Load results
    a5 = _load_stage(os.path.join(_run_dir(run_id), "stages"), "A5_EXECUTE")
    a7 = _load_stage(os.path.join(_run_dir(run_id), "stages"), "A7_BUILD_EVIDENCE")

    exec_output = a5.get("output", {})
    evidence = a7.get("output", {})
    main_result = exec_output.get("main_result", {})

    # Build Markdown report
    md_lines = [
        f"# Analysis Report — {run_id}",
        "",
        f"**Question:** {run.get('question', '')}",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Results",
        "",
    ]

    # Table
    columns = main_result.get("columns", [])
    rows = main_result.get("rows", [])
    if columns and rows:
        md_lines.append("| " + " | ".join(columns) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows[:50]:
            md_lines.append("| " + " | ".join(str(v) for v in row) + " |")
        if len(rows) > 50:
            md_lines.append(f"\n*({len(rows)} total rows, showing first 50)*")

    md_lines.extend([
        "",
        "## Evidence",
        "",
        f"- **Status:** {evidence.get('status', 'unknown')}",
        f"- **Rows returned:** {evidence.get('data_basis', {}).get('rows_returned', 0)}",
        f"- **Wall time:** {evidence.get('data_basis', {}).get('wall_time_ms', 0)} ms",
        f"- **Reproducible:** {evidence.get('reproducibility', {}).get('replayable', False)}",
    ])

    warnings = evidence.get("validation", {}).get("warnings", [])
    if warnings:
        md_lines.append("")
        md_lines.append("### Warnings")
        for w in warnings:
            md_lines.append(f"- {w}")

    md_lines.extend([
        "",
        "---",
        f"*Generated by Bridge IDE Data Platform, Run {run_id}*",
    ])

    # Write Markdown
    md_content = "\n".join(md_lines)
    md_path = os.path.join(artifacts_dir, "report.md")
    with open(md_path, "w") as f:
        f.write(md_content)

    # Write HTML
    html_path = os.path.join(artifacts_dir, "report.html")
    html_content = _markdown_to_html(md_content, run.get("question", ""))
    with open(html_path, "w") as f:
        f.write(html_content)

    # Try chart generation
    chart_paths = []
    if columns and rows and len(columns) >= 2:
        try:
            chart_path = os.path.join(artifacts_dir, "chart.png")
            _render_chart(columns, rows, chart_path)
            chart_paths.append(chart_path)
        except Exception:
            pass

    artifacts = [
        {"kind": "markdown", "path": md_path},
        {"kind": "html", "path": html_path},
    ]
    for cp in chart_paths:
        artifacts.append({"kind": "chart", "path": cp})

    return {"artifacts": artifacts}


# ---------------------------------------------------------------------------
# Stage A10: PUBLISH_RUN — Engine
# ---------------------------------------------------------------------------


def _stage_a10_publish_run(run: dict[str, Any]) -> dict[str, Any]:
    """Finalize run, emit events."""
    run_id = run["run_id"]

    # Emit event to event bus if available
    try:
        from event_bus import emit
        emit("data.run.completed", {"run_id": run_id, "question": run.get("question", "")})
    except (ImportError, Exception):
        pass

    return {
        "run_id": run_id,
        "status": "completed",
        "artifact_refs": [
            f"runs/{run_id}/artifacts/report.html",
            f"runs/{run_id}/artifacts/evidence.json",
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_dir(run_id: str) -> str:
    return os.path.join(DATA_PLATFORM_DIR, "runs", run_id)


def _save_run(run: dict[str, Any]) -> None:
    run["updated_at"] = datetime.now(timezone.utc).isoformat()
    run_dir = _run_dir(run["run_id"])
    os.makedirs(run_dir, exist_ok=True)
    _atomic_write_json(os.path.join(run_dir, "run_manifest.json"), run)


def _load_stage(stages_dir: str, stage_name: str) -> dict[str, Any]:
    path = os.path.join(stages_dir, f"{stage_name}.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _get_python_version() -> str:
    import sys
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _markdown_to_html(md: str, title: str = "") -> str:
    """Simple Markdown to HTML conversion."""
    lines = md.split("\n")
    html_lines = [
        "<!DOCTYPE html>",
        "<html><head>",
        f"<title>{title or 'Analysis Report'}</title>",
        "<style>body{font-family:sans-serif;max-width:900px;margin:0 auto;padding:20px}",
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}",
        "th{background:#f5f5f5}h1{color:#333}h2{color:#555;border-bottom:1px solid #eee;padding-bottom:5px}</style>",
        "</head><body>",
    ]
    in_table = False
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("| ") and "---" in line:
            continue  # Skip table separator
        elif line.startswith("| "):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not in_table:
                html_lines.append("<table><thead><tr>")
                for c in cells:
                    html_lines.append(f"<th>{c}</th>")
                html_lines.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_lines.append("<tr>")
                for c in cells:
                    html_lines.append(f"<td>{c}</td>")
                html_lines.append("</tr>")
        elif in_table and not line.startswith("|"):
            html_lines.append("</tbody></table>")
            in_table = False
            html_lines.append(f"<p>{line}</p>" if line.strip() else "")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f"<p><strong>{line[2:-2]}</strong></p>")
        elif line.startswith("*") and line.endswith("*"):
            html_lines.append(f"<p><em>{line[1:-1]}</em></p>")
        elif line.strip():
            html_lines.append(f"<p>{line}</p>")

    if in_table:
        html_lines.append("</tbody></table>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def _render_chart(columns: list[str], rows: list[list], output_path: str) -> None:
    """Render a simple bar chart from query results."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if len(columns) < 2 or len(rows) < 1:
            return

        labels = [str(r[0]) for r in rows[:20]]
        values = [float(r[1]) if r[1] is not None else 0 for r in rows[:20]]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(labels, values)
        ax.set_xlabel(columns[1])
        ax.set_ylabel(columns[0])
        ax.set_title(f"{columns[1]} by {columns[0]}")
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()
    except ImportError:
        pass
