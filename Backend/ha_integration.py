"""
ha_integration.py — Home Assistant Integration

Provides a bridge between AI agents and Home Assistant for smart home
control. Wraps the HA REST API with safety checks and approval gates.

Architecture Reference: R3_RealWorld_Capabilities.md
Phase: B — Capabilities

Features:
  - Entity state querying (lights, sensors, climate, etc.)
  - Service calls (turn on/off, set temperature, etc.)
  - Entity search and discovery
  - Safety classification (safe vs. approval-required actions)
  - Action logging for audit trail
  - Connection health checking

Design:
  - No HA SDK dependency — pure HTTP via urllib
  - Approval-required for destructive/physical actions
  - Read-only operations always allowed
  - Thread-safe
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HA_URL = "http://homeassistant.local:8123"
DEFAULT_TIMEOUT = 10  # seconds

# Safe domains — read-only or non-destructive
SAFE_DOMAINS: frozenset[str] = frozenset({
    "sensor", "binary_sensor", "weather", "sun", "zone",
    "person", "device_tracker", "input_number", "input_text",
    "input_boolean", "input_select", "input_datetime",
    "counter", "timer", "calendar",
})

# Approval-required domains — physical actions
APPROVAL_DOMAINS: frozenset[str] = frozenset({
    "lock", "alarm_control_panel", "cover", "garage_door",
    "valve", "siren", "camera",
})


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionSafety(Enum):
    """Safety classification for HA actions."""

    SAFE = "safe"                    # No approval needed
    CAUTION = "caution"              # Logged, but allowed
    APPROVAL_REQUIRED = "approval_required"  # Requires human approval


class HAConnectionStatus(Enum):
    """HA connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class HAEntity:
    """Represents a Home Assistant entity."""

    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: str = ""
    last_updated: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0] if "." in self.entity_id else ""

    @property
    def friendly_name(self) -> str:
        return self.attributes.get("friendly_name", self.entity_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "domain": self.domain,
            "friendly_name": self.friendly_name,
            "attributes": self.attributes,
            "last_changed": self.last_changed,
            "last_updated": self.last_updated,
        }


@dataclass
class HAAction:
    """An action to execute on Home Assistant."""

    domain: str
    service: str
    entity_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def full_service(self) -> str:
        return f"{self.domain}.{self.service}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "service": self.service,
            "full_service": self.full_service,
            "entity_id": self.entity_id,
            "data": self.data,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


@dataclass
class HAActionResult:
    """Result of a HA action execution."""

    success: bool
    action: HAAction
    safety: ActionSafety
    response: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action.to_dict(),
            "safety": self.safety.value,
            "response": self.response,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Home Assistant Client
# ---------------------------------------------------------------------------

class HAClient:
    """Home Assistant integration client.

    Provides safe access to Home Assistant's REST API with
    action classification, approval gates, and audit logging.
    """

    def __init__(
        self,
        url: str = DEFAULT_HA_URL,
        token: str = "",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize HA client.

        Args:
            url: Home Assistant base URL.
            token: Long-lived access token.
            timeout: Request timeout in seconds.
        """
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._action_log: list[HAAction] = []
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Connection
    # -------------------------------------------------------------------

    def check_connection(self) -> HAConnectionStatus:
        """Check connection to Home Assistant.

        Returns:
            Connection status.
        """
        if not self._token:
            return HAConnectionStatus.DISCONNECTED

        try:
            result = self._api_get("/api/")
            if result is not None:
                return HAConnectionStatus.CONNECTED
            return HAConnectionStatus.DISCONNECTED
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return HAConnectionStatus.AUTH_FAILED
            return HAConnectionStatus.DISCONNECTED
        except Exception:
            return HAConnectionStatus.DISCONNECTED

    # -------------------------------------------------------------------
    # Entity Queries (Always Safe)
    # -------------------------------------------------------------------

    def get_states(self) -> list[HAEntity]:
        """Get all entity states.

        Returns:
            List of HAEntity objects.
        """
        data = self._api_get("/api/states")
        if data is None:
            return []
        return [self._parse_entity(e) for e in data if isinstance(e, dict)]

    def get_state(self, entity_id: str) -> HAEntity | None:
        """Get state of a specific entity.

        Args:
            entity_id: Entity identifier (e.g., "light.living_room").

        Returns:
            HAEntity if found, None otherwise.
        """
        data = self._api_get(f"/api/states/{entity_id}")
        if data is None:
            return None
        return self._parse_entity(data)

    def search_entities(
        self,
        query: str = "",
        domain: str = "",
    ) -> list[HAEntity]:
        """Search for entities by name or domain.

        Args:
            query: Search text (matches entity_id and friendly_name).
            domain: Filter by domain (e.g., "light", "sensor").

        Returns:
            Matching entities.
        """
        entities = self.get_states()
        results = []

        for entity in entities:
            if domain and entity.domain != domain:
                continue
            if query:
                query_lower = query.lower()
                if (query_lower not in entity.entity_id.lower()
                        and query_lower not in entity.friendly_name.lower()):
                    continue
            results.append(entity)

        return results

    def get_domains(self) -> list[str]:
        """Get all unique entity domains.

        Returns:
            Sorted list of domain strings.
        """
        entities = self.get_states()
        domains = set(e.domain for e in entities if e.domain)
        return sorted(domains)

    # -------------------------------------------------------------------
    # Service Calls (Safety-Classified)
    # -------------------------------------------------------------------

    def classify_action(self, action: HAAction) -> ActionSafety:
        """Classify the safety level of an action.

        Args:
            action: The action to classify.

        Returns:
            ActionSafety classification.
        """
        domain = action.entity_id.split(".")[0] if action.entity_id else action.domain

        if domain in APPROVAL_DOMAINS:
            return ActionSafety.APPROVAL_REQUIRED

        if domain in SAFE_DOMAINS:
            return ActionSafety.SAFE

        # Default: caution for unknown domains
        return ActionSafety.CAUTION

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str = "",
        data: dict[str, Any] | None = None,
        agent_id: str = "",
        skip_safety: bool = False,
    ) -> HAActionResult:
        """Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., "light").
            service: Service name (e.g., "turn_on").
            entity_id: Target entity.
            data: Additional service data.
            agent_id: Agent making the call.
            skip_safety: Skip safety classification (for pre-approved actions).

        Returns:
            HAActionResult with success/failure and safety classification.
        """
        action = HAAction(
            domain=domain,
            service=service,
            entity_id=entity_id,
            data=data or {},
            agent_id=agent_id,
        )

        # Classify safety
        safety = ActionSafety.SAFE if skip_safety else self.classify_action(action)

        # Block approval-required actions
        if safety == ActionSafety.APPROVAL_REQUIRED:
            return HAActionResult(
                success=False,
                action=action,
                safety=safety,
                error="Action requires human approval. Use approval_gate to request.",
            )

        # Log action
        with self._lock:
            self._action_log.append(action)

        # Build service call payload
        payload: dict[str, Any] = {}
        if entity_id:
            payload["entity_id"] = entity_id
        if data:
            payload.update(data)

        # Execute
        try:
            result = self._api_post(
                f"/api/services/{domain}/{service}",
                payload,
            )
            return HAActionResult(
                success=True,
                action=action,
                safety=safety,
                response=result or {},
            )
        except Exception as e:
            return HAActionResult(
                success=False,
                action=action,
                safety=safety,
                error=str(e),
            )

    # -------------------------------------------------------------------
    # Action Log
    # -------------------------------------------------------------------

    def get_action_log(
        self,
        limit: int = 50,
        agent_id: str = "",
    ) -> list[HAAction]:
        """Get recent action log.

        Args:
            limit: Maximum entries.
            agent_id: Filter by agent. Empty = all.

        Returns:
            List of HAAction entries (newest first).
        """
        with self._lock:
            log = list(reversed(self._action_log))
        if agent_id:
            log = [a for a in log if a.agent_id == agent_id]
        return log[:limit]

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return integration status summary."""
        return {
            "url": self._url,
            "has_token": bool(self._token),
            "connection": self.check_connection().value if self._token else "not_configured",
            "total_actions": len(self._action_log),
            "safe_domains": sorted(SAFE_DOMAINS),
            "approval_domains": sorted(APPROVAL_DOMAINS),
        }

    # -------------------------------------------------------------------
    # Internal HTTP
    # -------------------------------------------------------------------

    def _api_get(self, path: str) -> Any:
        """GET request to HA API."""
        url = f"{self._url}{path}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    def _api_post(self, path: str, data: dict[str, Any]) -> Any:
        """POST request to HA API."""
        url = f"{self._url}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    @staticmethod
    def _parse_entity(data: dict[str, Any]) -> HAEntity:
        """Parse a HA state dict into HAEntity."""
        return HAEntity(
            entity_id=data.get("entity_id", ""),
            state=data.get("state", "unknown"),
            attributes=data.get("attributes", {}),
            last_changed=data.get("last_changed", ""),
            last_updated=data.get("last_updated", ""),
        )
