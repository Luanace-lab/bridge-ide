"""Approval requests, standing approvals, and PAAP helpers extracted from server.py (Slice 07).

This module owns:
- approval request store + expiry helper
- standing approval persistence + audit
- PAAP violation persistence + external-action classification

Anti-circular-import strategy:
  All shared callbacks are injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Module-owned state
# ---------------------------------------------------------------------------
APPROVAL_REQUESTS: dict[str, dict[str, Any]] = {}
APPROVAL_LOCK = threading.Lock()
APPROVAL_DEFAULT_TIMEOUT = 300  # 5 minutes

_SA_LOCK = threading.Lock()
_AGENT_PAAP_CLEARED: dict[str, bool] = {}
_AGENT_PAAP_VIOLATIONS: dict[str, int] = {}
_PAAP_EXTERNAL_PATTERNS: tuple[str, ...] = (
    "brows", "stealth", "cdp", "ghost", "playwright",
    "navigate", "scraping", "crawling",
    "web_screenshot", "external_screenshot",
    "api_call", "api_request", "calling_api", "fetch_api",
)

# NOTE: "screenshot" removed — too broad, matches self-verification (Playwright UI checks).
# NOTE: "api" removed — too broad, matches "capital", "capability", "recap".

# Paths — set by init()
_SA_FILE: str = ""
_SA_AUDIT_FILE: str = ""
_PAAP_VIOLATIONS_FILE: str = ""

# Injected callbacks — set by init()
_append_message: Callable[..., Any] | None = None
_ws_broadcast: Callable[..., Any] | None = None
_is_management_agent_fn: Callable[[str], bool] | None = None
_SA_CREATE_ALLOWED_GETTER: Callable[[], set[str]] | None = None


def init(
    *,
    base_dir: str,
    messages_dir: str,
    agent_log_dir: str,
    append_message_fn: Callable[..., Any],
    ws_broadcast_fn: Callable[..., Any],
    is_management_agent_fn: Callable[[str], bool],
    sa_create_allowed_getter: Callable[[], set[str]],
) -> None:
    """Bind file paths and callbacks. Must be called once before runtime use."""
    global _SA_FILE, _SA_AUDIT_FILE, _PAAP_VIOLATIONS_FILE
    global _append_message, _ws_broadcast, _is_management_agent_fn, _SA_CREATE_ALLOWED_GETTER

    _SA_FILE = os.path.join(base_dir, "standing_approvals.json")
    _SA_AUDIT_FILE = os.path.join(agent_log_dir, "sa_audit.jsonl")
    _PAAP_VIOLATIONS_FILE = os.path.join(messages_dir, "paap_violations.json")

    _append_message = append_message_fn
    _ws_broadcast = ws_broadcast_fn
    _is_management_agent_fn = is_management_agent_fn
    _SA_CREATE_ALLOWED_GETTER = sa_create_allowed_getter

    _AGENT_PAAP_VIOLATIONS.clear()
    _AGENT_PAAP_VIOLATIONS.update(_load_paap_violations())


def _is_management_agent(agent_id: str) -> bool:
    if _is_management_agent_fn is None:
        raise RuntimeError("handlers.approvals.init() not called: is_management_agent_fn missing")
    return _is_management_agent_fn(agent_id)


def _append_message_cb(*args: Any, **kwargs: Any) -> Any:
    if _append_message is None:
        raise RuntimeError("handlers.approvals.init() not called: append_message_fn missing")
    return _append_message(*args, **kwargs)


def _ws_broadcast_cb(*args: Any, **kwargs: Any) -> Any:
    if _ws_broadcast is None:
        raise RuntimeError("handlers.approvals.init() not called: ws_broadcast_fn missing")
    return _ws_broadcast(*args, **kwargs)


def _sa_create_allowed() -> set[str]:
    if _SA_CREATE_ALLOWED_GETTER is None:
        raise RuntimeError("handlers.approvals.init() not called: sa_create_allowed_getter missing")
    return set(_SA_CREATE_ALLOWED_GETTER())


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/approval/pending":
        _approval_expire_check()
        filter_agent = (query.get("agent_id") or [None])[0]
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip() or None
        is_mgmt = bool(requesting_agent and _is_management_agent(requesting_agent))
        with APPROVAL_LOCK:
            pending = [
                req
                for req in APPROVAL_REQUESTS.values()
                if req["status"] == "pending"
                and (filter_agent is None or req["agent_id"] == filter_agent)
                and (
                    requesting_agent is None
                    or is_mgmt
                    or req.get("requested_by") == requesting_agent
                    or req.get("agent_id") == requesting_agent
                )
            ]
        pending.sort(key=lambda r: r["requested_at"])
        handler._respond(200, {"pending": pending, "count": len(pending)})
        return True

    approval_status_match = re.match(r"^/approval/([^/]+)$", path)
    if approval_status_match:
        request_id = approval_status_match.group(1)
        if request_id not in ("pending", "respond"):
            _approval_expire_check()
            with APPROVAL_LOCK:
                req = APPROVAL_REQUESTS.get(request_id)
            if req is None:
                handler._respond(404, {"error": f"approval request not found: {request_id}"})
            else:
                handler._respond(200, req)
            return True

    if path == "/standing-approval/list":
        with _SA_LOCK:
            approvals = _load_standing_approvals()
        handler._respond(
            200,
            {
                "ok": True,
                "approvals": approvals,
                "count": len(approvals),
            },
        )
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    approval_edit_match = re.match(r"^/approval/([^/]+)/edit$", path)
    if approval_edit_match:
        request_id = approval_edit_match.group(1)
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True

        new_payload = data.get("payload")
        if not new_payload or not isinstance(new_payload, dict):
            handler._respond(400, {"error": "'payload' (dict) is required"})
            return True

        decided_by = str(data.get("decided_by", "user")).strip()
        if decided_by != "user":
            handler._respond(403, {"error": "only 'user' (Leo) may edit approval payloads"})
            return True

        _approval_expire_check()

        with APPROVAL_LOCK:
            req = APPROVAL_REQUESTS.get(request_id)
            if req is None:
                handler._respond(404, {"error": f"approval request not found: {request_id}"})
                return True
            if req["status"] != "pending":
                handler._respond(
                    409,
                    {
                        "error": f"cannot edit — request already {req['status']}",
                        "request_id": request_id,
                    },
                )
                return True

            old_payload = req.get("payload", {})
            for key, value in new_payload.items():
                old_payload[key] = value
            req["payload"] = old_payload
            result_req = dict(req)

        agent_id = result_req["agent_id"]
        _append_message_cb(
            "system",
            agent_id,
            f"[APPROVAL EDITIERT] Request {request_id}: Payload wurde von Leo aktualisiert.",
            meta={"type": "approval_edited", "request_id": request_id},
        )
        _ws_broadcast_cb(
            "approval_edited",
            {
                "request_id": request_id,
                "agent_id": agent_id,
                "edited_fields": list(new_payload.keys()),
            },
        )
        print(f"[approval] Payload edited: {request_id} — fields: {list(new_payload.keys())}")
        handler._respond(
            200,
            {
                "ok": True,
                "request_id": request_id,
                "payload": result_req["payload"],
            },
        )
        return True

    if path == "/standing-approval/create":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid json body"})
            return True
        created_by = str(data.get("created_by", "")).strip()
        sa_allowed = _sa_create_allowed()
        if created_by not in sa_allowed:
            handler._respond(403, {"error": f"only {sorted(sa_allowed)} may create Standing Approvals"})
            return True
        sa_action = str(data.get("action", "")).strip()
        sa_agent = str(data.get("agent", "")).strip()
        sa_scope = data.get("scope", {})
        if not sa_action or not sa_agent or not sa_scope.get("target"):
            handler._respond(400, {"error": "fields 'action', 'agent', 'scope.target' are required"})
            return True

        now_iso = datetime.now(timezone.utc).isoformat()
        sa_id = _sa_generate_id()
        new_sa: dict[str, Any] = {
            "id": sa_id,
            "created_at": now_iso,
            "created_by": created_by,
            "status": "active",
            "action": sa_action,
            "agent": sa_agent,
            "scope": sa_scope,
            "constraints": data.get("constraints", {}),
            "expires": data.get("expires"),
            "max_uses": data.get("max_uses"),
            "use_count": 0,
            "last_used": None,
            "paused_reason": None,
        }

        with _SA_LOCK:
            approvals = _load_standing_approvals()
            for existing in approvals:
                if (
                    existing.get("status") == "active"
                    and existing.get("action") == sa_action
                    and existing.get("agent") == sa_agent
                    and existing.get("scope", {}).get("target") == sa_scope.get("target")
                ):
                    handler._respond(
                        409,
                        {
                            "error": "active Standing Approval for this (action, agent, target) already exists",
                            "existing_id": existing.get("id"),
                        },
                    )
                    return True
            approvals.append(new_sa)
            _save_standing_approvals(approvals)

        _sa_audit_log(
            {
                "sa_id": sa_id,
                "event": "created",
                "created_by": created_by,
                "action": sa_action,
                "agent": sa_agent,
                "target": sa_scope.get("target"),
            }
        )
        print(f"[sa] Created: {sa_id} — {sa_action} for {sa_agent} by {created_by}")
        handler._respond(201, {"ok": True, "standing_approval": new_sa})
        return True

    sa_revoke_match = re.match(r"^/standing-approval/(SA-[A-Z0-9]+)/revoke$", path)
    if sa_revoke_match:
        sa_id = sa_revoke_match.group(1)
        revoked = False
        with _SA_LOCK:
            approvals = _load_standing_approvals()
            for sa in approvals:
                if sa.get("id") == sa_id:
                    if sa.get("status") != "active":
                        handler._respond(409, {"error": f"Standing Approval {sa_id} is already {sa.get('status')}"})
                        return True
                    sa["status"] = "revoked"
                    sa["revoked_at"] = datetime.now(timezone.utc).isoformat()
                    revoked = True
                    break
            if revoked:
                _save_standing_approvals(approvals)

        if not revoked:
            handler._respond(404, {"error": f"Standing Approval {sa_id} not found"})
            return True

        _sa_audit_log({"sa_id": sa_id, "event": "revoked"})
        print(f"[sa] Revoked: {sa_id}")
        handler._respond(200, {"ok": True, "sa_id": sa_id, "status": "revoked"})
        return True

    return False


def _approval_generate_id() -> str:
    """Generate a unique approval request ID with prefix."""
    return f"appr_{uuid.uuid4().hex[:12]}"


def _approval_expire_check() -> list[dict[str, Any]]:
    """Lazy expire pending approval requests and emit notifications."""
    now = datetime.now(timezone.utc)
    expired: list[dict[str, Any]] = []
    with APPROVAL_LOCK:
        for req in APPROVAL_REQUESTS.values():
            if req["status"] != "pending":
                continue
            expires_at = datetime.fromisoformat(req["expires_at"])
            if now >= expires_at:
                req["status"] = "expired"
                req["decided_at"] = now.isoformat()
                req["comment"] = "timeout — keine Antwort innerhalb des Zeitlimits"
                expired.append(dict(req))

    for req in expired:
        agent_id = req["agent_id"]
        action = req["action"]
        desc = req["description"]
        if _append_message is not None:
            _append_message(
                "system",
                agent_id,
                f"[APPROVAL EXPIRED] Deine Anfrage wurde nicht rechtzeitig beantwortet.\n"
                f"Aktion: {action}\nBeschreibung: {desc}",
                meta={"type": "approval_expired", "request_id": req["request_id"]},
            )
        if _ws_broadcast is not None:
            _ws_broadcast(
                "approval_decided",
                {
                    "request_id": req["request_id"],
                    "agent_id": agent_id,
                    "decision": "expired",
                    "action": action,
                },
            )
    return expired


def _load_standing_approvals() -> list[dict[str, Any]]:
    """Load standing approvals from JSON file."""
    if not _SA_FILE:
        return []
    try:
        with open(_SA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("approvals", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_standing_approvals(approvals: list[dict[str, Any]]) -> None:
    """Save standing approvals to JSON file atomically."""
    if not _SA_FILE:
        return
    data = json.dumps({"approvals": approvals}, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_SA_FILE), suffix=".tmp")
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, _SA_FILE)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _sa_generate_id() -> str:
    """Generate a unique Standing Approval ID."""
    return f"SA-{uuid.uuid4().hex[:6].upper()}"


def _sa_audit_log(entry: dict[str, Any]) -> None:
    """Append entry to standing-approval audit log."""
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    if not _SA_AUDIT_FILE:
        return
    try:
        with open(_SA_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[sa-audit] Failed to write audit log: {exc}")


def _check_standing_approval(action: str, agent_id: str, target: str) -> dict[str, Any] | None:
    """Return matching active standing approval, if any."""
    now = datetime.now(timezone.utc)
    with _SA_LOCK:
        approvals = _load_standing_approvals()
        for sa in approvals:
            if sa.get("status") != "active":
                continue
            if sa.get("action") != action:
                continue
            if sa.get("agent") != agent_id:
                continue
            scope = sa.get("scope", {})
            if scope.get("target") != target:
                continue
            expires = sa.get("expires")
            if expires:
                try:
                    if now >= datetime.fromisoformat(expires):
                        continue
                except (ValueError, TypeError):
                    continue
            max_uses = sa.get("max_uses")
            use_count = sa.get("use_count", 0)
            if max_uses is not None and use_count >= max_uses:
                continue
            return dict(sa)
    return None


def _sa_increment_usage(sa_id: str) -> None:
    """Increment use_count and update last_used for a standing approval."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with _SA_LOCK:
        approvals = _load_standing_approvals()
        for sa in approvals:
            if sa.get("id") == sa_id:
                sa["use_count"] = sa.get("use_count", 0) + 1
                sa["last_used"] = now_iso
                break
        _save_standing_approvals(approvals)


def _load_paap_violations() -> dict[str, int]:
    """Load persisted PAAP violations from disk."""
    if not _PAAP_VIOLATIONS_FILE:
        return {}
    try:
        with open(_PAAP_VIOLATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _save_paap_violations() -> None:
    """Persist PAAP violations to disk."""
    if not _PAAP_VIOLATIONS_FILE:
        return
    try:
        tmp = _PAAP_VIOLATIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_AGENT_PAAP_VIOLATIONS, f)
        os.replace(tmp, _PAAP_VIOLATIONS_FILE)
    except OSError:
        pass


def _is_paap_external_action(action: str) -> bool:
    """Check if an activity action represents an external action requiring PAAP."""
    action_lower = action.lower()
    return any(p in action_lower for p in _PAAP_EXTERNAL_PATTERNS)
