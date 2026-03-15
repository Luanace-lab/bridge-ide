from __future__ import annotations

import secrets
import time
from typing import Any, Callable

_bridge_user_token_getter: Callable[[], str] = lambda: ""
_ui_session_token_getter: Callable[[], str] = lambda: ""
_platform_operator_agents_getter: Callable[[], set[str]] = lambda: set()
_agent_state_lock: Any = None
_session_tokens: dict[str, str] = {}
_grace_tokens: dict[str, tuple[str, float]] = {}
_auth_tier2_get_paths: set[str] = set()
_auth_tier2_get_patterns: tuple[Any, ...] = ()
_auth_tier2_post_paths: set[str] = set()
_auth_tier3_post_paths: set[str] = set()
_auth_tier3_patterns: tuple[Any, ...] = ()
_auth_tier2_patterns: tuple[Any, ...] = ()


def init(
    *,
    bridge_user_token_getter: Callable[[], str],
    ui_session_token_getter: Callable[[], str],
    platform_operator_agents_getter: Callable[[], set[str]],
    agent_state_lock: Any,
    session_tokens: dict[str, str],
    grace_tokens: dict[str, tuple[str, float]],
    auth_tier2_get_paths: set[str],
    auth_tier2_get_patterns: tuple[Any, ...],
    auth_tier2_post_paths: set[str],
    auth_tier3_post_paths: set[str],
    auth_tier3_patterns: tuple[Any, ...],
    auth_tier2_patterns: tuple[Any, ...],
) -> None:
    global _bridge_user_token_getter
    global _ui_session_token_getter
    global _platform_operator_agents_getter
    global _agent_state_lock
    global _session_tokens
    global _grace_tokens
    global _auth_tier2_get_paths
    global _auth_tier2_get_patterns
    global _auth_tier2_post_paths
    global _auth_tier3_post_paths
    global _auth_tier3_patterns
    global _auth_tier2_patterns

    _bridge_user_token_getter = bridge_user_token_getter
    _ui_session_token_getter = ui_session_token_getter
    _platform_operator_agents_getter = platform_operator_agents_getter
    _agent_state_lock = agent_state_lock
    _session_tokens = session_tokens
    _grace_tokens = grace_tokens
    _auth_tier2_get_paths = auth_tier2_get_paths
    _auth_tier2_get_patterns = auth_tier2_get_patterns
    _auth_tier2_post_paths = auth_tier2_post_paths
    _auth_tier3_post_paths = auth_tier3_post_paths
    _auth_tier3_patterns = auth_tier3_patterns
    _auth_tier2_patterns = auth_tier2_patterns


def _extract_auth_token(self) -> str:
    token = str(self.headers.get("X-Bridge-Token", "")).strip()
    if token:
        return token
    auth = str(self.headers.get("Authorization", "")).strip()
    if len(auth) > 7 and auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return ""


def _resolve_auth_identity(self) -> tuple[str, str | None]:
    token = self._extract_auth_token()
    if not token:
        return ("none", None)

    bridge_user_token = _bridge_user_token_getter()
    if bridge_user_token and secrets.compare_digest(token, bridge_user_token):
        return ("user", "user")

    ui_session_token = _ui_session_token_getter()
    if ui_session_token and secrets.compare_digest(token, ui_session_token):
        return ("user", "ui")

    with _agent_state_lock:
        agent_id = _session_tokens.get(token)
    if agent_id:
        return ("agent", agent_id)

    grace_entry = _grace_tokens.get(token)
    if grace_entry:
        grace_agent_id, grace_expiry = grace_entry
        if time.time() < grace_expiry:
            return ("agent", grace_agent_id)
        _grace_tokens.pop(token, None)

    return ("invalid", None)


def _require_authenticated(
    self, *, allow_user: bool = True, allow_agent: bool = True
) -> tuple[bool, str, str | None]:
    role, identity = self._resolve_auth_identity()
    if role == "none":
        self._respond(401, {"error": "authentication required"})
        return (False, role, identity)
    if role == "invalid":
        self._respond(403, {"error": "invalid token"})
        return (False, role, identity)
    if role == "user" and not allow_user:
        self._respond(403, {"error": "user token not allowed"})
        return (False, role, identity)
    if role == "agent" and not allow_agent:
        self._respond(403, {"error": "agent token not allowed"})
        return (False, role, identity)
    return (True, role, identity)


def _require_platform_operator(
    self, *, allow_user: bool = True
) -> tuple[bool, str, str | None]:
    ok, role, identity = self._require_authenticated(allow_user=allow_user, allow_agent=True)
    if not ok:
        return (False, role, identity)
    if role == "agent" and identity not in _platform_operator_agents_getter():
        self._respond(403, {"error": "agent is not allowed to use platform operator endpoints"})
        return (False, role, identity)
    return (True, role, identity)


def _path_requires_auth_get(self, path: str) -> bool:
    if path in _auth_tier2_get_paths:
        return True
    for pat in _auth_tier2_get_patterns:
        if pat.match(path):
            return True
    return False


def _path_requires_auth_post(self, path: str) -> bool:
    if path in _auth_tier2_post_paths:
        return True
    if path in _auth_tier3_post_paths:
        return True
    for pat in _auth_tier3_patterns:
        if pat.match(path):
            return True
    for pat in _auth_tier2_patterns:
        if pat.match(path):
            return True
    return False
