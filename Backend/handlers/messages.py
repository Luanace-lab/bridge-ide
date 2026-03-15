"""Message-queue functions extracted from server.py (Slice 02).

This module owns:
- load_history / persist_message
- append_message (77+ callsites — signature UNCHANGED)
- messages_for_agent
- Dedup globals & helpers (_broadcast_fingerprint, _is_duplicate_broadcast,
  _is_duplicate_direct, _is_echo_ack_message)

Anti-circular-import strategy:
  All shared state and cross-domain functions are injected via init().
  This module NEVER imports from server.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Module-local message-ID counter (replaces server._MSG_ID_COUNTER).
# Fully owned here because both load_history() and append_message() live in
# this module.  init() seeds the initial value.
# ---------------------------------------------------------------------------
_msg_id_counter: int = 0

# ---------------------------------------------------------------------------
# Dedup globals (local to this module — no sharing with server.py needed)
# ---------------------------------------------------------------------------
_BROADCAST_DEDUP: dict[str, tuple[str, float]] = {}  # sender -> (fingerprint, ts)
_BROADCAST_DEDUP_WINDOW = 300  # 5 minutes
_BROADCAST_DEDUP_EXEMPT = {"system", "user"}

# Direct message dedup: sender:recipient -> (fingerprint, ts)
_DIRECT_DEDUP: dict[str, tuple[str, float]] = {}
_DIRECT_DEDUP_WINDOW = 3  # seconds — catch parallel tool calls (exact block)
_DIRECT_DEDUP_CONTENT_WINDOW = 15  # seconds — catch content-similar messages

# Echo-loop suppression (Codex ack ping-pong)
_ECHO_ACK_PATTERNS = [
    re.compile(r"^nachricht\s+\d+\s+verarbeitet", re.IGNORECASE),
    re.compile(r"^message\s+\d+\s+processed", re.IGNORECASE),
]
_ECHO_ACK_KEYWORDS = {"verarbeitet", "verstanden", "danke", "acknowledged", "processed"}

# ---------------------------------------------------------------------------
# Injected references (set by init())
# ---------------------------------------------------------------------------
_MESSAGES: list[dict[str, Any]] = []
_CURSORS: dict[str, int] = {}
_LOCK: Any = None
_COND: Any = None
_LOG_FILE: str = ""

# Callback functions
_ws_broadcast_message: Callable[..., Any] | None = None
_resolve_agent_alias: Callable[[str], str] | None = None
_push_non_mcp_notification: Callable[..., Any] | None = None
_maybe_team_lead_intervene: Callable[..., Any] | None = None
_is_management_agent: Callable[[str], bool] | None = None
_get_team_members: Callable[[str], set[str]] | None = None
_utc_now_iso: Callable[[], str] | None = None


def init(
    *,
    messages: list[dict[str, Any]],
    cursors: dict[str, int],
    lock: Any,
    cond: Any,
    log_file: str,
    ws_broadcast_message_fn: Callable[..., Any],
    resolve_agent_alias_fn: Callable[[str], str],
    push_non_mcp_fn: Callable[..., Any],
    maybe_team_lead_fn: Callable[..., Any],
    is_management_agent_fn: Callable[[str], bool],
    get_team_members_fn: Callable[[str], set[str]],
    utc_now_iso_fn: Callable[[], str],
) -> None:
    """Bind shared state and cross-domain callbacks.  Must be called once
    before any other function in this module is used."""
    global _MESSAGES, _CURSORS, _LOCK, _COND, _LOG_FILE
    global _ws_broadcast_message, _resolve_agent_alias
    global _push_non_mcp_notification, _maybe_team_lead_intervene
    global _is_management_agent, _get_team_members, _utc_now_iso

    _MESSAGES = messages
    _CURSORS = cursors
    _LOCK = lock
    _COND = cond
    _LOG_FILE = log_file

    _ws_broadcast_message = ws_broadcast_message_fn
    _resolve_agent_alias = resolve_agent_alias_fn
    _push_non_mcp_notification = push_non_mcp_fn
    _maybe_team_lead_intervene = maybe_team_lead_fn
    _is_management_agent = is_management_agent_fn
    _get_team_members = get_team_members_fn
    _utc_now_iso = utc_now_iso_fn


# ===================================================================
# History persistence
# ===================================================================

def load_history() -> None:
    global _msg_id_counter
    if not os.path.exists(_LOG_FILE):
        return

    with open(_LOG_FILE, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in msg:
                msg["id"] = _msg_id_counter
                _msg_id_counter += 1
            else:
                # Track the highest ID seen to avoid collisions
                if msg["id"] >= _msg_id_counter:
                    _msg_id_counter = msg["id"] + 1
            _MESSAGES.append(msg)


def persist_message(msg: dict[str, Any]) -> None:
    with open(_LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(msg, ensure_ascii=False) + "\n")


# ===================================================================
# Dedup helpers
# ===================================================================

def _broadcast_fingerprint(content: str) -> str:
    """Normalize broadcast content for dedup: strip timestamps, TZ, numbers, keep letters+spaces."""
    s = content.lower()
    # Remove timezone abbreviations that vary between messages
    s = re.sub(r"\b(?:utc|cet|cest|gmt|est|pst)\b", "", s)
    # Remove all non-letter chars, normalize whitespace
    s = re.sub(r"[^a-z ]", "", s)
    s = re.sub(r" +", " ", s)
    return s[:60].strip()


def _is_duplicate_broadcast(sender: str, content: str) -> bool:
    """Return True if sender already sent a similar broadcast within the dedup window."""
    now = time.time()
    fp = _broadcast_fingerprint(content)
    if sender in _BROADCAST_DEDUP:
        old_fp, old_ts = _BROADCAST_DEDUP[sender]
        if (now - old_ts) < _BROADCAST_DEDUP_WINDOW:
            # Compare by common prefix (min 20 chars) to catch variations
            cmp_len = min(len(fp), len(old_fp), 40)
            if cmp_len >= 20 and fp[:cmp_len] == old_fp[:cmp_len]:
                return True
    _BROADCAST_DEDUP[sender] = (fp, now)
    return False


def _is_duplicate_direct(sender: str, recipient: str, content: str) -> bool:
    """Return True if sender sent a similar message to the same recipient recently.

    Two-tier dedup:
    1. Exact block: ANY message from same sender->recipient within 3s (parallel tool calls)
    2. Content-similar: similar content within 15s (catches near-duplicate messages)
    """
    now = time.time()
    key = f"{sender}:{recipient}"
    fp = _broadcast_fingerprint(content)
    if key in _DIRECT_DEDUP:
        old_fp, old_ts = _DIRECT_DEDUP[key]
        time_diff = now - old_ts
        # Tier 1: Any message within 3s from same sender->recipient
        if time_diff < _DIRECT_DEDUP_WINDOW:
            return True
        # Tier 2: Content-similar within 15s
        if time_diff < _DIRECT_DEDUP_CONTENT_WINDOW and old_fp and fp:
            # Prefix match (like broadcast dedup)
            cmp_len = min(len(fp), len(old_fp), 40)
            if cmp_len >= 15 and fp[:cmp_len] == old_fp[:cmp_len]:
                return True
            # Substring match: shorter message contained in longer one
            shorter, longer = (fp, old_fp) if len(fp) <= len(old_fp) else (old_fp, fp)
            if len(shorter) >= 15 and shorter in longer:
                return True
    _DIRECT_DEDUP[key] = (fp, now)
    return False


def _is_echo_ack_message(content: str) -> bool:
    """Detect empty acknowledgement messages that carry no actionable content.

    Returns True for messages like "Nachricht 64038 verarbeitet. Danke, ..."
    where the entire content is just an ack with no real work instructions.
    """
    c = content.strip()
    if len(c) > 300:
        return False  # Long messages likely have real content
    c_lower = c.lower()
    # Pattern 1: Starts with "Nachricht \d+ verarbeitet"
    for pat in _ECHO_ACK_PATTERNS:
        if pat.search(c_lower):
            return True
    # Pattern 2: Short message (< 150 chars) that is purely ack keywords
    if len(c) < 150:
        ack_count = sum(1 for kw in _ECHO_ACK_KEYWORDS if kw in c_lower)
        # If message has 2+ ack keywords and no tool calls / code / URLs
        if ack_count >= 2 and "bridge_" not in c_lower and "http" not in c_lower and "```" not in c:
            return True
    return False


# ===================================================================
# Core message operations
# ===================================================================

def append_message(
    sender: str,
    recipient: str,
    content: str,
    meta: dict[str, Any] | None = None,
    suppress_team_lead: bool = False,
    reply_to: int | None = None,
    channel: str | None = None,
    team: str | None = None,
) -> dict[str, Any]:
    global _msg_id_counter

    # Resolve aliases to canonical IDs
    recipient = _resolve_agent_alias(recipient)  # type: ignore[misc]

    # Broadcast dedup: suppress duplicate broadcasts from agents
    _broadcast_recipients = {"all", "all_managers", "leads"}
    if (
        recipient in _broadcast_recipients
        and sender not in _BROADCAST_DEDUP_EXEMPT
        and _is_duplicate_broadcast(sender, content)
    ):
        print(f"[dedup] Suppressed duplicate broadcast from {sender}")
        return {
            "id": None,
            "from": sender,
            "to": recipient,
            "content": content,
            "timestamp": _utc_now_iso(),  # type: ignore[misc]
            "suppressed": True,
        }

    # Direct message dedup: catch parallel tool-call duplicates
    if (
        recipient not in _broadcast_recipients
        and sender not in _BROADCAST_DEDUP_EXEMPT
        and _is_duplicate_direct(sender, recipient, content)
    ):
        print(f"[dedup] Suppressed duplicate direct from {sender}\u2192{recipient}")
        return {
            "id": None,
            "from": sender,
            "to": recipient,
            "content": content,
            "timestamp": _utc_now_iso(),  # type: ignore[misc]
            "suppressed": True,
        }

    # Echo-loop suppression: block empty ack messages between agents
    # Catches codex<->codex_2 ping-pong ("Nachricht X verarbeitet" loops)
    if (
        sender not in _BROADCAST_DEDUP_EXEMPT
        and recipient not in _broadcast_recipients
        and recipient not in _BROADCAST_DEDUP_EXEMPT
        and _is_echo_ack_message(content)
    ):
        print(f"[echo-loop] Suppressed empty ack from {sender}\u2192{recipient}: {content[:60]}")
        return {
            "id": None,
            "from": sender,
            "to": recipient,
            "content": content,
            "timestamp": _utc_now_iso(),  # type: ignore[misc]
            "suppressed": True,
        }

    msg: dict[str, Any] = {
        "id": None,
        "from": sender,
        "to": recipient,
        "content": content,
        "timestamp": _utc_now_iso(),  # type: ignore[misc]
    }
    if isinstance(meta, dict):
        msg["meta"] = meta
    if reply_to is not None:
        msg["reply_to"] = reply_to
    if channel:
        msg["channel"] = channel
    if team:
        msg["team"] = team

    with _COND:
        msg["id"] = _msg_id_counter
        _msg_id_counter += 1
        _MESSAGES.append(msg)
        # Cap in-memory messages to prevent unbounded growth
        if len(_MESSAGES) > 50_000:
            removed = len(_MESSAGES) - 25_000
            _MESSAGES[:] = _MESSAGES[-25_000:]
            # Adjust all cursors so they still point to valid indices
            for aid in list(_CURSORS):
                _CURSORS[aid] = max(0, _CURSORS[aid] - removed)
        persist_message(msg)
        _COND.notify_all()

    # Hardening (C3): Push to relevant WebSocket clients (targeted for agents, broadcast for UI)
    _ws_broadcast_message(msg)  # type: ignore[misc]

    # Non-MCP Direct Push: immediate tmux notification for Codex/Qwen/Gemini
    if not msg.get("suppressed"):
        _push_non_mcp_notification(msg)  # type: ignore[misc]

    if not suppress_team_lead:
        intervention = _maybe_team_lead_intervene(msg)  # type: ignore[misc]
        if intervention:
            append_message(
                sender=str(intervention["from"]),
                recipient=str(intervention["to"]),
                content=str(intervention["content"]),
                meta=intervention.get("meta") if isinstance(intervention.get("meta"), dict) else None,
                suppress_team_lead=True,
            )

    return msg


def messages_for_agent(from_index: int, agent_id: str, team_filter: str | None = None) -> list[dict[str, Any]]:
    subset: list[dict[str, Any]] = []
    _is_mgmt: bool | None = None  # lazy-evaluated
    for msg in _MESSAGES[from_index:]:
        # Team filter: if requested, only return messages with matching team field
        if team_filter:
            if msg.get("team") != team_filter:
                continue
        target = str(msg.get("to", "")).strip()
        if target == "all_managers":
            if _is_mgmt is None:
                _is_mgmt = _is_management_agent(agent_id)  # type: ignore[misc]
            if not _is_mgmt:
                continue
        elif target.startswith("team:"):
            # team:X broadcast — deliver to all members of team X
            team_id = target[len("team:"):]
            members = _get_team_members(team_id)  # type: ignore[misc]
            if agent_id not in members:
                continue
        elif target not in {agent_id, "all"}:
            continue
        # Channel filtering: if message has a channel, only deliver to team members
        msg_channel = msg.get("channel")
        if msg_channel and target == "all":
            team_members = _get_team_members(str(msg_channel))  # type: ignore[misc]
            if team_members and agent_id not in team_members:
                continue
        subset.append(msg)
    return subset


def cursor_index_after_message_id(last_message_id: Any) -> int | None:
    """Translate a persisted message ID into the next unread list index.

    The live /receive endpoint uses list indices in `_CURSORS`, while persisted
    agent state stores `last_message_id_received`. This helper bridges both
    representations without altering cursor state itself.
    """
    try:
        target_id = int(last_message_id)
    except (TypeError, ValueError):
        return None

    with _COND:
        for index, msg in enumerate(_MESSAGES):
            try:
                msg_id = int(msg.get("id", -1))
            except (TypeError, ValueError):
                continue
            if msg_id > target_id:
                return index
        return len(_MESSAGES)
