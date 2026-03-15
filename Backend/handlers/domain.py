"""Domain Engine HTTP route handler.

Handles /work-items/*, /calendar/*, /library/* endpoints.
Generic for all domains — Marketing, Legal, Finance, etc.
"""

from __future__ import annotations

import os
from typing import Any


def handle_get(handler: Any, path: str) -> bool:
    """Handle GET requests for domain engine paths."""

    # GET /work-items
    if path == "/work-items":
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        qs = {}
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
        workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter required"})
            return True
        try:
            from domain_engine.work_item import list_work_items
            domain = qs.get("domain", [""])[0]
            status = qs.get("status", [""])[0]
            campaign_id = qs.get("campaign_id", [""])[0]
            items = list_work_items(workspace_dir, domain=domain, status=status, campaign_id=campaign_id)
            handler._respond(200, {"items": items, "count": len(items)})
        except Exception as exc:
            handler._respond(500, {"error": f"list work items failed: {exc}"})
        return True

    # GET /work-items/{id}
    if path.startswith("/work-items/") and not path.endswith("/metrics") and not path.endswith("/events"):
        item_id = path.split("/work-items/")[1].strip("/")
        if not item_id:
            handler._respond(400, {"error": "item_id required"})
            return True
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        workspace_dir = ""
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
            workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter required"})
            return True
        try:
            from domain_engine.work_item import load_work_item
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            handler._respond(200, item)
        except Exception as exc:
            handler._respond(500, {"error": f"get work item failed: {exc}"})
        return True

    # GET /calendar
    if path == "/calendar":
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        qs = {}
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
        workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter required"})
            return True
        try:
            from domain_engine.calendar_index import get_calendar
            entries = get_calendar(
                workspace_dir,
                start_date=qs.get("start", [""])[0],
                end_date=qs.get("end", [""])[0],
                domain=qs.get("domain", [""])[0],
            )
            handler._respond(200, {"entries": entries, "count": len(entries)})
        except Exception as exc:
            handler._respond(500, {"error": f"calendar failed: {exc}"})
        return True

    # GET /legal/clauses
    if path == "/legal/clauses":
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        qs = {}
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
        jurisdiction = qs.get("jurisdiction", [""])[0]
        try:
            from domain_packs.legal.clause_types import list_clause_types, clauses_for_jurisdiction, list_content_types
            if jurisdiction:
                clauses = clauses_for_jurisdiction(jurisdiction)
            else:
                clauses = list_clause_types()
            content_types = list_content_types()
            handler._respond(200, {
                "clauses": clauses,
                "clause_count": len(clauses),
                "content_types": content_types,
                "jurisdiction_filter": jurisdiction or None,
            })
        except Exception as exc:
            handler._respond(500, {"error": f"legal clauses failed: {exc}"})
        return True

    # GET /legal/risk-score
    if path == "/legal/risk-score":
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        qs = {}
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
        clause_type = qs.get("clause_type", [""])[0]
        jurisdiction = qs.get("jurisdiction", ["DE"])[0]
        if not clause_type:
            handler._respond(400, {"error": "clause_type query parameter required"})
            return True
        try:
            from domain_packs.legal.risk_assessment import assess_clause_risk
            result = assess_clause_risk(
                clause_type=clause_type,
                jurisdiction=jurisdiction,
                clause_present=qs.get("present", ["true"])[0].lower() != "false",
            )
            handler._respond(200, result)
        except Exception as exc:
            handler._respond(500, {"error": f"risk score failed: {exc}"})
        return True

    # GET /legal/dpa-checklist
    if path == "/legal/dpa-checklist":
        try:
            from domain_packs.legal.dpa_checklist import list_dpa_clauses, get_dpa_keywords
            clauses = list_dpa_clauses()
            keywords = get_dpa_keywords()
            handler._respond(200, {
                "clauses": clauses,
                "clause_count": len(clauses),
                "keywords": keywords,
            })
        except Exception as exc:
            handler._respond(500, {"error": f"dpa checklist failed: {exc}"})
        return True

    # GET /library/items
    if path == "/library/items":
        import urllib.parse
        raw_path = getattr(handler, "path", "")
        qs = {}
        if "?" in raw_path:
            qs = urllib.parse.parse_qs(raw_path.split("?", 1)[1])
        workspace_dir = qs.get("workspace_dir", [""])[0]
        if not workspace_dir:
            handler._respond(400, {"error": "workspace_dir query parameter required"})
            return True
        try:
            from domain_engine.content_library import list_library_items
            items = list_library_items(workspace_dir, domain=qs.get("domain", [""])[0])
            handler._respond(200, {"items": items, "count": len(items)})
        except Exception as exc:
            handler._respond(500, {"error": f"library failed: {exc}"})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    """Handle POST requests for domain engine paths."""

    # POST /work-items
    if path == "/work-items":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        domain = str(data.get("domain", "")).strip()
        item_type = str(data.get("type", "")).strip()
        title = str(data.get("title", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not domain or not item_type or not title or not workspace_dir:
            handler._respond(400, {"error": "'domain', 'type', 'title', 'workspace_dir' required"})
            return True
        try:
            from domain_engine.work_item import create_work_item
            item = create_work_item(
                domain=domain,
                item_type=item_type,
                title=title,
                workspace_dir=workspace_dir,
                brief=str(data.get("brief", "")),
                body=str(data.get("body", "")),
                owner=str(data.get("owner", "")),
                campaign_id=str(data.get("campaign_id", "")),
                channel_targets=data.get("channel_targets", []),
                schedule=str(data.get("schedule", "")),
                tags=data.get("tags", []),
                metadata=data.get("metadata"),
                overlay=data.get("overlay"),
            )
            handler._respond(201, {"item_id": item["item_id"], "status": item["status"]})
        except Exception as exc:
            handler._respond(500, {"error": f"create work item failed: {exc}"})
        return True

    # POST /work-items/{id}/approve
    if path.startswith("/work-items/") and path.endswith("/approve"):
        item_id = path.split("/work-items/")[1].split("/approve")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        reviewer = str(data.get("reviewer", "user")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' required"})
            return True
        try:
            from domain_engine.work_item import load_work_item, approve_work_item
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            item = approve_work_item(item, reviewer, workspace_dir)
            handler._respond(200, {"ok": True, "item_id": item_id, "status": item["status"]})
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"approve failed: {exc}"})
        return True

    # POST /work-items/{id}/transition
    if path.startswith("/work-items/") and path.endswith("/transition"):
        item_id = path.split("/work-items/")[1].split("/transition")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        new_status = str(data.get("status", "")).strip()
        if not workspace_dir or not new_status:
            handler._respond(400, {"error": "'workspace_dir' and 'status' required"})
            return True
        try:
            from domain_engine.work_item import load_work_item, transition_work_item
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            item = transition_work_item(item, new_status, workspace_dir)
            handler._respond(200, {"ok": True, "item_id": item_id, "status": item["status"]})
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"transition failed: {exc}"})
        return True

    # POST /work-items/{id}/optimize
    if path.startswith("/work-items/") and path.endswith("/optimize"):
        item_id = path.split("/work-items/")[1].split("/optimize")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        platform = str(data.get("platform", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' required"})
            return True
        try:
            from domain_engine.work_item import load_work_item
            from domain_packs.marketing.platform_rules import optimize_for_platform
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            results = {}
            if platform:
                results[platform] = optimize_for_platform(item.get("body", ""), platform)
            else:
                for ch in item.get("channel_targets", []):
                    results[ch] = optimize_for_platform(item.get("body", ""), ch)
            handler._respond(200, {"item_id": item_id, "optimizations": results})
        except Exception as exc:
            handler._respond(500, {"error": f"optimize failed: {exc}"})
        return True

    # POST /work-items/{id}/variants
    if path.startswith("/work-items/") and path.endswith("/variants"):
        item_id = path.split("/work-items/")[1].split("/variants")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        variant_body = str(data.get("body", "")).strip()
        variant_label = str(data.get("label", "")).strip()
        if not workspace_dir or not variant_body:
            handler._respond(400, {"error": "'workspace_dir' and 'body' required"})
            return True
        try:
            from domain_engine.work_item import load_work_item, add_variant
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            item = add_variant(item, variant_body, variant_label, workspace_dir)
            handler._respond(200, {"ok": True, "variants": len(item["variants"])})
        except Exception as exc:
            handler._respond(500, {"error": f"add variant failed: {exc}"})
        return True

    # POST /analytics/import
    if path == "/analytics/import":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        item_id = str(data.get("item_id", "")).strip()
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        channel = str(data.get("channel", "")).strip()
        metrics = data.get("metrics", {})
        if not item_id or not workspace_dir or not channel:
            handler._respond(400, {"error": "'item_id', 'workspace_dir', 'channel' required"})
            return True
        try:
            from domain_engine.work_item import load_work_item, import_metrics
            item = load_work_item(item_id, workspace_dir)
            if not item:
                handler._respond(404, {"error": f"WorkItem {item_id} not found"})
                return True
            item = import_metrics(item, channel, metrics, str(data.get("period", "")), workspace_dir)
            handler._respond(200, {"ok": True, "snapshots": len(item.get("observation_snapshots", []))})
        except Exception as exc:
            handler._respond(500, {"error": f"import metrics failed: {exc}"})
        return True

    # POST /legal/analyze
    if path == "/legal/analyze":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        detected_clauses = data.get("detected_clauses")
        jurisdiction = str(data.get("jurisdiction", "")).strip()
        if not detected_clauses or not isinstance(detected_clauses, dict) or not jurisdiction:
            handler._respond(400, {"error": "'detected_clauses' (dict) and 'jurisdiction' required"})
            return True
        try:
            from domain_packs.legal.risk_assessment import assess_contract_risk, compare_across_jurisdictions
            jurisdictions = data.get("jurisdictions")
            playbook = data.get("playbook")
            if jurisdictions and isinstance(jurisdictions, list):
                result = compare_across_jurisdictions(detected_clauses, jurisdictions, playbook)
                handler._respond(200, {"cross_jurisdictional": True, "results": result})
            else:
                result = assess_contract_risk(detected_clauses, jurisdiction, playbook)
                handler._respond(200, result)
        except Exception as exc:
            handler._respond(500, {"error": f"legal analyze failed: {exc}"})
        return True

    # POST /legal/dpa-check
    if path == "/legal/dpa-check":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        clause_results = data.get("clause_results")
        if not clause_results or not isinstance(clause_results, dict):
            handler._respond(400, {"error": "'clause_results' (dict) required"})
            return True
        try:
            from domain_packs.legal.dpa_checklist import run_dpa_check
            result = run_dpa_check(clause_results)
            handler._respond(200, result)
        except Exception as exc:
            handler._respond(500, {"error": f"dpa check failed: {exc}"})
        return True

    # POST /library/items
    if path == "/library/items":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        domain = str(data.get("domain", "")).strip()
        item_type = str(data.get("type", "")).strip()
        title = str(data.get("title", "")).strip()
        body = str(data.get("body", "")).strip()
        if not workspace_dir or not domain or not title or not body:
            handler._respond(400, {"error": "'workspace_dir', 'domain', 'title', 'body' required"})
            return True
        try:
            from domain_engine.content_library import create_library_item
            item = create_library_item(domain, item_type, title, body, workspace_dir, tags=data.get("tags"))
            handler._respond(201, {"library_id": item["library_id"]})
        except Exception as exc:
            handler._respond(500, {"error": f"create library item failed: {exc}"})
        return True

    # POST /library/items/{id}/instantiate
    if path.startswith("/library/items/") and path.endswith("/instantiate"):
        library_id = path.split("/library/items/")[1].split("/instantiate")[0]
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid JSON body"})
            return True
        workspace_dir = str(data.get("workspace_dir", "")).strip()
        if not workspace_dir:
            handler._respond(400, {"error": "'workspace_dir' required"})
            return True
        try:
            from domain_engine.content_library import instantiate_library_item
            item = instantiate_library_item(library_id, workspace_dir, overrides=data.get("overrides"))
            handler._respond(201, {"item_id": item["item_id"], "status": item["status"]})
        except FileNotFoundError as exc:
            handler._respond(404, {"error": str(exc)})
        except Exception as exc:
            handler._respond(500, {"error": f"instantiate failed: {exc}"})
        return True

    return False
