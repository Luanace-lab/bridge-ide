"""Creator Job Pipeline — Model, Persistence, Registry.

This module owns the creator job lifecycle:
- Job creation with unique IDs
- Atomic persistence to workspace directories
- Global registry for cross-workspace job enumeration
- Event logging (JSONL append-only)
- Interrupted job detection for resume
"""

from __future__ import annotations

import collections
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.environ.get(
    "BRIDGE_BASE_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)

_REGISTRY_PATH = os.path.join(BASE_DIR, "creator_job_registry.json")

VALID_JOB_TYPES = frozenset(
    {
        "local_ingest",
        "url_ingest",
        "transcribe",
        "analyze_content",
        "clip_export",
        "social_export",
        "package_social",
        "publish",
        "voiceover",
        "voice_clone",
        "embed_content",
    }
)

VALID_STATUSES = frozenset(
    {
        "queued",
        "running",
        "completed",
        "failed",
        "partial",
        "cancelled",
    }
)


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------


def create_job(
    job_type: str,
    source: dict[str, Any],
    workspace_dir: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new creator job dict (not yet persisted)."""
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"Invalid job_type: {job_type!r}. Must be one of {sorted(VALID_JOB_TYPES)}")

    now = datetime.now(timezone.utc).isoformat()
    job_id = f"cj_{uuid.uuid4().hex[:12]}"

    return {
        "job_id": job_id,
        "job_type": job_type,
        "source": dict(source) if source else {},
        "workspace_dir": workspace_dir,
        "created_at": now,
        "updated_at": now,
        "status": "queued",
        "stage": None,
        "stages": [],
        "progress_pct": 0,
        "error": None,
        "warnings": [],
        "artifacts": {},
        "metrics": {},
        "config": dict(config) if config else {},
        "resume_from_stage": None,
        "attempt_count": 0,
    }


def save_job(job: dict[str, Any]) -> None:
    """Atomically persist a job to its workspace directory.

    Creates the job directory structure if it does not exist:
        workspace_dir/creator_jobs/<job_id>/job.json
        workspace_dir/creator_jobs/<job_id>/artifacts/
        workspace_dir/creator_jobs/<job_id>/chunks/
    """
    job["updated_at"] = datetime.now(timezone.utc).isoformat()

    job_dir = _job_dir(job["workspace_dir"], job["job_id"])
    os.makedirs(job_dir, exist_ok=True)
    os.makedirs(os.path.join(job_dir, "artifacts"), exist_ok=True)
    os.makedirs(os.path.join(job_dir, "chunks"), exist_ok=True)

    job_path = os.path.join(job_dir, "job.json")
    _atomic_write_json(job_path, job)

    # Update registry
    _registry_set(job["job_id"], job["workspace_dir"])


def load_job(job_id: str, workspace_dir: str) -> dict[str, Any] | None:
    """Load a job from its workspace directory. Returns None if not found."""
    job_path = os.path.join(_job_dir(workspace_dir, job_id), "job.json")
    if not os.path.isfile(job_path):
        return None
    try:
        with open(job_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def list_jobs(
    workspace_dir: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List jobs, optionally filtered by workspace and/or status.

    If workspace_dir is given, scans that workspace directly.
    Otherwise uses the registry to find all known workspaces.
    """
    results: list[dict[str, Any]] = []

    if workspace_dir:
        workspaces = [workspace_dir]
    else:
        registry = _load_registry()
        workspaces = list(set(registry.values()))

    for ws in workspaces:
        jobs_root = os.path.join(ws, "creator_jobs")
        if not os.path.isdir(jobs_root):
            continue
        for entry in os.listdir(jobs_root):
            if not entry.startswith("cj_"):
                continue
            job = load_job(entry, ws)
            if job is None:
                continue
            if status and job.get("status") != status:
                continue
            results.append(job)

    results.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return results


def append_job_event(
    job_id: str,
    workspace_dir: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Append an event to the job's events.jsonl file."""
    job_dir = _job_dir(workspace_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "data": data or {},
    }

    events_path = os.path.join(job_dir, "events.jsonl")
    with open(events_path, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_job_events(job_id: str, workspace_dir: str) -> list[dict[str, Any]]:
    """Load all events for a job."""
    events_path = os.path.join(_job_dir(workspace_dir, job_id), "events.jsonl")
    if not os.path.isfile(events_path):
        return []
    events: list[dict[str, Any]] = []
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


# ---------------------------------------------------------------------------
# Interrupted job detection (for resume on startup)
# ---------------------------------------------------------------------------


def find_interrupted_jobs(workspace_dir: str) -> list[dict[str, Any]]:
    """Find jobs that were running when the process was interrupted.

    Returns jobs with status=running, with resume_from_stage set to the
    stage that was running (or the last completed stage + 1).
    """
    results: list[dict[str, Any]] = []
    jobs_root = os.path.join(workspace_dir, "creator_jobs")
    if not os.path.isdir(jobs_root):
        return results

    for entry in os.listdir(jobs_root):
        if not entry.startswith("cj_"):
            continue
        job = load_job(entry, workspace_dir)
        if job is None or job.get("status") != "running":
            continue

        # Determine resume point
        resume_stage = None
        stages = job.get("stages", [])
        for stage in stages:
            if stage.get("status") == "running":
                resume_stage = stage["name"]
                break

        if resume_stage is None and stages:
            # Find last completed, resume from next
            for stage in reversed(stages):
                if stage.get("status") == "completed":
                    idx = stages.index(stage)
                    if idx + 1 < len(stages):
                        resume_stage = stages[idx + 1]["name"]
                    break

        job["resume_from_stage"] = resume_stage
        results.append(job)

    return results


# ---------------------------------------------------------------------------
# Registry (job_id -> workspace_dir mapping)
# ---------------------------------------------------------------------------


def _load_registry() -> dict[str, str]:
    """Load the global job registry."""
    if not os.path.isfile(_REGISTRY_PATH):
        return {}
    try:
        with open(_REGISTRY_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry: dict[str, str]) -> None:
    """Atomically save the global job registry."""
    os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
    _atomic_write_json(_REGISTRY_PATH, registry)


def _registry_set(job_id: str, workspace_dir: str) -> None:
    """Add or update a job in the registry."""
    registry = _load_registry()
    registry[job_id] = workspace_dir
    _save_registry(registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_dir(workspace_dir: str, job_id: str) -> str:
    """Return the directory path for a job."""
    return os.path.join(workspace_dir, "creator_jobs", job_id)


def _atomic_write_json(path: str, data: Any) -> None:
    """Atomically write JSON to a file using tempfile + os.replace."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, path)
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------

# Maps job_type -> list of (stage_name, stage_function)
# Stage function signature: (job: dict) -> dict (artifacts)
_STAGE_REGISTRY: dict[str, list[tuple[str, Callable]]] = {}


def register_stages(
    job_type: str,
    stages: list[tuple[str, Callable]],
) -> None:
    """Register stage functions for a job type."""
    _STAGE_REGISTRY[job_type] = list(stages)


def get_stages(job_type: str) -> list[tuple[str, Callable]]:
    """Get registered stages for a job type."""
    return _STAGE_REGISTRY.get(job_type, [])


# ---------------------------------------------------------------------------
# Worker — Queue, Semaphore, Daemon Thread
# ---------------------------------------------------------------------------

_JOB_QUEUE: collections.deque[tuple[str, str]] = collections.deque()  # (job_id, workspace_dir)
_QUEUE_LOCK = threading.Lock()
_QUEUE_EVENT = threading.Event()  # signals new work available
_CANCEL_FLAGS: set[str] = set()
_CANCEL_LOCK = threading.Lock()

_JOB_SEMAPHORE: threading.Semaphore | None = None
_MAX_QUEUE_SIZE = 50
_WORKER_THREAD: threading.Thread | None = None
_WORKER_RUNNING = False


def _reset_worker_state() -> None:
    """Reset all worker state. For testing only."""
    global _JOB_SEMAPHORE, _WORKER_THREAD, _WORKER_RUNNING, _MAX_QUEUE_SIZE
    _WORKER_RUNNING = False
    _WORKER_THREAD = None
    _JOB_SEMAPHORE = None
    _MAX_QUEUE_SIZE = 50
    with _QUEUE_LOCK:
        _JOB_QUEUE.clear()
    with _CANCEL_LOCK:
        _CANCEL_FLAGS.clear()
    _QUEUE_EVENT.clear()
    _STAGE_REGISTRY.clear()


def start_worker(
    max_concurrent: int = 2,
    max_queue_size: int = 50,
) -> None:
    """Start the background worker thread."""
    global _JOB_SEMAPHORE, _WORKER_THREAD, _WORKER_RUNNING, _MAX_QUEUE_SIZE

    if _WORKER_RUNNING:
        return

    _JOB_SEMAPHORE = threading.Semaphore(max_concurrent)
    _MAX_QUEUE_SIZE = max_queue_size
    _WORKER_RUNNING = True

    _WORKER_THREAD = threading.Thread(target=_worker_loop, daemon=True, name="creator-job-worker")
    _WORKER_THREAD.start()


def stop_worker() -> None:
    """Stop the worker thread."""
    global _WORKER_RUNNING
    _WORKER_RUNNING = False
    _QUEUE_EVENT.set()  # wake the worker so it can exit


def submit_job(job_id: str, workspace_dir: str) -> bool:
    """Submit a job to the worker queue.

    Returns False if the queue is full.
    """
    with _QUEUE_LOCK:
        if len(_JOB_QUEUE) >= _MAX_QUEUE_SIZE:
            return False
        _JOB_QUEUE.append((job_id, workspace_dir))
    _QUEUE_EVENT.set()
    return True


def cancel_job(job_id: str) -> None:
    """Request cancellation of a running or queued job."""
    with _CANCEL_LOCK:
        _CANCEL_FLAGS.add(job_id)


def retry_job(job_id: str, workspace_dir: str) -> bool:
    """Retry a failed job from its failed stage.

    Resets the failed stage to 'queued', sets resume_from_stage,
    and re-enqueues the job.
    """
    job = load_job(job_id, workspace_dir)
    if job is None:
        return False
    if job["status"] not in ("failed", "partial"):
        return False

    # Find the failed stage, reset it
    for stage in job.get("stages", []):
        if stage["status"] == "failed":
            stage["status"] = "queued"
            stage["error"] = None
            stage["started_at"] = None
            stage["completed_at"] = None
            job["resume_from_stage"] = stage["name"]
            break

    job["status"] = "queued"
    job["error"] = None
    save_job(job)
    append_job_event(job_id, workspace_dir, "job_retry", {"resume_from": job.get("resume_from_stage")})
    return submit_job(job_id, workspace_dir)


def resume_job(job_id: str, workspace_dir: str) -> bool:
    """Resume a failed or interrupted job from the last completed stage.

    Similar to retry but determines resume point automatically.
    """
    job = load_job(job_id, workspace_dir)
    if job is None:
        return False

    # Find resume point
    resume_stage = None
    stages = job.get("stages", [])
    for i, stage in enumerate(stages):
        if stage["status"] in ("failed", "running", "queued"):
            resume_stage = stage["name"]
            if stage["status"] in ("failed", "running"):
                stage["status"] = "queued"
                stage["error"] = None
            break

    job["status"] = "queued"
    job["error"] = None
    job["resume_from_stage"] = resume_stage
    save_job(job)
    append_job_event(job_id, workspace_dir, "job_resume", {"resume_from": resume_stage})
    return submit_job(job_id, workspace_dir)


def _is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled."""
    with _CANCEL_LOCK:
        return job_id in _CANCEL_FLAGS


def _clear_cancel(job_id: str) -> None:
    """Clear the cancel flag for a job."""
    with _CANCEL_LOCK:
        _CANCEL_FLAGS.discard(job_id)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


def _worker_loop() -> None:
    """Main worker loop — runs in daemon thread."""
    while _WORKER_RUNNING:
        # Wait for work
        _QUEUE_EVENT.wait(timeout=1.0)
        _QUEUE_EVENT.clear()

        while _WORKER_RUNNING:
            # Dequeue
            item = None
            with _QUEUE_LOCK:
                if _JOB_QUEUE:
                    item = _JOB_QUEUE.popleft()
            if item is None:
                break

            job_id, workspace_dir = item

            # Check cancel before acquiring semaphore
            if _is_cancelled(job_id):
                job = load_job(job_id, workspace_dir)
                if job:
                    job["status"] = "cancelled"
                    save_job(job)
                    append_job_event(job_id, workspace_dir, "job_cancelled", {})
                _clear_cancel(job_id)
                continue

            # Acquire semaphore (backpressure)
            if _JOB_SEMAPHORE is not None:
                _JOB_SEMAPHORE.acquire()

            try:
                _execute_job(job_id, workspace_dir)
            finally:
                if _JOB_SEMAPHORE is not None:
                    _JOB_SEMAPHORE.release()
                _clear_cancel(job_id)


def _execute_job(job_id: str, workspace_dir: str) -> None:
    """Execute all stages of a job sequentially."""
    job = load_job(job_id, workspace_dir)
    if job is None:
        logger.error("Job %s not found in %s", job_id, workspace_dir)
        return

    stages = get_stages(job["job_type"])
    if not stages:
        logger.error("No stages registered for job type %s", job["job_type"])
        job["status"] = "failed"
        job["error"] = f"No stages registered for job type: {job['job_type']}"
        save_job(job)
        return

    job["stages"] = _normalize_stage_list(job.get("stages", []), stages)

    job["status"] = "running"
    job["attempt_count"] += 1
    save_job(job)
    append_job_event(job_id, workspace_dir, "job_started", {"attempt": job["attempt_count"]})

    resume_from = job.get("resume_from_stage")

    for i, (stage_name, stage_fn) in enumerate(stages):
        # Skip already completed stages (resume support)
        stage_info = job["stages"][i] if i < len(job["stages"]) else None
        if stage_info and stage_info["status"] == "completed":
            if resume_from is None or stage_name != resume_from:
                continue

        # Check cancel
        if _is_cancelled(job_id):
            job["status"] = "cancelled"
            save_job(job)
            append_job_event(job_id, workspace_dir, "job_cancelled", {"at_stage": stage_name})
            return

        # Execute stage
        _execute_stage(job, i, stage_name, stage_fn)

        # Check if stage failed
        if job["stages"][i]["status"] == "failed":
            job["status"] = "failed"
            job["error"] = job["stages"][i].get("error", "Unknown stage error")
            job["stage"] = stage_name
            save_job(job)
            append_job_event(job_id, workspace_dir, "job_failed", {"stage": stage_name, "error": job["error"]})
            _emit_event("creator.job.failed", {"job_id": job_id, "stage": stage_name, "error": job["error"]})
            return

        # Update progress
        job["progress_pct"] = int(((i + 1) / len(stages)) * 100)
        save_job(job)

    # All stages completed
    job["status"] = "completed"
    job["progress_pct"] = 100
    job["stage"] = None
    save_job(job)
    append_job_event(job_id, workspace_dir, "job_completed", {})
    _emit_event("creator.job.completed", {"job_id": job_id})


def _execute_stage(
    job: dict[str, Any],
    stage_index: int,
    stage_name: str,
    stage_fn: Callable,
) -> None:
    """Execute a single stage with error handling."""
    stage_info = job["stages"][stage_index]
    stage_info["status"] = "running"
    stage_info["started_at"] = datetime.now(timezone.utc).isoformat()
    job["stage"] = stage_name
    save_job(job)

    append_job_event(
        job["job_id"], job["workspace_dir"],
        "stage_started", {"stage": stage_name},
    )

    start_time = time.monotonic()
    try:
        result = stage_fn(job)
        elapsed = time.monotonic() - start_time

        stage_info["status"] = "completed"
        stage_info["completed_at"] = datetime.now(timezone.utc).isoformat()
        if isinstance(result, dict):
            stage_info["artifacts"] = result

        # Store artifacts in job-level dict too
        if isinstance(result, dict) and result:
            job["artifacts"][stage_name] = result

        append_job_event(
            job["job_id"], job["workspace_dir"],
            "stage_completed",
            {"stage": stage_name, "duration_s": round(elapsed, 3)},
        )

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        stage_info["status"] = "failed"
        stage_info["error"] = str(exc)
        stage_info["completed_at"] = datetime.now(timezone.utc).isoformat()

        append_job_event(
            job["job_id"], job["workspace_dir"],
            "stage_failed",
            {"stage": stage_name, "error": str(exc), "duration_s": round(elapsed, 3)},
        )

    save_job(job)


def _normalize_stage_list(
    persisted_stages: list[dict[str, Any]],
    registered_stages: list[tuple[str, Callable]],
) -> list[dict[str, Any]]:
    """Align persisted stage state to the current registered stage list.

    This prevents resume/retry from crashing when the persisted job file
    contains an incomplete or older stage list.
    """
    persisted_by_name = {}
    for stage in persisted_stages:
        name = stage.get("name")
        if isinstance(name, str) and name:
            persisted_by_name[name] = stage

    normalized: list[dict[str, Any]] = []
    for name, _ in registered_stages:
        existing = persisted_by_name.get(name)
        if existing:
            normalized.append({
                "name": name,
                "status": existing.get("status", "queued"),
                "started_at": existing.get("started_at"),
                "completed_at": existing.get("completed_at"),
                "error": existing.get("error"),
                "artifacts": existing.get("artifacts", {}) if isinstance(existing.get("artifacts", {}), dict) else {},
            })
        else:
            normalized.append({
                "name": name,
                "status": "queued",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "artifacts": {},
            })
    return normalized


# ---------------------------------------------------------------------------
# Event bus integration (optional, fire-and-forget)
# ---------------------------------------------------------------------------


def _emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """Emit an event to the Bridge event bus if available.

    Fire-and-forget: failures are logged but do not break the pipeline.
    """
    try:
        from event_bus import emit
        emit(event_type, payload)
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Event bus emit failed for %s: %s", event_type, exc)
