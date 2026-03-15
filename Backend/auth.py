"""
auth.py — API Authentication and Authorization

Provides API key and token-based authentication for the Bridge platform.
Supports agent-level and user-level access control.

Phase: Platform Security

Features:
  - API key generation and validation
  - Agent-scoped permissions (read, write, admin)
  - Rate limiting per API key
  - Key rotation support
  - Audit logging of auth events
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "bridge_"
API_KEY_LENGTH = 32  # Bytes of randomness
KEY_HASH_ALGO = "sha256"
DEFAULT_RATE_LIMIT = 100  # Requests per minute
RATE_WINDOW = 60.0  # Seconds


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Permission(Enum):
    """Access permission levels."""

    READ = "read"           # Read messages, status, history
    WRITE = "write"         # Send messages, register agents
    ADMIN = "admin"         # Manage keys, cleanup, configuration
    AGENT = "agent"         # Full agent operations


class AuthResult(Enum):
    """Authentication result codes."""

    OK = "ok"
    INVALID_KEY = "invalid_key"
    EXPIRED_KEY = "expired_key"
    RATE_LIMITED = "rate_limited"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    MISSING_KEY = "missing_key"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class APIKey:
    """An API key with metadata and permissions."""

    key_id: str                    # Short identifier
    key_hash: str                  # SHA-256 hash of the full key
    owner: str                     # Owner identifier (agent_id or user)
    permissions: set[Permission] = field(default_factory=lambda: {Permission.READ, Permission.WRITE})
    rate_limit: int = DEFAULT_RATE_LIMIT
    created_at: float = 0.0
    expires_at: float = 0.0        # 0 = never expires
    revoked: bool = False
    description: str = ""

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.revoked and not self.is_expired

    def has_permission(self, perm: Permission) -> bool:
        if Permission.ADMIN in self.permissions:
            return True  # Admin has all permissions
        return perm in self.permissions

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "owner": self.owner,
            "permissions": sorted(p.value for p in self.permissions),
            "rate_limit": self.rate_limit,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "is_valid": self.is_valid,
            "description": self.description,
        }


@dataclass
class AuthEvent:
    """Audit log entry for auth events."""

    timestamp: float
    event_type: str       # "auth_success", "auth_failure", "key_created", etc.
    key_id: str
    owner: str
    result: str           # AuthResult value
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "key_id": self.key_id,
            "owner": self.owner,
            "result": self.result,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(self):
        self._windows: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key_id: str, limit: int) -> bool:
        """Check if request is within rate limit.

        Args:
            key_id: API key identifier.
            limit: Max requests per window.

        Returns:
            True if within limit, False if rate limited.
        """
        now = time.time()
        cutoff = now - RATE_WINDOW

        with self._lock:
            if key_id not in self._windows:
                self._windows[key_id] = []

            # Remove expired entries
            self._windows[key_id] = [
                t for t in self._windows[key_id] if t > cutoff
            ]

            if len(self._windows[key_id]) >= limit:
                return False

            self._windows[key_id].append(now)
            return True

    def reset(self, key_id: str) -> None:
        """Reset rate limit counter for a key."""
        with self._lock:
            self._windows.pop(key_id, None)


# ---------------------------------------------------------------------------
# Auth Manager
# ---------------------------------------------------------------------------

class AuthManager:
    """Manages API key authentication and authorization.

    Handles key generation, validation, permission checks,
    rate limiting, and audit logging.
    """

    def __init__(self, audit_limit: int = 1000) -> None:
        """Initialize auth manager.

        Args:
            audit_limit: Maximum audit log entries to keep in memory.
        """
        self._keys: dict[str, APIKey] = {}  # key_hash → APIKey
        self._key_id_index: dict[str, str] = {}  # key_id → key_hash
        self._rate_limiter = _RateLimiter()
        self._audit_log: list[AuthEvent] = []
        self._audit_limit = audit_limit
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Key Management
    # -------------------------------------------------------------------

    def create_key(
        self,
        owner: str,
        permissions: set[Permission] | None = None,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        expires_in: float = 0.0,
        description: str = "",
    ) -> tuple[str, APIKey]:
        """Create a new API key.

        Args:
            owner: Key owner identifier.
            permissions: Set of permissions. Defaults to READ + WRITE.
            rate_limit: Max requests per minute.
            expires_in: Seconds until expiration. 0 = never expires.
            description: Human-readable description.

        Returns:
            Tuple of (raw_key_string, APIKey metadata).

        Raises:
            ValueError: If owner is empty.
        """
        if not owner:
            raise ValueError("Owner must not be empty")

        # Generate random key
        random_bytes = os.urandom(API_KEY_LENGTH)
        key_hex = random_bytes.hex()
        raw_key = f"{API_KEY_PREFIX}{key_hex}"

        # Hash for storage
        key_hash = self._hash_key(raw_key)
        key_id = f"key_{key_hex[:8]}"

        expires_at = 0.0
        if expires_in > 0:
            expires_at = time.time() + expires_in

        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            owner=owner,
            permissions=permissions or {Permission.READ, Permission.WRITE},
            rate_limit=rate_limit,
            expires_at=expires_at,
            description=description,
        )

        with self._lock:
            self._keys[key_hash] = api_key
            self._key_id_index[key_id] = key_hash

        self._log_event("key_created", key_id, owner, AuthResult.OK.value)
        return raw_key, api_key

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key.

        Args:
            key_id: Key identifier to revoke.

        Returns:
            True if key was found and revoked.
        """
        with self._lock:
            key_hash = self._key_id_index.get(key_id)
            if key_hash is None:
                return False
            api_key = self._keys.get(key_hash)
            if api_key is None:
                return False
            api_key.revoked = True

        self._log_event("key_revoked", key_id, api_key.owner, AuthResult.OK.value)
        return True

    def get_key_info(self, key_id: str) -> APIKey | None:
        """Get API key metadata by key_id.

        Args:
            key_id: Key identifier.

        Returns:
            APIKey if found, None otherwise.
        """
        key_hash = self._key_id_index.get(key_id)
        if key_hash is None:
            return None
        return self._keys.get(key_hash)

    def list_keys(self, owner: str | None = None) -> list[APIKey]:
        """List all API keys, optionally filtered by owner.

        Args:
            owner: Filter by owner. None = all keys.

        Returns:
            List of APIKey objects.
        """
        keys = list(self._keys.values())
        if owner:
            keys = [k for k in keys if k.owner == owner]
        return keys

    # -------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------

    def authenticate(
        self,
        raw_key: str,
        required_permission: Permission = Permission.READ,
    ) -> tuple[AuthResult, APIKey | None]:
        """Authenticate a request with an API key.

        Validates the key, checks permissions, and enforces rate limits.

        Args:
            raw_key: The raw API key string.
            required_permission: Minimum required permission.

        Returns:
            Tuple of (AuthResult, APIKey if successful).
        """
        if not raw_key:
            self._log_event("auth_attempt", "", "", AuthResult.MISSING_KEY.value)
            return AuthResult.MISSING_KEY, None

        key_hash = self._hash_key(raw_key)
        api_key = self._keys.get(key_hash)

        if api_key is None:
            self._log_event("auth_failure", "", "", AuthResult.INVALID_KEY.value)
            return AuthResult.INVALID_KEY, None

        if api_key.revoked:
            self._log_event(
                "auth_failure", api_key.key_id, api_key.owner,
                AuthResult.INVALID_KEY.value, "Key revoked",
            )
            return AuthResult.INVALID_KEY, None

        if api_key.is_expired:
            self._log_event(
                "auth_failure", api_key.key_id, api_key.owner,
                AuthResult.EXPIRED_KEY.value,
            )
            return AuthResult.EXPIRED_KEY, None

        if not api_key.has_permission(required_permission):
            self._log_event(
                "auth_failure", api_key.key_id, api_key.owner,
                AuthResult.INSUFFICIENT_PERMISSIONS.value,
                f"Required: {required_permission.value}",
            )
            return AuthResult.INSUFFICIENT_PERMISSIONS, None

        if not self._rate_limiter.check(api_key.key_id, api_key.rate_limit):
            self._log_event(
                "auth_failure", api_key.key_id, api_key.owner,
                AuthResult.RATE_LIMITED.value,
            )
            return AuthResult.RATE_LIMITED, None

        self._log_event(
            "auth_success", api_key.key_id, api_key.owner,
            AuthResult.OK.value,
        )
        return AuthResult.OK, api_key

    # -------------------------------------------------------------------
    # Audit Log
    # -------------------------------------------------------------------

    def get_audit_log(
        self,
        limit: int = 50,
        key_id: str = "",
        event_type: str = "",
    ) -> list[AuthEvent]:
        """Get audit log entries.

        Args:
            limit: Maximum entries to return.
            key_id: Filter by key_id. Empty = all.
            event_type: Filter by event type. Empty = all.

        Returns:
            List of AuthEvent entries (newest first).
        """
        events = list(reversed(self._audit_log))
        if key_id:
            events = [e for e in events if e.key_id == key_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[:limit]

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return auth system status summary."""
        keys = list(self._keys.values())
        return {
            "total_keys": len(keys),
            "active_keys": sum(1 for k in keys if k.is_valid),
            "revoked_keys": sum(1 for k in keys if k.revoked),
            "expired_keys": sum(1 for k in keys if k.is_expired),
            "audit_log_size": len(self._audit_log),
            "owners": sorted(set(k.owner for k in keys)),
        }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        """Hash an API key for secure storage."""
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def _log_event(
        self,
        event_type: str,
        key_id: str,
        owner: str,
        result: str,
        details: str = "",
    ) -> None:
        """Log an auth event."""
        event = AuthEvent(
            timestamp=time.time(),
            event_type=event_type,
            key_id=key_id,
            owner=owner,
            result=result,
            details=details,
        )
        with self._lock:
            self._audit_log.append(event)
            if len(self._audit_log) > self._audit_limit:
                self._audit_log = self._audit_log[-self._audit_limit:]
