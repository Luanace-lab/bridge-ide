"""Capability library route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote

from server_utils import parse_bool


_DETAIL_RE = re.compile(r"^/capability-library/([^/]+)$")


def handle_get(handler: Any, path: str, query_string: str) -> bool:
    import capability_library

    if path == "/capability-library":
        qs = parse_qs(query_string, keep_blank_values=False)
        official_vendor = None
        reproducible = None
        runtime_verified = None
        try:
            if "official_vendor" in qs:
                official_vendor = parse_bool(qs.get("official_vendor", [""])[0], False)
            if "reproducible" in qs:
                reproducible = parse_bool(qs.get("reproducible", [""])[0], False)
            if "runtime_verified" in qs:
                runtime_verified = parse_bool(qs.get("runtime_verified", [""])[0], False)
            limit = int(qs.get("limit", ["50"])[0])
            offset = int(qs.get("offset", ["0"])[0])
            payload = capability_library.list_entries(
                query=qs.get("q", [""])[0],
                entry_type=qs.get("type", [""])[0],
                vendor=qs.get("vendor", [""])[0],
                cli=qs.get("cli", [""])[0],
                task_tag=qs.get("task_tag", [""])[0],
                source_registry=qs.get("source_registry", [""])[0],
                status=qs.get("status", [""])[0],
                trust_tier=qs.get("trust_tier", [""])[0],
                official_vendor=official_vendor,
                reproducible=reproducible,
                runtime_verified=runtime_verified,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(200, payload)
        return True

    if path == "/capability-library/facets":
        handler._respond(200, capability_library.facets())
        return True

    match = _DETAIL_RE.match(path)
    if not match:
        return False

    entry_id = unquote(match.group(1))
    entry = capability_library.get_entry(entry_id)
    if entry is None:
        handler._respond(404, {"error": f"capability entry '{entry_id}' not found"})
    else:
        handler._respond(200, {"entry": entry})
    return True


def handle_post(handler: Any, path: str) -> bool:
    import capability_library

    if path == "/capability-library/search":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        query = str(data.get("query", data.get("q", ""))).strip()
        if not query:
            handler._respond(400, {"error": "'query' is required"})
            return True
        try:
            payload = capability_library.search_entries(
                query=query,
                entry_type=str(data.get("type", "")).strip(),
                vendor=str(data.get("vendor", "")).strip(),
                cli=str(data.get("cli", "")).strip(),
                task_tag=str(data.get("task_tag", "")).strip(),
                source_registry=str(data.get("source_registry", "")).strip(),
                status=str(data.get("status", "")).strip(),
                trust_tier=str(data.get("trust_tier", "")).strip(),
                official_vendor=(
                    parse_bool(data.get("official_vendor"), False)
                    if "official_vendor" in data
                    else None
                ),
                reproducible=(
                    parse_bool(data.get("reproducible"), False)
                    if "reproducible" in data
                    else None
                ),
                runtime_verified=(
                    parse_bool(data.get("runtime_verified"), False)
                    if "runtime_verified" in data
                    else None
                ),
                limit=int(data.get("limit", 25)),
                offset=int(data.get("offset", 0)),
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(200, payload)
        return True

    if path != "/capability-library/recommend":
        return False

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    task = str(data.get("task", "")).strip()
    if not task:
        handler._respond(400, {"error": "'task' is required"})
        return True
    try:
        payload = capability_library.recommend_entries(
            task=task,
            engine=str(data.get("engine", "")).strip(),
            cli=str(data.get("cli", "")).strip(),
            top_k=int(data.get("top_k", data.get("limit", 10))),
            official_vendor_only=(
                parse_bool(data.get("official_vendor_only"), False)
                if "official_vendor_only" in data
                else (
                    parse_bool(data.get("official_vendor"), False)
                    if "official_vendor" in data
                    else None
                )
            ),
        )
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(200, payload)
    return True
