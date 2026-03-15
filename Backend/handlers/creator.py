"""Creator HTTP route extraction from server.py.

This module owns the existing Creator HTTP endpoints so they can evolve
outside the server.py monolith without changing route semantics.

It intentionally does not import from server.
"""

from __future__ import annotations

import os
import threading
from typing import Any

_CREATOR_RUNTIME_LOCK = threading.Lock()
_CREATOR_RUNTIME_READY = False
_RECOVERED_INTERRUPTED_JOBS: set[tuple[str, str]] = set()


def _ensure_creator_runtime(workspace_dir: str = "") -> None:
    global _CREATOR_RUNTIME_READY

    import creator_job
    from creator_job_stages import (
        register_analysis_stages,
        register_embed_stages,
        register_ingest_stages,
        register_publish_stages,
        register_render_stages,
        register_voiceover_stages,
    )

    with _CREATOR_RUNTIME_LOCK:
        if not _CREATOR_RUNTIME_READY:
            register_ingest_stages()
            register_analysis_stages()
            register_publish_stages()
            register_voiceover_stages()
            register_embed_stages()
            register_render_stages()
            creator_job.start_worker()
            _CREATOR_RUNTIME_READY = True
        else:
            creator_job.start_worker()

        if workspace_dir:
            for job in creator_job.find_interrupted_jobs(workspace_dir):
                key = (workspace_dir, job["job_id"])
                if key in _RECOVERED_INTERRUPTED_JOBS:
                    continue
                creator_job.resume_job(job["job_id"], workspace_dir)
                _RECOVERED_INTERRUPTED_JOBS.add(key)


def handle_get(handler: Any, path: str) -> bool:
    if path == "/creator/social-presets":
        try:
            import creator_media

            presets = creator_media.list_social_presets()
        except Exception as exc:
            handler._respond(500, {"error": f"failed to list creator presets: {exc}"})
            return True
        handler._respond(200, {"presets": presets, "count": len(presets)})
        return True

    # GET /creator/jobs?workspace_dir=...&status=...
    if path == "/creator/jobs":
        workspace_dir = ""
        status = ""
        import urllib.parse as _up_jobs

        raw_path = getattr(handler, "path", "")
        if "?" in raw_path:
            qs = _up_jobs.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
            status = qs.get("status", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job

            jobs = creator_job.list_jobs(workspace_dir=workspace_dir, status=status or None)
            summaries = [
                {
                    "job_id": job.get("job_id"),
                    "job_type": job.get("job_type"),
                    "status": job.get("status"),
                    "stage": job.get("stage"),
                    "progress_pct": job.get("progress_pct"),
                    "error": job.get("error"),
                    "created_at": job.get("created_at"),
                    "updated_at": job.get("updated_at"),
                }
                for job in jobs
            ]
            handler._respond(200, {"jobs": summaries, "count": len(summaries)})
        except Exception as exc:
            handler._respond(500, {"error": f"failed to list jobs: {exc}"})
        return True

    # GET /creator/voices
    if path == "/creator/voices":
        try:
            from creator_fish_audio import list_voices
            voices = list_voices()
            handler._respond(200, {"voices": voices, "count": len(voices)})
        except Exception as exc:
            handler._respond(500, {"error": f"list voices failed: {exc}"})
        return True

    # GET /creator/library
    if path == "/creator/library":
        try:
            from creator_embeddings import list_embedded_videos
            workspace_dir = ""
            import urllib.parse as _up2
            raw_path = getattr(handler, "path", "")
            if "?" in raw_path:
                qs = _up2.parse_qs(raw_path.split("?", 1)[1])
                workspace_dir = qs.get("collection", ["creator_video_embeddings"])[0]
            videos = list_embedded_videos(workspace_dir or "creator_video_embeddings")
            handler._respond(200, {"videos": videos, "count": len(videos)})
        except Exception as exc:
            handler._respond(500, {"error": f"library failed: {exc}"})
        return True

    # GET /creator/setup/status
    if path == "/creator/setup/status":
        try:
            import creator_setup
            status = creator_setup.check_all()
            handler._respond(200, status)
        except Exception as exc:
            handler._respond(500, {"error": f"setup check failed: {exc}"})
        return True

    # GET /creator/setup/guide/{platform}
    if path.startswith("/creator/setup/guide/"):
        platform = path.split("/creator/setup/guide/")[1].strip("/")
        if not platform:
            handler._respond(400, {"error": "platform is required"})
            return True
        try:
            import creator_setup
            guide = creator_setup.get_oauth_guide(platform)
            handler._respond(200, {"platform": platform, "guide": guide})
        except Exception as exc:
            handler._respond(500, {"error": f"guide failed: {exc}"})
        return True

    # GET /creator/jobs/batch/{batch_id}?workspace_dir=...
    if path.startswith("/creator/jobs/batch/"):
        batch_id = path.split("/creator/jobs/batch/")[1].strip("/")
        if not batch_id:
            handler._respond(400, {"error": "batch_id is required"})
            return True
        workspace_dir = ""
        import urllib.parse as _up
        raw_path = getattr(handler, "path", "")
        if "?" in raw_path:
            qs = _up.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter is required"})
            return True
        try:
            import json as _json
            batch_path = os.path.join(workspace_dir, "creator_batches", f"{batch_id}.json")
            if not os.path.isfile(batch_path):
                handler._respond(404, {"error": f"Batch {batch_id} not found"})
                return True
            with open(batch_path) as f:
                batch_data = _json.load(f)
            import creator_job
            statuses = {"completed": 0, "failed": 0, "running": 0, "queued": 0, "other": 0}
            jobs = []
            for jid in batch_data.get("job_ids", []):
                job = creator_job.load_job(jid, workspace_dir)
                if job:
                    s = job.get("status", "unknown")
                    statuses[s] = statuses.get(s, 0) + 1
                    jobs.append({"job_id": jid, "status": s})
            handler._respond(200, {
                "batch_id": batch_id,
                "total": len(batch_data.get("job_ids", [])),
                **statuses,
                "jobs": jobs,
            })
        except Exception as exc:
            handler._respond(500, {"error": f"batch status failed: {exc}"})
        return True

    # GET /creator/campaigns?workspace_dir=...&status=...
    if path == "/creator/campaigns":
        workspace_dir = ""
        status = ""
        import urllib.parse as _up_campaigns

        raw_path = getattr(handler, "path", "")
        if "?" in raw_path:
            qs = _up_campaigns.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
            status = qs.get("status", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter is required"})
            return True
        try:
            import creator_campaign

            campaigns = creator_campaign.list_campaigns(workspace_dir, status or None)
            summaries = [
                {
                    "campaign_id": campaign.get("campaign_id"),
                    "title": campaign.get("title"),
                    "status": campaign.get("status"),
                    "owner": campaign.get("owner"),
                    "target_platforms": campaign.get("target_platforms", []),
                    "created_at": campaign.get("created_at"),
                    "updated_at": campaign.get("updated_at"),
                }
                for campaign in campaigns
            ]
            handler._respond(200, {"campaigns": summaries, "count": len(summaries)})
        except Exception as exc:
            handler._respond(500, {"error": f"failed to list campaigns: {exc}"})
        return True

    if path.startswith("/creator/campaigns/"):
        campaign_id = path.split("/creator/campaigns/")[1].strip("/")
        if not campaign_id:
            handler._respond(400, {"error": "campaign_id is required"})
            return True
        workspace_dir = ""
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter is required"})
            return True
        try:
            import creator_campaign

            campaign = creator_campaign.load_campaign(campaign_id, workspace_dir)
            if campaign is None:
                handler._respond(404, {"error": f"Campaign {campaign_id} not found"})
                return True
            handler._respond(200, campaign)
        except Exception as exc:
            handler._respond(500, {"error": f"failed to load campaign: {exc}"})
        return True

    # GET /creator/jobs/{job_id}?workspace_dir=...
    if path.startswith("/creator/jobs/") and "/events" not in path and "/batch/" not in path:
        job_id = path.split("/creator/jobs/")[1].strip("/")
        if not job_id:
            handler._respond(400, {"error": "job_id is required"})
            return True
        # Extract workspace_dir from the raw request path (handler.path has query string)
        workspace_dir = ""
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.load_job(job_id, workspace_dir)
            if job is None:
                handler._respond(404, {"error": f"Job {job_id} not found"})
                return True
            handler._respond(200, job)
        except Exception as exc:
            handler._respond(500, {"error": f"failed to load job: {exc}"})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    # --- Job-based endpoints (async, return 202) ---

    if path == "/creator/jobs/local-ingest":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input_path", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not input_path or not workspace_dir:
            handler._respond(400, {"error": "'input_path' and 'workspace_dir' are required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.create_job(
                job_type="local_ingest",
                source={"input_path": input_path},
                workspace_dir=workspace_dir,
                config={
                    "language": str(data.get("language", "de")).strip() or "de",
                    "model": str(data.get("model", "")).strip() or None,
                    "transcribe": bool(data.get("transcribe", True)),
                },
            )
            creator_job.save_job(job)
            creator_job.start_worker()
            ok = creator_job.submit_job(job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {
                "job_id": job["job_id"],
                "status": "queued",
                "status_url": f"/creator/jobs/{job['job_id']}?workspace_dir={workspace_dir}",
            })
        except Exception as exc:
            handler._respond(500, {"error": f"failed to create job: {exc}"})
        return True

    if path == "/creator/jobs/url-ingest":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        source_url = str(data.get("source_url", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not source_url or not workspace_dir:
            handler._respond(400, {"error": "'source_url' and 'workspace_dir' are required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.create_job(
                job_type="url_ingest",
                source={"source_url": source_url},
                workspace_dir=workspace_dir,
                config={
                    "language": str(data.get("language", "de")).strip() or "de",
                    "model": str(data.get("model", "")).strip() or None,
                    "transcribe": bool(data.get("transcribe", True)),
                },
            )
            creator_job.save_job(job)
            creator_job.start_worker()
            ok = creator_job.submit_job(job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {
                "job_id": job["job_id"],
                "status": "queued",
                "status_url": f"/creator/jobs/{job['job_id']}?workspace_dir={workspace_dir}",
            })
        except Exception as exc:
            handler._respond(500, {"error": f"failed to create job: {exc}"})
        return True

    # --- Voiceover + Voice Clone endpoints ---

    if path == "/creator/jobs/voiceover":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.create_job(
                job_type="voiceover",
                source={"video_path": str(data.get("video_path", "")).strip()},
                workspace_dir=workspace_dir,
                config={
                    "text": str(data.get("text", "")).strip(),
                    "voice_id": str(data.get("voice_id", "")).strip(),
                },
            )
            creator_job.save_job(job)
            creator_job.start_worker()
            ok = creator_job.submit_job(job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {"job_id": job["job_id"], "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"voiceover job failed: {exc}"})
        return True

    if path == "/creator/jobs/voice-clone":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.create_job(
                job_type="voice_clone",
                source={"audio_path": str(data.get("audio_path", "")).strip()},
                workspace_dir=workspace_dir,
                config={"voice_name": str(data.get("voice_name", "")).strip()},
            )
            creator_job.save_job(job)
            creator_job.start_worker()
            ok = creator_job.submit_job(job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {"job_id": job["job_id"], "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"voice clone job failed: {exc}"})
        return True

    # --- Embed + Search endpoints ---

    if path == "/creator/jobs/embed":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            job = creator_job.create_job(
                job_type="embed_content",
                source={"video_path": str(data.get("video_path", "")).strip()},
                workspace_dir=workspace_dir,
                config={
                    "chunk_duration_s": int(data.get("chunk_duration_s", 120)),
                    "collection": str(data.get("collection", "creator_video_embeddings")),
                },
            )
            creator_job.save_job(job)
            creator_job.start_worker()
            ok = creator_job.submit_job(job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {"job_id": job["job_id"], "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"embed job failed: {exc}"})
        return True

    if path == "/creator/search":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        query = str(data.get("query", "")).strip()
        if not query:
            handler._respond(400, {"error": "'query' is required"})
            return True
        try:
            from creator_embeddings import search
            collection = str(data.get("collection", "creator_video_embeddings"))
            top_k = int(data.get("top_k", 5))
            results = search(collection, query, top_k)
            handler._respond(200, {"query": query, "results": results, "count": len(results)})
        except (RuntimeError, ImportError, FileNotFoundError, ValueError) as exc:
            handler._respond(400, {"error": f"search failed: {exc}"})
        except Exception as exc:
            handler._respond(500, {"error": f"search failed: {exc}"})
        return True

    # --- Batch endpoints ---

    if path == "/creator/jobs/batch-ingest":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        sources = data.get("sources", [])
        if not workspace_dir or not isinstance(sources, list) or not sources:
            handler._respond(400, {"error": "'workspace_dir' and non-empty 'sources' list are required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            import uuid
            creator_job.start_worker()

            batch_id = f"batch_{uuid.uuid4().hex[:12]}"
            job_ids = []
            for src in sources:
                input_path = str(src.get("input_path", "")).strip()
                source_url = str(src.get("source_url", "")).strip()
                job_type = "url_ingest" if source_url else "local_ingest"
                source_data = {"source_url": source_url} if source_url else {"input_path": input_path}
                job = creator_job.create_job(
                    job_type=job_type,
                    source=source_data,
                    workspace_dir=workspace_dir,
                    config={
                        "language": str(data.get("language", "de")).strip() or "de",
                        "transcribe": bool(data.get("transcribe", True)),
                    },
                )
                creator_job.save_job(job)
                creator_job.submit_job(job["job_id"], workspace_dir)
                job_ids.append(job["job_id"])

            # Save batch file
            import json as _json
            batch_dir = os.path.join(workspace_dir, "creator_batches")
            os.makedirs(batch_dir, exist_ok=True)
            with open(os.path.join(batch_dir, f"{batch_id}.json"), "w") as f:
                _json.dump({"batch_id": batch_id, "job_ids": job_ids}, f)

            handler._respond(202, {"batch_id": batch_id, "job_ids": job_ids, "count": len(job_ids)})
        except Exception as exc:
            handler._respond(500, {"error": f"batch ingest failed: {exc}"})
        return True

    if path == "/creator/jobs/publish-batch":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        publishes = data.get("publishes", [])
        if not workspace_dir or not isinstance(publishes, list) or not publishes:
            handler._respond(400, {"error": "'workspace_dir' and non-empty 'publishes' list are required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            import uuid
            creator_job.start_worker()

            batch_id = f"batch_{uuid.uuid4().hex[:12]}"
            job_ids = []
            for pub in publishes:
                pub_job = creator_job.create_job(
                    job_type="publish",
                    source={
                        "source_job_id": str(pub.get("source_job_id", "")).strip(),
                        "clip_path": str(pub.get("clip_path", "")).strip(),
                    },
                    workspace_dir=workspace_dir,
                    config={"channels": pub.get("channels", [])},
                )
                creator_job.save_job(pub_job)
                creator_job.submit_job(pub_job["job_id"], workspace_dir)
                job_ids.append(pub_job["job_id"])

            import json as _json
            batch_dir = os.path.join(workspace_dir, "creator_batches")
            os.makedirs(batch_dir, exist_ok=True)
            with open(os.path.join(batch_dir, f"{batch_id}.json"), "w") as f:
                _json.dump({"batch_id": batch_id, "job_ids": job_ids}, f)

            handler._respond(202, {"batch_id": batch_id, "job_ids": job_ids, "count": len(job_ids)})
        except Exception as exc:
            handler._respond(500, {"error": f"batch publish failed: {exc}"})
        return True

    # --- Campaign endpoints ---

    if path == "/creator/campaigns":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        title = str(data.get("title", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not title or not workspace_dir:
            handler._respond(400, {"error": "'title' and 'workspace_dir' are required"})
            return True
        try:
            import creator_campaign
            camp = creator_campaign.create_campaign(
                title=title,
                goal=str(data.get("goal", "")).strip(),
                workspace_dir=workspace_dir,
                owner=str(data.get("owner", "")).strip(),
                target_platforms=data.get("target_platforms"),
                target_audience=str(data.get("target_audience", "")).strip(),
            )
            creator_campaign.save_campaign(camp)
            handler._respond(201, {
                "campaign_id": camp["campaign_id"],
                "status": camp["status"],
            })
        except Exception as exc:
            handler._respond(500, {"error": f"failed to create campaign: {exc}"})
        return True

    if path.startswith("/creator/campaigns/") and path.endswith("/approve"):
        campaign_id = path.split("/creator/campaigns/")[1].split("/approve")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            import creator_campaign
            camp = creator_campaign.load_campaign(campaign_id, workspace_dir)
            if camp is None:
                handler._respond(404, {"error": f"Campaign {campaign_id} not found"})
                return True
            creator_campaign.approve_campaign(camp)
            creator_campaign.save_campaign(camp)
            creator_campaign.append_campaign_event(campaign_id, workspace_dir, "approved", {})
            handler._respond(200, {"ok": True, "campaign_id": campaign_id, "status": camp["status"]})
        except Exception as exc:
            handler._respond(500, {"error": f"approve failed: {exc}"})
        return True

    if path.startswith("/creator/campaigns/") and path.endswith("/metrics/import"):
        campaign_id = path.split("/creator/campaigns/")[1].split("/metrics/import")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            import creator_campaign
            camp = creator_campaign.load_campaign(campaign_id, workspace_dir)
            if camp is None:
                handler._respond(404, {"error": f"Campaign {campaign_id} not found"})
                return True
            creator_campaign.import_performance_snapshot(
                camp,
                channel=str(data.get("channel", "")).strip(),
                metrics=data.get("metrics", {}),
                period=str(data.get("period", "")).strip(),
            )
            creator_campaign.save_campaign(camp)
            handler._respond(200, {"ok": True, "snapshots": len(camp["performance_snapshots"])})
        except Exception as exc:
            handler._respond(500, {"error": f"metrics import failed: {exc}"})
        return True

    if path.startswith("/creator/campaigns/") and path.endswith("/plan"):
        campaign_id = path.split("/creator/campaigns/")[1].split("/plan")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            import creator_campaign
            camp = creator_campaign.load_campaign(campaign_id, workspace_dir)
            if camp is None:
                handler._respond(404, {"error": f"Campaign {campaign_id} not found"})
                return True
            creator_campaign.set_publish_plan(camp, data.get("plan", []))
            creator_campaign.save_campaign(camp)
            handler._respond(200, {"ok": True, "campaign_id": campaign_id, "status": camp["status"]})
        except Exception as exc:
            handler._respond(500, {"error": f"plan failed: {exc}"})
        return True

    # --- Job publish endpoint ---

    if path == "/creator/jobs/publish":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            pub_job = creator_job.create_job(
                job_type="publish",
                source={
                    "source_job_id": str(data.get("source_job_id", "")).strip(),
                    "clip_path": str(data.get("clip_path", "")).strip(),
                },
                workspace_dir=workspace_dir,
                config={
                    "channels": data.get("channels", []),
                },
            )
            creator_job.save_job(pub_job)
            creator_job.start_worker()
            ok = creator_job.submit_job(pub_job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {
                "job_id": pub_job["job_id"],
                "status": "queued",
                "status_url": f"/creator/jobs/{pub_job['job_id']}?workspace_dir={workspace_dir}",
            })
        except Exception as exc:
            handler._respond(500, {"error": f"failed to create publish job: {exc}"})
        return True

    # --- Job analyze endpoint ---

    if path == "/creator/jobs/analyze":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        job_id = str(data.get("job_id", "")).strip()
        if not job_id:
            job_id = str(data.get("source_job_id", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not job_id or not workspace_dir:
            handler._respond(400, {"error": "'job_id' and 'workspace_dir' are required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job

            # Load existing job to get transcript
            source_job = creator_job.load_job(job_id, workspace_dir)
            if source_job is None:
                handler._respond(404, {"error": f"Job {job_id} not found"})
                return True

            # Create analysis job referencing the source job's artifacts
            analysis_job = creator_job.create_job(
                job_type="analyze_content",
                source={"source_job_id": job_id},
                workspace_dir=workspace_dir,
                config=data.get("config", {}),
            )
            # Copy transcript artifacts from source job
            transcript = source_job.get("artifacts", {}).get("transcript_merge", {})
            if transcript:
                analysis_job["artifacts"]["transcript_merge"] = transcript

            creator_job.save_job(analysis_job)
            creator_job.start_worker()
            ok = creator_job.submit_job(analysis_job["job_id"], workspace_dir)
            if not ok:
                handler._respond(429, {"error": "Job queue is full"})
                return True
            handler._respond(202, {
                "job_id": analysis_job["job_id"],
                "status": "queued",
                "status_url": f"/creator/jobs/{analysis_job['job_id']}?workspace_dir={workspace_dir}",
            })
        except Exception as exc:
            handler._respond(500, {"error": f"failed to create analysis job: {exc}"})
        return True

    # --- Job lifecycle endpoints ---

    # POST /creator/jobs/{job_id}/retry
    if path.startswith("/creator/jobs/") and path.endswith("/retry"):
        job_id = path.split("/creator/jobs/")[1].split("/retry")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            ok = creator_job.retry_job(job_id, workspace_dir)
            if not ok:
                handler._respond(404, {"error": f"Job {job_id} not found or not in failed state"})
                return True
            handler._respond(200, {"ok": True, "job_id": job_id, "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"retry failed: {exc}"})
        return True

    # POST /creator/jobs/{job_id}/cancel
    if path.startswith("/creator/jobs/") and path.endswith("/cancel"):
        job_id = path.split("/creator/jobs/")[1].split("/cancel")[0]
        try:
            import creator_job
            creator_job.cancel_job(job_id)
            handler._respond(200, {"ok": True, "job_id": job_id, "status": "cancelling"})
        except Exception as exc:
            handler._respond(500, {"error": f"cancel failed: {exc}"})
        return True

    # POST /creator/jobs/{job_id}/resume
    if path.startswith("/creator/jobs/") and path.endswith("/resume"):
        job_id = path.split("/creator/jobs/")[1].split("/resume")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' is required"})
            return True
        try:
            _ensure_creator_runtime(workspace_dir)
            import creator_job
            ok = creator_job.resume_job(job_id, workspace_dir)
            if not ok:
                handler._respond(404, {"error": f"Job {job_id} not found"})
                return True
            handler._respond(200, {"ok": True, "job_id": job_id, "status": "queued"})
        except Exception as exc:
            handler._respond(500, {"error": f"resume failed: {exc}"})
        return True

    # --- Legacy synchronous endpoints ---

    if path == "/creator/local-ingest":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input_path", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not input_path or not workspace_dir:
            handler._respond(400, {"error": "'input_path' and 'workspace_dir' are required"})
            return True
        try:
            import creator_media

            result = creator_media.ingest_local_media(
                input_path,
                workspace_dir,
                language=str(data.get("language", "de")).strip() or "de",
                model=(str(data.get("model", "")).strip() or None),
                transcribe=bool(data.get("transcribe", True)),
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"creator ingest failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/creator/url-ingest":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        source_url = str(data.get("source_url", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not source_url or not workspace_dir:
            handler._respond(400, {"error": "'source_url' and 'workspace_dir' are required"})
            return True
        try:
            import creator_media

            result = creator_media.ingest_url_media(
                source_url,
                workspace_dir,
                language=str(data.get("language", "de")).strip() or "de",
                model=(str(data.get("model", "")).strip() or None),
                transcribe=bool(data.get("transcribe", True)),
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"creator url ingest failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/creator/write-srt":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        output_path = str(data.get("output_path", "")).strip()
        segments = data.get("segments")
        if not output_path or not isinstance(segments, list):
            handler._respond(400, {"error": "'output_path' and list 'segments' are required"})
            return True
        try:
            import creator_media

            result = creator_media.write_srt(segments, output_path)
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"srt export failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/creator/highlights":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        segments = data.get("segments")
        if not isinstance(segments, list):
            handler._respond(400, {"error": "list 'segments' is required"})
            return True
        try:
            import creator_media

            result = creator_media.pick_highlight_candidates(
                segments,
                max_candidates=int(data.get("max_candidates", 3) or 3),
                min_duration_s=float(data.get("min_duration_s", 2.0) or 2.0),
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"highlight extraction failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "highlights": result, "count": len(result)})
        return True

    if path == "/creator/export-clip":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input_path", "")).strip()
        output_path = str(data.get("output_path", "")).strip()
        if not input_path or not output_path:
            handler._respond(400, {"error": "'input_path' and 'output_path' are required"})
            return True
        try:
            import creator_media

            result = creator_media.export_clip(
                input_path,
                output_path,
                start_s=float(data.get("start_s", 0) or 0),
                end_s=float(data.get("end_s", 0) or 0),
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"clip export failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/creator/export-social-clip":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input_path", "")).strip()
        output_path = str(data.get("output_path", "")).strip()
        if not input_path or not output_path:
            handler._respond(400, {"error": "'input_path' and 'output_path' are required"})
            return True
        segments = data.get("segments")
        if segments is not None and not isinstance(segments, list):
            handler._respond(400, {"error": "'segments' must be a list when provided"})
            return True
        try:
            import creator_media

            result = creator_media.export_social_clip(
                input_path,
                output_path,
                start_s=float(data.get("start_s", 0) or 0),
                end_s=float(data.get("end_s", 0) or 0),
                preset_name=str(data.get("preset_name", "youtube_short")).strip() or "youtube_short",
                segments=segments,
                burn_subtitles=bool(data.get("burn_subtitles", False)),
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"social clip export failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    if path == "/creator/package-social":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        input_path = str(data.get("input_path", "")).strip()
        output_dir = str(data.get("output_dir", "")).strip()
        package_name = str(data.get("package_name", "")).strip()
        if not input_path or not output_dir or not package_name:
            handler._respond(400, {"error": "'input_path', 'output_dir', and 'package_name' are required"})
            return True
        preset_names = data.get("preset_names")
        if preset_names is not None and not isinstance(preset_names, list):
            handler._respond(400, {"error": "'preset_names' must be a list when provided"})
            return True
        segments = data.get("segments")
        if segments is not None and not isinstance(segments, list):
            handler._respond(400, {"error": "'segments' must be a list when provided"})
            return True
        default_metadata = data.get("default_metadata")
        if default_metadata is not None and not isinstance(default_metadata, dict):
            handler._respond(400, {"error": "'default_metadata' must be an object when provided"})
            return True
        metadata_by_preset = data.get("metadata_by_preset")
        if metadata_by_preset is not None and not isinstance(metadata_by_preset, dict):
            handler._respond(400, {"error": "'metadata_by_preset' must be an object when provided"})
            return True
        try:
            import creator_media

            result = creator_media.create_social_package(
                input_path,
                output_dir,
                package_name=package_name,
                start_s=float(data.get("start_s", 0) or 0),
                end_s=float(data.get("end_s", 0) or 0),
                preset_names=preset_names,
                segments=segments,
                burn_subtitles=bool(data.get("burn_subtitles", True)),
                write_sidecar_srt=bool(data.get("write_sidecar_srt", True)),
                default_metadata=default_metadata,
                metadata_by_preset=metadata_by_preset,
            )
        except creator_media.CreatorMediaError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except Exception as exc:
            handler._respond(500, {"error": f"social package export failed: {exc}"})
            return True
        handler._respond(200, {"ok": True, "result": result})
        return True

    return False
