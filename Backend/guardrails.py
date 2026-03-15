"""
Guardrails Engine — Policy rules and enforcement for Bridge agents.

Stores per-agent policies in guardrails.json. Checks actions against
allowed_tools, denied_actions, and rate_limits. Logs violations.

Default policy: permissive (everything allowed). Tighten per agent.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("guardrails")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GUARDRAILS_FILE = os.path.join(BASE_DIR, "guardrails.json")
VIOLATIONS_FILE = os.path.join(BASE_DIR, "logs", "guardrails_violations.jsonl")

_LOCK = threading.Lock()

# Default permissive policy
_DEFAULT_POLICY: dict[str, Any] = {
    "allowed_tools": ["*"],
    "denied_actions": [],
    "rate_limits": {"max_per_minute": 0},  # 0 = unlimited
    "output_schema": None,
    "consequential_tools_mode": "log",
    "preset_name": "",
    "preset_applied_at": "",
}

_VALID_POLICY_KEYS = {
    "allowed_tools",
    "denied_actions",
    "rate_limits",
    "output_schema",
    "consequential_tools_mode",
    "preset_name",
    "preset_applied_at",
}

_VALID_CONSEQUENTIAL_MODES = {"log", "explicit_allow", "deny"}

_CONSEQUENTIAL_TOOL_RULES: dict[str, dict[str, Any]] = {
    "browser_write": {
        "severity": "high",
        "description": "Browser actions that can change external state or authenticated sessions.",
        "patterns": [
            "bridge_browser_click",
            "bridge_browser_fill",
            "bridge_browser_upload",
            "bridge_browser_action",
            "bridge_stealth_click",
            "bridge_stealth_fill",
            "bridge_stealth_file_upload",
            "bridge_cdp_click",
            "bridge_cdp_fill",
            "bridge_cdp_file_upload",
        ],
    },
    "desktop_control": {
        "severity": "high",
        "description": "Desktop input and control primitives that can affect arbitrary local applications.",
        "patterns": [
            "bridge_desktop_click",
            "bridge_desktop_double_click",
            "bridge_desktop_drag",
            "bridge_desktop_type",
            "bridge_desktop_key",
            "bridge_desktop_scroll",
            "bridge_desktop_hover",
            "bridge_desktop_window_focus",
            "bridge_desktop_window_resize",
            "bridge_desktop_window_minimize",
            "bridge_desktop_clipboard_write",
        ],
    },
    "communications": {
        "severity": "critical",
        "description": "Real-world outbound communication actions.",
        "patterns": [
            "bridge_email_send",
            "bridge_slack_send",
            "bridge_telegram_send",
            "bridge_whatsapp_send",
            "bridge_whatsapp_voice",
            "bridge_phone_call",
        ],
    },
    "credential_and_file_delete": {
        "severity": "critical",
        "description": "Credential mutations or destructive file operations.",
        "patterns": [
            "bridge_credential_store",
            "bridge_credential_delete",
            "bridge_file_delete",
        ],
    },
}

_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "safe_default": {
        "description": (
            "Allows non-consequential tools by default, but requires explicit allow for "
            "browser, desktop, communication, and destructive actions."
        ),
        "policy": {
            "allowed_tools": ["*"],
            "denied_actions": [
                "wipe disk",
                "delete database",
                "drop table",
                "format drive",
                "delete credentials",
            ],
            "rate_limits": {"max_per_minute": 30},
            "output_schema": None,
            "consequential_tools_mode": "explicit_allow",
        },
    },
    "creator_operator": {
        "description": (
            "For creator workflows that need browser, desktop, and communication actions "
            "while keeping destructive operations denied."
        ),
        "policy": {
            "allowed_tools": ["*", "browser_write", "desktop_control", "communications"],
            "denied_actions": [
                "wipe disk",
                "delete database",
                "drop table",
                "format drive",
                "delete credentials",
            ],
            "rate_limits": {"max_per_minute": 120},
            "output_schema": None,
            "consequential_tools_mode": "explicit_allow",
        },
    },
    "admin_operator": {
        "description": (
            "For management-grade operators that need broad access with logging instead of "
            "blanket denial for consequential tools."
        ),
        "policy": {
            "allowed_tools": ["*"],
            "denied_actions": ["wipe disk", "format drive"],
            "rate_limits": {"max_per_minute": 240},
            "output_schema": None,
            "consequential_tools_mode": "log",
        },
    },
}

# In-memory rate tracking: agent_id → list of timestamps
_rate_tracker: dict[str, list[float]] = {}


def _load_policies() -> dict[str, dict[str, Any]]:
    """Load all policies from guardrails.json."""
    if not os.path.exists(GUARDRAILS_FILE):
        return {}
    try:
        with open(GUARDRAILS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load guardrails.json: %s", exc)
        return {}


def _save_policies(policies: dict[str, dict[str, Any]]) -> None:
    """Save policies to guardrails.json atomically."""
    tmp = GUARDRAILS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(policies, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, GUARDRAILS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _log_violation(
    agent_id: str,
    violation_type: str,
    details: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append violation to JSONL log."""
    from datetime import datetime, timezone
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "type": violation_type,
        "details": details,
        "metadata": dict(metadata or {}),
    }
    try:
        os.makedirs(os.path.dirname(VIOLATIONS_FILE), exist_ok=True)
        with open(VIOLATIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    log.warning("GUARDRAIL VIOLATION: agent=%s type=%s details=%s", agent_id, violation_type, details)


def log_violation(
    agent_id: str,
    violation_type: str,
    details: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Public wrapper for writing a guardrail violation entry."""
    _log_violation(agent_id, violation_type, details, metadata=metadata)


def get_policy(agent_id: str) -> dict[str, Any]:
    """Get policy for an agent. Returns default if none set."""
    with _LOCK:
        policies = _load_policies()
    policy = policies.get(agent_id, {})
    # Merge with defaults
    result = dict(_DEFAULT_POLICY)
    result.update(policy)
    result["agent_id"] = agent_id
    return result


def set_policy(agent_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    """Set or update policy for an agent."""
    # Validate fields
    sanitized: dict[str, Any] = {}
    for k, v in policy.items():
        if k in _VALID_POLICY_KEYS:
            if k == "consequential_tools_mode":
                mode = str(v).strip().lower()
                if mode not in _VALID_CONSEQUENTIAL_MODES:
                    raise ValueError(
                        f"invalid consequential_tools_mode '{v}'. Allowed: {sorted(_VALID_CONSEQUENTIAL_MODES)}"
                    )
                sanitized[k] = mode
                continue
            sanitized[k] = v

    with _LOCK:
        policies = _load_policies()
        if agent_id not in policies:
            policies[agent_id] = {}
        policies[agent_id].update(sanitized)
        _save_policies(policies)

    return get_policy(agent_id)


def delete_policy(agent_id: str) -> bool:
    """Remove policy for an agent (reverts to default)."""
    with _LOCK:
        policies = _load_policies()
        if agent_id not in policies:
            return False
        del policies[agent_id]
        _save_policies(policies)
    return True


def list_policies() -> dict[str, dict[str, Any]]:
    """List all configured policies."""
    with _LOCK:
        return _load_policies()


def list_presets() -> dict[str, dict[str, Any]]:
    """Return the available guardrail policy presets."""
    return deepcopy(_POLICY_PRESETS)


def apply_preset(
    agent_id: str,
    preset_name: str,
    *,
    overrides: dict[str, Any] | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    """Apply a named policy preset to an agent."""
    normalized_name = str(preset_name or "").strip()
    if normalized_name not in _POLICY_PRESETS:
        raise KeyError(normalized_name)
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object")

    if replace:
        with _LOCK:
            policies = _load_policies()
            policies[agent_id] = {}
            _save_policies(policies)

    preset_policy = deepcopy(_POLICY_PRESETS[normalized_name]["policy"])
    preset_policy["preset_name"] = normalized_name
    preset_policy["preset_applied_at"] = datetime.now(timezone.utc).isoformat()
    if overrides:
        preset_policy.update(overrides)
    return set_policy(agent_id, preset_policy)


def _tool_allowed_result(agent_id: str, tool_name: str, *, log_violations: bool) -> tuple[bool, str]:
    policy = get_policy(agent_id)
    allowed = policy.get("allowed_tools", ["*"])
    classification = classify_tool(tool_name)
    mode = str(policy.get("consequential_tools_mode", "log")).strip().lower()
    if classification and mode == "deny":
        if log_violations:
            _log_violation(
                agent_id,
                "tool_denied",
                f"consequential tool '{tool_name}' denied by mode=deny",
                metadata={
                    "tool_name": tool_name,
                    "group": classification["group"],
                    "mode": mode,
                },
            )
        return False, f"consequential tool '{tool_name}' denied by guardrails policy"
    if classification and mode == "explicit_allow":
        if tool_name not in allowed and classification["group"] not in allowed:
            if log_violations:
                _log_violation(
                    agent_id,
                    "tool_denied",
                    (
                        f"consequential tool '{tool_name}' requires explicit allow "
                        f"(group '{classification['group']}')"
                    ),
                    metadata={
                        "tool_name": tool_name,
                        "group": classification["group"],
                        "mode": mode,
                    },
                )
            return False, f"consequential tool '{tool_name}' requires explicit allow"
    if "*" in allowed:
        return True, ""
    if tool_name in allowed:
        return True, ""
    if classification and classification["group"] in allowed:
        return True, ""
    if log_violations:
        _log_violation(
            agent_id,
            "tool_denied",
            f"tool '{tool_name}' not in allowed_tools",
            metadata={
                "tool_name": tool_name,
                "group": classification["group"] if classification else "",
            },
        )
    return False, f"tool '{tool_name}' not allowed by guardrails policy"


def check_tool_allowed(agent_id: str, tool_name: str) -> tuple[bool, str]:
    """Check if agent is allowed to use a tool. Returns (allowed, reason)."""
    return _tool_allowed_result(agent_id, tool_name, log_violations=True)


def classify_tool(tool_name: str) -> dict[str, Any] | None:
    """Classify a tool into a consequential tool group if configured."""
    name = str(tool_name or "").strip()
    if not name:
        return None
    for group, info in _CONSEQUENTIAL_TOOL_RULES.items():
        patterns = info.get("patterns", [])
        if name in patterns:
            return {
                "group": group,
                "severity": info.get("severity", "high"),
                "description": info.get("description", ""),
                "tool_name": name,
            }
    return None


def is_consequential_tool(tool_name: str) -> bool:
    """Return True if tool belongs to a consequential tool group."""
    return classify_tool(tool_name) is not None


def list_consequential_tools() -> dict[str, dict[str, Any]]:
    """Return the configured consequential tool catalog."""
    return deepcopy(_CONSEQUENTIAL_TOOL_RULES)


def evaluate_policy(agent_id: str, tool_name: str = "", action_text: str = "") -> dict[str, Any]:
    """Evaluate a policy against a potential tool/action without mutating state.

    Does not consume rate-limit budget and does not log guardrail violations.
    """
    policy = get_policy(agent_id)
    tool_name = str(tool_name or "").strip()
    action_text = str(action_text or "").strip()
    classification = classify_tool(tool_name) if tool_name else None
    tool_allowed = True
    tool_reason = ""

    if tool_name:
        tool_allowed, tool_reason = _tool_allowed_result(agent_id, tool_name, log_violations=False)

    action_denied = False
    action_reason = ""
    if action_text:
        action_denied, action_reason = _action_denied_result(agent_id, action_text, log_violations=False)

    rate_limited, rate_limit_reason, rate_limit = _rate_limit_result(agent_id, consume=False, log_violations=False)

    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "tool_allowed": tool_allowed,
        "tool_reason": tool_reason,
        "tool_classification": classification,
        "action_text": action_text,
        "action_denied": action_denied,
        "action_reason": action_reason,
        "rate_limited": rate_limited,
        "rate_limit_reason": rate_limit_reason,
        "rate_limit": rate_limit,
        "policy": policy,
    }


def _action_denied_result(agent_id: str, action_text: str, *, log_violations: bool) -> tuple[bool, str]:
    policy = get_policy(agent_id)
    denied = policy.get("denied_actions", [])
    if not denied:
        return False, ""
    action_lower = action_text.lower()
    for pattern in denied:
        if str(pattern).lower() in action_lower:
            if log_violations:
                _log_violation(
                    agent_id,
                    "action_denied",
                    f"action matches denied pattern '{pattern}': {action_text[:200]}",
                    metadata={
                        "pattern": str(pattern),
                        "action_preview": action_text[:200],
                    },
                )
            return True, f"action denied by guardrails: matches '{pattern}'"
    return False, ""


def check_action_denied(agent_id: str, action_text: str) -> tuple[bool, str]:
    """Check if action matches any denied pattern. Returns (denied, reason)."""
    return _action_denied_result(agent_id, action_text, log_violations=True)


def _rate_limit_result(
    agent_id: str,
    *,
    consume: bool,
    log_violations: bool,
) -> tuple[bool, str, dict[str, Any]]:
    policy = get_policy(agent_id)
    rate_limits = policy.get("rate_limits", {})
    max_per_min = int(rate_limits.get("max_per_minute", 0) or 0)

    now = time.time()
    cutoff = now - 60
    existing = list(_rate_tracker.get(agent_id, []))
    active = [timestamp for timestamp in existing if timestamp > cutoff]

    if consume:
        _rate_tracker[agent_id] = active

    if max_per_min <= 0:
        return False, "", {
            "enabled": False,
            "max_per_minute": 0,
            "current_count": len(active),
            "remaining": None,
            "window_seconds": 60,
        }

    if len(active) >= max_per_min:
        reason = f"rate limit exceeded: {max_per_min}/minute"
        if log_violations:
            _log_violation(
                agent_id,
                "rate_exceeded",
                f"{len(active)}/{max_per_min} per minute",
                metadata={
                    "current_count": len(active),
                    "max_per_minute": max_per_min,
                },
            )
        return True, reason, {
            "enabled": True,
            "max_per_minute": max_per_min,
            "current_count": len(active),
            "remaining": 0,
            "window_seconds": 60,
        }

    if consume:
        active.append(now)
        _rate_tracker[agent_id] = active

    remaining = max(0, max_per_min - len(active))
    return False, "", {
        "enabled": True,
        "max_per_minute": max_per_min,
        "current_count": len(active),
        "remaining": remaining,
        "window_seconds": 60,
    }


def check_rate_limit(agent_id: str) -> tuple[bool, str]:
    """Check if agent has exceeded rate limit. Returns (exceeded, reason)."""
    exceeded, reason, _ = _rate_limit_result(agent_id, consume=True, log_violations=True)
    return exceeded, reason


def get_violations(agent_id: str = "", limit: int = 50, violation_type: str = "") -> list[dict[str, Any]]:
    """Read recent violations from log."""
    if not os.path.exists(VIOLATIONS_FILE):
        return []
    entries: list[dict[str, Any]] = []
    violation_type = str(violation_type or "").strip()
    try:
        with open(VIOLATIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if agent_id and entry.get("agent_id") != agent_id:
                    continue
                if violation_type and entry.get("type") != violation_type:
                    continue
                entries.append(entry)
    except OSError:
        pass
    return entries[-limit:]  # Return last N


def summarize_violations(agent_id: str = "", limit: int = 500, violation_type: str = "") -> dict[str, Any]:
    """Return aggregated statistics for recent guardrail violations."""
    entries = get_violations(agent_id=agent_id, limit=limit, violation_type=violation_type)
    by_type: dict[str, int] = {}
    by_agent_id: dict[str, int] = {}
    latest_timestamp = ""

    for entry in entries:
        type_key = str(entry.get("type", "")) or "unknown"
        agent_key = str(entry.get("agent_id", "")) or "unknown"
        by_type[type_key] = by_type.get(type_key, 0) + 1
        by_agent_id[agent_key] = by_agent_id.get(agent_key, 0) + 1
        timestamp = str(entry.get("timestamp", ""))
        if timestamp > latest_timestamp:
            latest_timestamp = timestamp

    return {
        "filters": {
            "agent_id": str(agent_id or "").strip(),
            "type": str(violation_type or "").strip(),
            "limit": max(1, min(int(limit), 500)),
        },
        "total_violations": len(entries),
        "by_type": by_type,
        "by_agent_id": by_agent_id,
        "latest_timestamp": latest_timestamp,
    }


def check_output_schema(agent_id: str, output_data: Any) -> tuple[bool, list[str]]:
    """Validate output_data against agent's output_schema policy.

    Returns (valid, errors). If no schema set, always valid.
    Schema format: {"required_fields": [...], "field_types": {"key": "str|int|float|bool|list|dict"}}
    Simple type checks — no jsonschema dependency.
    """
    policy = get_policy(agent_id)
    schema = policy.get("output_schema")
    if not schema or not isinstance(schema, dict):
        return True, []

    if not isinstance(output_data, dict):
        return False, ["output must be a dict"]

    errors: list[str] = []

    # Check required fields
    required = schema.get("required_fields", [])
    for field in required:
        if field not in output_data:
            errors.append(f"missing required field '{field}'")

    # Check field types
    type_map = {"str": str, "int": int, "float": (int, float), "bool": bool, "list": list, "dict": dict}
    field_types = schema.get("field_types", {})
    for field, expected_type_name in field_types.items():
        if field not in output_data:
            continue  # Missing fields handled by required_fields
        expected = type_map.get(expected_type_name)
        if expected and not isinstance(output_data[field], expected):
            actual = type(output_data[field]).__name__
            errors.append(f"field '{field}' expected {expected_type_name}, got {actual}")

    if errors:
        _log_violation(agent_id, "output_schema", "; ".join(errors))

    return len(errors) == 0, errors
