"""Execution journal GET route extraction from server.py.

This module owns the read-only execution journal endpoints.
Write/prune/report endpoints remain outside this slice.
"""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qs


_is_management_agent: Callable[[str], bool] | None = None
_RUN_DETAIL_RE = re.compile(r"^/execution/runs/([A-Za-z0-9._-]+)$")


def init(*, is_management_agent_fn: Callable[[str], bool]) -> None:
    global _is_management_agent
    _is_management_agent = is_management_agent_fn


def _is_management(agent_id: str) -> bool:
    if _is_management_agent is None:
        raise RuntimeError("handlers.execution_routes.init() not called: is_management_agent_fn missing")
    return _is_management_agent(agent_id)


def handle_get(handler: Any, path: str, query_string: str) -> bool:
    if path == "/execution/summary":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        qs = parse_qs(query_string, keep_blank_values=False)
        source = qs.get("source", [""])[0]
        tool_name = qs.get("tool_name", [""])[0]
        task_id = qs.get("task_id", [""])[0]
        agent_id = qs.get("agent_id", [""])[0]
        status = qs.get("status", [""])[0]
        recent_limit = min(int(qs.get("recent_limit", ["10"])[0]), 50)
        if requesting_agent and not _is_management(requesting_agent):
            if not agent_id:
                handler._respond(403, {"error": "execution summary requires self agent_id filter or management access"})
                return True
            if agent_id != requesting_agent:
                handler._respond(403, {"error": "execution summary access is limited to own runs"})
                return True
        try:
            import execution_journal

            summary = execution_journal.summarize_runs(
                source=source,
                tool_name=tool_name,
                task_id=task_id,
                agent_id=agent_id,
                status=status,
                recent_limit=recent_limit,
            )
        except Exception as exc:
            handler._respond(500, {"error": f"failed to summarize execution runs: {exc}"})
            return True
        handler._respond(200, {"summary": summary})
        return True

    if path == "/execution/metrics":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        qs = parse_qs(query_string, keep_blank_values=False)
        source = qs.get("source", [""])[0]
        task_id = qs.get("task_id", [""])[0]
        agent_id = qs.get("agent_id", [""])[0]
        window_hours = float(qs.get("window_hours", ["24"])[0])
        recent_limit = min(int(qs.get("recent_limit", ["10"])[0]), 50)
        if requesting_agent and not _is_management(requesting_agent):
            if not agent_id:
                handler._respond(403, {"error": "execution metrics require self agent_id filter or management access"})
                return True
            if agent_id != requesting_agent:
                handler._respond(403, {"error": "execution metrics access is limited to own runs"})
                return True
        try:
            import execution_journal

            metrics = execution_journal.metrics_runs(
                source=source,
                task_id=task_id,
                agent_id=agent_id,
                window_hours=window_hours,
                recent_limit=recent_limit,
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"failed to compute execution metrics: {exc}"})
            return True
        handler._respond(200, {"metrics": metrics})
        return True

    if path == "/execution/runs":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        qs = parse_qs(query_string, keep_blank_values=False)
        limit = min(int(qs.get("limit", ["50"])[0]), 500)
        source = qs.get("source", [""])[0]
        tool_name = qs.get("tool_name", [""])[0]
        task_id = qs.get("task_id", [""])[0]
        agent_id = qs.get("agent_id", [""])[0]
        status = qs.get("status", [""])[0]
        if requesting_agent and not _is_management(requesting_agent):
            if not agent_id:
                handler._respond(403, {"error": "execution journal requires self agent_id filter or management access"})
                return True
            if agent_id != requesting_agent:
                handler._respond(403, {"error": "execution journal access is limited to own runs"})
                return True
        try:
            import execution_journal

            runs = execution_journal.list_runs(
                limit=limit,
                source=source,
                tool_name=tool_name,
                task_id=task_id,
                agent_id=agent_id,
                status=status,
            )
        except Exception as exc:
            handler._respond(500, {"error": f"failed to list execution runs: {exc}"})
            return True
        handler._respond(200, {"runs": runs, "count": len(runs)})
        return True

    run_match = _RUN_DETAIL_RE.match(path)
    if run_match:
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        run_id = run_match.group(1)
        try:
            import execution_journal

            payload = execution_journal.read_run(run_id)
        except FileNotFoundError:
            handler._respond(404, {"error": f"execution run '{run_id}' not found"})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"failed to read execution run: {exc}"})
            return True
        if requesting_agent and not _is_management(requesting_agent):
            run_agent = str(payload.get("run", {}).get("agent_id", "")).strip()
            if run_agent != requesting_agent:
                handler._respond(403, {"error": "execution journal access is limited to own runs"})
                return True
        handler._respond(200, payload)
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path == "/execution/runs/prune":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        if requesting_agent and not _is_management(requesting_agent):
            handler._respond(403, {"error": "execution prune admin-only (management level)"})
            return True

        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True

        raw_max_age = data.get("max_age_hours")
        if raw_max_age is None:
            handler._respond(400, {"error": "field 'max_age_hours' is required"})
            return True

        try:
            import execution_journal

            result = execution_journal.prune_runs(
                max_age_hours=float(raw_max_age),
                keep_latest=int(data.get("keep_latest", 0) or 0),
                source=str(data.get("source", "")).strip(),
                tool_name=str(data.get("tool_name", "")).strip(),
                task_id=str(data.get("task_id", "")).strip(),
                agent_id=str(data.get("agent_id", "")).strip(),
                status=str(data.get("status", "")).strip(),
                dry_run=bool(data.get("dry_run", True)),
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"failed to prune execution runs: {exc}"})
            return True

        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/guardrails/incident-bundle":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        if not agent_id:
            handler._respond(400, {"error": "field 'agent_id' is required"})
            return True
        if requesting_agent and not _is_management(requesting_agent) and requesting_agent != agent_id:
            handler._respond(403, {"error": "incident bundle access is limited to self or management"})
            return True
        tool_name = str(data.get("tool_name", "")).strip()
        action_text = str(data.get("action_text", "")).strip()
        source = str(data.get("source", "")).strip()
        task_id = str(data.get("task_id", "")).strip()
        status = str(data.get("status", "")).strip()
        violation_type = str(data.get("violation_type", "")).strip()
        recent_limit = min(int(data.get("recent_limit", 5) or 5), 20)
        try:
            import execution_journal
            import guardrails
            from datetime import datetime, timezone

            bundle = {
                "agent_id": agent_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "filters": {
                    "tool_name": tool_name,
                    "action_text": action_text,
                    "source": source,
                    "task_id": task_id,
                    "status": status,
                    "violation_type": violation_type,
                    "recent_limit": recent_limit,
                },
                "policy": guardrails.get_policy(agent_id),
                "evaluation": guardrails.evaluate_policy(
                    agent_id,
                    tool_name=tool_name,
                    action_text=action_text,
                ),
                "violations_summary": guardrails.summarize_violations(
                    agent_id=agent_id,
                    limit=500,
                    violation_type=violation_type,
                ),
                "recent_violations": guardrails.get_violations(
                    agent_id=agent_id,
                    limit=recent_limit,
                    violation_type=violation_type,
                ),
                "execution_summary": execution_journal.summarize_runs(
                    source=source,
                    task_id=task_id,
                    agent_id=agent_id,
                    status=status,
                    recent_limit=recent_limit,
                ),
                "recent_runs": execution_journal.list_runs(
                    limit=recent_limit,
                    source=source,
                    task_id=task_id,
                    agent_id=agent_id,
                    status=status,
                ),
            }
        except Exception as exc:
            handler._respond(500, {"error": f"failed to build incident bundle: {exc}"})
            return True
        handler._respond(200, {"ok": True, "bundle": bundle})
        return True

    if path == "/audit/export":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        if not agent_id:
            handler._respond(400, {"error": "field 'agent_id' is required"})
            return True
        if requesting_agent and not _is_management(requesting_agent) and requesting_agent != agent_id:
            handler._respond(403, {"error": "audit export access is limited to self or management"})
            return True
        source = str(data.get("source", "")).strip()
        task_id = str(data.get("task_id", "")).strip()
        status = str(data.get("status", "")).strip()
        violation_type = str(data.get("violation_type", "")).strip()
        recent_limit = min(int(data.get("recent_limit", 10) or 10), 50)
        try:
            import execution_journal
            import guardrails
            from datetime import datetime, timezone

            export_payload = {
                "schema_version": "bridge.audit_export.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "agent_id": agent_id,
                "filters": {
                    "source": source,
                    "task_id": task_id,
                    "status": status,
                    "violation_type": violation_type,
                    "recent_limit": recent_limit,
                },
                "guardrails": {
                    "policy": guardrails.get_policy(agent_id),
                    "summary": guardrails.summarize_violations(
                        agent_id=agent_id,
                        limit=500,
                        violation_type=violation_type,
                    ),
                    "recent_violations": guardrails.get_violations(
                        agent_id=agent_id,
                        limit=recent_limit,
                        violation_type=violation_type,
                    ),
                },
                "execution": {
                    "summary": execution_journal.summarize_runs(
                        source=source,
                        task_id=task_id,
                        agent_id=agent_id,
                        status=status,
                        recent_limit=recent_limit,
                    ),
                    "metrics": execution_journal.metrics_runs(
                        source=source,
                        task_id=task_id,
                        agent_id=agent_id,
                        window_hours=float(data.get("window_hours", 24) or 24),
                        recent_limit=recent_limit,
                    ),
                    "recent_runs": execution_journal.list_runs(
                        limit=recent_limit,
                        source=source,
                        task_id=task_id,
                        agent_id=agent_id,
                        status=status,
                    ),
                },
            }
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"failed to build audit export: {exc}"})
            return True
        handler._respond(200, {"ok": True, "export": export_payload})
        return True

    return False
