from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_BASE_DIR = os.path.join(BASE_DIR, "execution_runs")
_LOCK = threading.Lock()
AGENT_DIARY_SOURCE = "cli_session"
AGENT_DIARY_TOOL = "agent_diary"
_DIARY_TRANSCRIPT_MAX_LINES = 8
_DIARY_LIST_LIMIT = 5
_DIARY_STABLE_META_KEYS = {
    "run_kind",
    "workspace",
    "project_root",
    "instruction_path",
    "resume_id",
    "cli_identity_source",
}


def _safe_id(raw: str, *, fallback_prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", (raw or "").strip())[:120]
    if cleaned:
        return cleaned
    return f"{fallback_prefix}_{uuid.uuid4().hex[:10]}"


def _run_dir(run_id: str) -> str:
    return os.path.join(RUNS_BASE_DIR, _safe_id(run_id, fallback_prefix="run"))


def _run_file(run_id: str) -> str:
    return os.path.join(_run_dir(run_id), "run.json")


def _steps_file(run_id: str) -> str:
    return os.path.join(_run_dir(run_id), "steps.jsonl")


def _artifacts_dir(run_id: str) -> str:
    return os.path.join(_run_dir(run_id), "artifacts")


def _atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def _atomic_write_text(path: str, text: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact_ref(raw: dict[str, Any] | str) -> dict[str, Any]:
    ref: dict[str, Any]
    if isinstance(raw, str):
        ref = {"path": raw}
    else:
        ref = dict(raw)
    path = str(ref.get("path", "")).strip()
    if path:
        ref["path"] = path
        ref["exists"] = os.path.exists(path)
        if os.path.isfile(path):
            try:
                ref["size_bytes"] = os.path.getsize(path)
            except OSError:
                pass
    return ref


def _parse_utc(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_text_list(raw: Any, *, limit: int = _DIARY_LIST_LIMIT, max_chars: int = 220) -> list[str]:
    items: list[str] = []
    if isinstance(raw, str):
        source_items = [raw]
    elif isinstance(raw, list):
        source_items = raw
    else:
        source_items = []

    for item in source_items:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_transcript_excerpt(raw: str, *, max_lines: int = _DIARY_TRANSCRIPT_MAX_LINES, max_chars: int = 220) -> list[str]:
    lines: list[str] = []
    for line in str(raw or "").splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact:
            continue
        if len(compact) > max_chars:
            compact = compact[: max_chars - 3] + "..."
        lines.append(compact)
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _non_empty_str(raw: Any) -> str:
    return str(raw or "").strip()


def _stable_agent_diary_run_id(agent_id: str, session_id: str = "", workspace: str = "") -> str:
    anchor = _safe_id(session_id or workspace or agent_id, fallback_prefix="session")
    return _safe_id(f"agent_diary_{agent_id}_{anchor}", fallback_prefix="agent_diary")


def _merge_run_meta(existing: dict[str, Any], updates: dict[str, Any]) -> bool:
    changed = False
    merged_meta = dict(existing.get("meta", {}) or {})
    incoming_meta = updates.get("meta", {})
    diary_run = (
        merged_meta.get("run_kind") == "agent_diary"
        or (isinstance(incoming_meta, dict) and incoming_meta.get("run_kind") == "agent_diary")
    )

    for key in ("task_id", "agent_id", "engine", "session_id"):
        value = _non_empty_str(updates.get(key))
        if value and not _non_empty_str(existing.get(key)):
            existing[key] = value
            changed = True

    if isinstance(incoming_meta, dict):
        for key, raw_value in incoming_meta.items():
            if isinstance(raw_value, dict):
                clean_dict = {str(k): v for k, v in raw_value.items() if v not in (None, "", [], {})}
                if not clean_dict:
                    continue
                current = merged_meta.get(key)
                if not isinstance(current, dict):
                    current = {}
                next_value = dict(current)
                for sub_key, sub_value in clean_dict.items():
                    if next_value.get(sub_key) != sub_value:
                        next_value[sub_key] = sub_value
                        changed = True
                merged_meta[key] = next_value
                continue

            value = raw_value
            if isinstance(value, str):
                value = value.strip()
            if value in (None, "", [], {}):
                continue
            if diary_run and key in _DIARY_STABLE_META_KEYS:
                current = merged_meta.get(key)
                if current in (None, "", [], {}):
                    merged_meta[key] = value
                    changed = True
                continue
            if merged_meta.get(key) != value:
                merged_meta[key] = value
                changed = True

    if changed:
        existing["meta"] = merged_meta
    return changed


def ensure_run(
    run_id: str,
    *,
    source: str,
    tool_name: str,
    task_id: str = "",
    agent_id: str = "",
    engine: str = "",
    session_id: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_run_id = _safe_id(run_id, fallback_prefix="run")
    run_path = _run_file(safe_run_id)
    os.makedirs(_artifacts_dir(safe_run_id), exist_ok=True)
    with _LOCK:
        if os.path.exists(run_path):
            with open(run_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            updated = _merge_run_meta(
                payload,
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "engine": engine,
                    "session_id": session_id,
                    "meta": dict(meta or {}),
                },
            )
            if updated:
                _atomic_write_json(run_path, payload)
            return payload
        payload = {
            "run_id": safe_run_id,
            "source": source,
            "tool_name": tool_name,
            "task_id": task_id,
            "agent_id": agent_id,
            "engine": engine,
            "session_id": session_id,
            "created_at": _utc_now(),
            "meta": dict(meta or {}),
        }
        _atomic_write_json(run_path, payload)
        return payload


def append_cli_session_diary(
    *,
    agent_id: str,
    session_id: str = "",
    engine: str = "",
    workspace: str = "",
    project_root: str = "",
    instruction_path: str = "",
    resume_id: str = "",
    cli_identity_source: str = "",
    event_type: str = "snapshot",
    context_pct: int | None = None,
    agent_status: str = "",
    mode: str = "",
    activity_summary: str = "",
    task_titles: list[str] | None = None,
    message_previews: list[str] | None = None,
    transcript_text: str = "",
) -> dict[str, Any]:
    clean_agent_id = _non_empty_str(agent_id)
    if not clean_agent_id:
        raise ValueError("agent_id is required")

    run_id = _stable_agent_diary_run_id(clean_agent_id, session_id=session_id, workspace=workspace)
    transcript_lines = _normalize_transcript_excerpt(transcript_text)
    task_title_list = _normalize_text_list(task_titles)
    message_preview_list = _normalize_text_list(message_previews)
    clean_activity = _non_empty_str(activity_summary)
    clean_event = _non_empty_str(event_type) or "snapshot"
    artifact_refs: list[dict[str, Any]] = []

    ensure_run(
        run_id,
        source=AGENT_DIARY_SOURCE,
        tool_name=AGENT_DIARY_TOOL,
        agent_id=clean_agent_id,
        engine=_non_empty_str(engine),
        session_id=_non_empty_str(session_id),
        meta={
            "run_kind": "agent_diary",
            "workspace": _non_empty_str(workspace),
            "project_root": _non_empty_str(project_root),
            "instruction_path": _non_empty_str(instruction_path),
            "resume_id": _non_empty_str(resume_id),
            "cli_identity_source": _non_empty_str(cli_identity_source),
        },
    )

    if _non_empty_str(transcript_text):
        artifact_name = f"{int(time.time() * 1000)}_{_safe_id(clean_event, fallback_prefix='snapshot')}.log"
        artifact_path = os.path.join(_artifacts_dir(run_id), artifact_name)
        _atomic_write_text(artifact_path, transcript_text.rstrip("\n") + "\n")
        artifact_refs.append({"path": artifact_path, "kind": "cli_session_log"})

    summary_parts: list[str] = []
    if clean_activity:
        summary_parts.append(f"Aktivitaet: {clean_activity}")
    if task_title_list:
        summary_parts.append("Tasks: " + "; ".join(task_title_list[:3]))
    if message_preview_list:
        summary_parts.append("Nachrichten: " + "; ".join(message_preview_list[:2]))
    if transcript_lines:
        summary_parts.append("CLI: " + transcript_lines[-1])

    step = append_step(
        run_id,
        source=AGENT_DIARY_SOURCE,
        tool_name=AGENT_DIARY_TOOL,
        status=clean_event,
        agent_id=clean_agent_id,
        engine=_non_empty_str(engine),
        session_id=_non_empty_str(session_id),
        input_summary={
            "event_type": clean_event,
            "workspace": _non_empty_str(workspace),
            "instruction_path": _non_empty_str(instruction_path),
            "resume_id": _non_empty_str(resume_id),
            "context_pct": context_pct,
        },
        result_summary={
            "event_type": clean_event,
            "context_pct": context_pct,
            "agent_status": _non_empty_str(agent_status),
            "mode": _non_empty_str(mode),
            "activity_summary": clean_activity,
            "task_titles": task_title_list,
            "message_previews": message_preview_list,
            "transcript_lines": transcript_lines,
            "transcript_excerpt": "\n".join(transcript_lines),
            "diary_summary": ". ".join(summary_parts),
        },
        artifacts=artifact_refs,
    )
    return {
        "run_id": run_id,
        "step_id": step["step_id"],
        "context_bundle_id": f"{run_id}:{step['step_id']}",
        "artifact_path": artifact_refs[0]["path"] if artifact_refs else "",
    }


def build_agent_diary_bundle(
    *,
    agent_id: str,
    session_id: str = "",
    limit_runs: int = 10,
) -> dict[str, Any]:
    records = _collect_run_records(
        source=AGENT_DIARY_SOURCE,
        tool_name=AGENT_DIARY_TOOL,
        task_id="",
        agent_id=_non_empty_str(agent_id),
        status="",
    )
    if session_id:
        records = [record for record in records if _non_empty_str(record.get("session_id")) == _non_empty_str(session_id)]
    if not records:
        return {}

    latest_run: dict[str, Any] | None = None
    latest_step: dict[str, Any] | None = None
    latest_ts = ""
    for record in records[: max(1, int(limit_runs))]:
        payload = read_run(str(record.get("run_id", "")))
        for step in payload.get("steps", []):
            if not isinstance(step, dict):
                continue
            timestamp = _non_empty_str(step.get("timestamp"))
            if timestamp >= latest_ts:
                latest_ts = timestamp
                latest_run = payload.get("run", {})
                latest_step = step

    if latest_run is None:
        latest_run = read_run(str(records[0].get("run_id", ""))).get("run", {})
    meta = latest_run.get("meta", {}) if isinstance(latest_run, dict) else {}
    result_summary = latest_step.get("result_summary", {}) if isinstance(latest_step, dict) else {}
    transcript_lines = _normalize_text_list(result_summary.get("transcript_lines"), limit=_DIARY_TRANSCRIPT_MAX_LINES)
    transcript_excerpt = _non_empty_str(result_summary.get("transcript_excerpt"))
    if not transcript_lines and transcript_excerpt:
        transcript_lines = _normalize_transcript_excerpt(transcript_excerpt)

    run_id = _non_empty_str(latest_run.get("run_id"))
    step_id = _non_empty_str(latest_step.get("step_id")) if isinstance(latest_step, dict) else ""
    event_type = _non_empty_str(result_summary.get("event_type"))
    if not event_type and isinstance(latest_step, dict):
        event_type = _non_empty_str(latest_step.get("status"))

    return {
        "run_id": run_id,
        "step_id": step_id,
        "context_bundle_id": f"{run_id}:{step_id}" if run_id and step_id else run_id,
        "timestamp": latest_ts,
        "event_type": event_type,
        "agent_id": _non_empty_str(latest_run.get("agent_id")) or _non_empty_str(agent_id),
        "engine": _non_empty_str(latest_run.get("engine")),
        "session_id": _non_empty_str(latest_run.get("session_id")),
        "workspace": _non_empty_str(meta.get("workspace")),
        "project_root": _non_empty_str(meta.get("project_root")),
        "instruction_path": _non_empty_str(meta.get("instruction_path")),
        "resume_id": _non_empty_str(meta.get("resume_id")),
        "cli_identity_source": _non_empty_str(meta.get("cli_identity_source")),
        "agent_status": _non_empty_str(result_summary.get("agent_status")),
        "mode": _non_empty_str(result_summary.get("mode")),
        "context_pct": result_summary.get("context_pct"),
        "activity_summary": _non_empty_str(result_summary.get("activity_summary")),
        "task_titles": _normalize_text_list(result_summary.get("task_titles")),
        "message_previews": _normalize_text_list(result_summary.get("message_previews")),
        "transcript_lines": transcript_lines,
        "transcript_excerpt": transcript_excerpt or "\n".join(transcript_lines),
        "summary": _non_empty_str(result_summary.get("diary_summary")),
    }


def append_step(
    run_id: str,
    *,
    source: str,
    tool_name: str,
    status: str,
    task_id: str = "",
    agent_id: str = "",
    engine: str = "",
    session_id: str = "",
    input_summary: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any] | str] | None = None,
    error: str | None = None,
    error_class: str = "",
) -> dict[str, Any]:
    safe_run_id = _safe_id(run_id, fallback_prefix="run")
    ensure_run(
        safe_run_id,
        source=source,
        tool_name=tool_name,
        task_id=task_id,
        agent_id=agent_id,
        engine=engine,
        session_id=session_id,
    )
    step_id = f"step_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    entry = {
        "step_id": step_id,
        "run_id": safe_run_id,
        "timestamp": _utc_now(),
        "source": source,
        "tool_name": tool_name,
        "status": status,
        "task_id": task_id,
        "agent_id": agent_id,
        "engine": engine,
        "session_id": session_id,
        "input_summary": dict(input_summary or {}),
        "result_summary": dict(result_summary or {}),
        "artifacts": [_artifact_ref(item) for item in list(artifacts or [])],
        "error": error,
        "error_class": error_class,
    }
    with _LOCK:
        os.makedirs(_run_dir(safe_run_id), exist_ok=True)
        with open(_steps_file(safe_run_id), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _summarize_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    first_step_at = ""
    last_step_at = ""
    artifact_count = 0
    has_errors = False
    last_error = ""

    for step in steps:
        status = str(step.get("status", "")).strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

        timestamp = str(step.get("timestamp", "")).strip()
        if timestamp and (not first_step_at or timestamp < first_step_at):
            first_step_at = timestamp
        if timestamp and timestamp > last_step_at:
            last_step_at = timestamp

        artifacts = step.get("artifacts", [])
        if isinstance(artifacts, list):
            artifact_count += len(artifacts)

        raw_error = step.get("error")
        error_text = str(raw_error).strip() if raw_error not in (None, "") else ""
        if error_text:
            has_errors = True
            last_error = error_text

    last_status = str(steps[-1].get("status", "")).strip() if steps else ""

    return {
        "step_count": len(steps),
        "status_counts": status_counts,
        "first_step_at": first_step_at,
        "last_step_at": last_step_at,
        "last_status": last_status,
        "artifact_count": artifact_count,
        "has_errors": has_errors,
        "last_error": last_error,
    }


def read_run(run_id: str) -> dict[str, Any]:
    safe_run_id = _safe_id(run_id, fallback_prefix="run")
    run_path = _run_file(safe_run_id)
    steps_path = _steps_file(safe_run_id)
    if not os.path.exists(run_path):
        raise FileNotFoundError(run_path)
    with open(run_path, "r", encoding="utf-8") as handle:
        run_data = json.load(handle)
    steps: list[dict[str, Any]] = []
    if os.path.exists(steps_path):
        with open(steps_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                steps.append(json.loads(line))
    return {
        "run": run_data,
        "steps": steps,
        "summary": _summarize_steps(steps),
        "artifacts_dir": str(Path(_artifacts_dir(safe_run_id))),
    }


def _load_run_summary(
    entry: str,
    *,
    source: str,
    tool_name: str,
    task_id: str,
    agent_id: str,
    status: str,
) -> dict[str, Any] | None:
    run_path = _run_file(entry)
    if not os.path.isfile(run_path):
        return None
    try:
        with open(run_path, "r", encoding="utf-8") as handle:
            run_data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if source and run_data.get("source") != source:
        return None
    if tool_name and run_data.get("tool_name") != tool_name:
        return None
    if task_id and run_data.get("task_id") != task_id:
        return None
    if agent_id and run_data.get("agent_id") != agent_id:
        return None

    steps_path = _steps_file(entry)
    steps: list[dict[str, Any]] = []
    if os.path.isfile(steps_path):
        try:
            with open(steps_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        step = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    steps.append(step)
        except OSError:
            pass
    summary = _summarize_steps(steps)
    if status and summary.get("last_status") != status:
        return None

    return {
        "run_id": run_data.get("run_id", entry),
        "source": run_data.get("source", ""),
        "tool_name": run_data.get("tool_name", ""),
        "task_id": run_data.get("task_id", ""),
        "agent_id": run_data.get("agent_id", ""),
        "engine": run_data.get("engine", ""),
        "session_id": run_data.get("session_id", ""),
        "created_at": run_data.get("created_at", ""),
        "step_count": summary.get("step_count", 0),
        "last_status": summary.get("last_status", ""),
        "last_step_at": summary.get("last_step_at", ""),
        "artifact_count": summary.get("artifact_count", 0),
        "has_errors": summary.get("has_errors", False),
        "last_error": summary.get("last_error", ""),
        "meta": run_data.get("meta", {}),
    }


def _collect_run_records(
    *,
    source: str,
    tool_name: str,
    task_id: str,
    agent_id: str,
    status: str,
) -> list[dict[str, Any]]:
    if not os.path.isdir(RUNS_BASE_DIR):
        return []

    records: list[dict[str, Any]] = []
    for entry in os.listdir(RUNS_BASE_DIR):
        record = _load_run_summary(
            entry,
            source=source,
            tool_name=tool_name,
            task_id=task_id,
            agent_id=agent_id,
            status=status,
        )
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return records


def list_runs(
    *,
    limit: int = 50,
    source: str = "",
    tool_name: str = "",
    task_id: str = "",
    agent_id: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    """List execution runs ordered by creation time descending."""
    source = (source or "").strip()
    tool_name = (tool_name or "").strip()
    task_id = (task_id or "").strip()
    agent_id = (agent_id or "").strip()
    status = (status or "").strip()
    limit = max(1, min(int(limit), 500))
    return _collect_run_records(
        source=source,
        tool_name=tool_name,
        task_id=task_id,
        agent_id=agent_id,
        status=status,
    )[:limit]


def summarize_runs(
    *,
    source: str = "",
    tool_name: str = "",
    task_id: str = "",
    agent_id: str = "",
    status: str = "",
    recent_limit: int = 10,
) -> dict[str, Any]:
    """Return aggregated statistics for execution runs matching the given filters."""
    source = (source or "").strip()
    tool_name = (tool_name or "").strip()
    task_id = (task_id or "").strip()
    agent_id = (agent_id or "").strip()
    status = (status or "").strip()
    recent_limit = max(1, min(int(recent_limit), 50))
    records = _collect_run_records(
        source=source,
        tool_name=tool_name,
        task_id=task_id,
        agent_id=agent_id,
        status=status,
    )

    by_source: dict[str, int] = {}
    by_tool_name: dict[str, int] = {}
    by_agent_id: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total_steps = 0
    latest_created_at = ""
    latest_step_at = ""

    for record in records:
        source_key = str(record.get("source", "")) or "unknown"
        tool_key = str(record.get("tool_name", "")) or "unknown"
        agent_key = str(record.get("agent_id", "")) or "unknown"
        status_key = str(record.get("last_status", "")) or "no_steps"
        by_source[source_key] = by_source.get(source_key, 0) + 1
        by_tool_name[tool_key] = by_tool_name.get(tool_key, 0) + 1
        by_agent_id[agent_key] = by_agent_id.get(agent_key, 0) + 1
        by_status[status_key] = by_status.get(status_key, 0) + 1
        total_steps += int(record.get("step_count", 0) or 0)
        created_at = str(record.get("created_at", ""))
        last_step_at = str(record.get("last_step_at", ""))
        if created_at > latest_created_at:
            latest_created_at = created_at
        if last_step_at > latest_step_at:
            latest_step_at = last_step_at

    return {
        "filters": {
            "source": source,
            "tool_name": tool_name,
            "task_id": task_id,
            "agent_id": agent_id,
            "status": status,
        },
        "total_runs": len(records),
        "total_steps": total_steps,
        "by_source": by_source,
        "by_tool_name": by_tool_name,
        "by_agent_id": by_agent_id,
        "by_status": by_status,
        "latest_created_at": latest_created_at,
        "latest_step_at": latest_step_at,
        "recent_run_ids": [str(record.get("run_id", "")) for record in records[:recent_limit]],
    }


def metrics_runs(
    *,
    source: str = "",
    task_id: str = "",
    agent_id: str = "",
    window_hours: float = 24,
    recent_limit: int = 10,
) -> dict[str, Any]:
    """Return lightweight KPI metrics for recent execution runs."""
    window_hours = float(window_hours)
    if window_hours <= 0:
        raise ValueError("window_hours must be > 0")
    recent_limit = max(1, min(int(recent_limit), 50))

    records = _collect_run_records(
        source=(source or "").strip(),
        tool_name="",
        task_id=(task_id or "").strip(),
        agent_id=(agent_id or "").strip(),
        status="",
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    recent_records: list[dict[str, Any]] = []
    for record in records:
        created_at = _parse_utc(str(record.get("created_at", "")))
        if created_at is None or created_at < cutoff:
            continue
        recent_records.append(record)

    status_counts: dict[str, int] = {}
    runs_with_errors = 0
    total_steps = 0
    for record in recent_records:
        status = str(record.get("last_status", "")).strip() or "no_steps"
        status_counts[status] = status_counts.get(status, 0) + 1
        if bool(record.get("has_errors", False)):
            runs_with_errors += 1
        total_steps += int(record.get("step_count", 0) or 0)

    return {
        "filters": {
            "source": str(source or "").strip(),
            "task_id": str(task_id or "").strip(),
            "agent_id": str(agent_id or "").strip(),
            "window_hours": window_hours,
        },
        "total_runs": len(recent_records),
        "total_steps": total_steps,
        "pending_approval_runs": status_counts.get("pending_approval", 0),
        "completed_runs": status_counts.get("completed", 0),
        "error_runs": status_counts.get("error", 0),
        "runs_with_errors": runs_with_errors,
        "status_counts": status_counts,
        "recent_run_ids": [str(record.get("run_id", "")) for record in recent_records[:recent_limit]],
    }


def prune_runs(
    *,
    max_age_hours: float,
    keep_latest: int = 0,
    source: str = "",
    tool_name: str = "",
    task_id: str = "",
    agent_id: str = "",
    status: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Prune execution runs older than the given age threshold."""
    keep_latest = max(0, int(keep_latest))
    max_age_hours = float(max_age_hours)
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be > 0")

    records = _collect_run_records(
        source=(source or "").strip(),
        tool_name=(tool_name or "").strip(),
        task_id=(task_id or "").strip(),
        agent_id=(agent_id or "").strip(),
        status=(status or "").strip(),
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    candidates: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        if index < keep_latest:
            continue
        created_at = _parse_utc(str(record.get("created_at", "")))
        if created_at is None or created_at > cutoff:
            continue
        candidates.append(record)

    result: dict[str, Any] = {
        "filters": {
            "source": str(source or "").strip(),
            "tool_name": str(tool_name or "").strip(),
            "task_id": str(task_id or "").strip(),
            "agent_id": str(agent_id or "").strip(),
            "status": str(status or "").strip(),
        },
        "dry_run": bool(dry_run),
        "max_age_hours": max_age_hours,
        "keep_latest": keep_latest,
        "matched_runs": len(records),
        "candidate_runs": len(candidates),
        "candidate_run_ids": [str(record.get("run_id", "")) for record in candidates],
    }
    if dry_run:
        result["pruned_runs"] = 0
        return result

    pruned_run_ids: list[str] = []
    failed: list[dict[str, str]] = []
    with _LOCK:
        for record in candidates:
            run_id = str(record.get("run_id", "")).strip()
            if not run_id:
                continue
            try:
                shutil.rmtree(_run_dir(run_id))
                pruned_run_ids.append(run_id)
            except OSError as exc:
                failed.append({"run_id": run_id, "error": str(exc)})
    result["pruned_runs"] = len(pruned_run_ids)
    result["pruned_run_ids"] = pruned_run_ids
    result["failed_runs"] = failed
    return result
