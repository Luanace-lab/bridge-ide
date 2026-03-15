"""
engine_routing.py — Smart Engine Routing

Selects the best engine for a task based on routing rules,
availability, cost optimization, and fallback chains.

Architecture Reference: R5_Integration_Roadmap.md C5
Phase: C — Intelligence

Features:
  - Rule-based routing (task category → preferred engine)
  - Fallback chains when primary engine unavailable
  - Cost-aware selection (prefer cheaper models for simple tasks)
  - Health-aware routing (skip engines with errors)
  - Custom routing rules via configuration
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine_abc import ENGINE_REGISTRY


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TaskCategory(Enum):
    """Task categories for routing decisions."""

    CODE_REVIEW = "code_review"
    CODE_GENERATION = "code_generation"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"
    QUICK_TASK = "quick_task"
    CONVERSATION = "conversation"
    ANALYSIS = "analysis"
    TRANSLATION = "translation"
    DEFAULT = "default"


# Default routing rules: category → ordered list of engine preferences
DEFAULT_ROUTING_RULES: dict[str, list[str]] = {
    "code_review": ["openai_api", "litellm", "echo"],
    "code_generation": ["openai_api", "litellm", "echo"],
    "documentation": ["gemini_api", "openai_api", "litellm", "echo"],
    "research": ["gemini_api", "openai_api", "litellm", "echo"],
    "quick_task": ["openai_api", "litellm", "echo"],
    "conversation": ["openai_api", "gemini_api", "litellm", "echo"],
    "analysis": ["openai_api", "gemini_api", "litellm", "echo"],
    "translation": ["gemini_api", "openai_api", "litellm", "echo"],
    "default": ["openai_api", "gemini_api", "litellm", "echo"],
}

# Model recommendations per category
CATEGORY_MODELS: dict[str, str] = {
    "code_review": "gpt-4o",
    "code_generation": "gpt-4o",
    "documentation": "gemini-2.0-flash",
    "research": "gemini-2.0-pro",
    "quick_task": "gpt-4o-mini",
    "conversation": "gpt-4o-mini",
    "analysis": "gpt-4o",
    "translation": "gemini-2.0-flash",
    "default": "gpt-4o",
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    engine_name: str
    model: str
    category: str
    reason: str
    fallback_chain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "model": self.model,
            "category": self.category,
            "reason": self.reason,
            "fallback_chain": self.fallback_chain,
        }


@dataclass
class EngineHealth:
    """Health snapshot for routing decisions."""

    engine_name: str
    available: bool
    error_count: int = 0
    avg_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Engine Router
# ---------------------------------------------------------------------------

class EngineRouter:
    """Smart engine routing with fallback chains.

    Routes tasks to the best available engine based on:
    - Task category routing rules
    - Engine availability and health
    - Cost optimization preferences
    - Custom overrides
    """

    def __init__(
        self,
        rules: dict[str, list[str]] | None = None,
        models: dict[str, str] | None = None,
    ) -> None:
        """Initialize router.

        Args:
            rules: Custom routing rules. Defaults to DEFAULT_ROUTING_RULES.
            models: Custom model recommendations. Defaults to CATEGORY_MODELS.
        """
        self._rules = rules or dict(DEFAULT_ROUTING_RULES)
        self._models = models or dict(CATEGORY_MODELS)
        self._health: dict[str, EngineHealth] = {}
        self._overrides: dict[str, str] = {}  # agent_id → engine_name
        self._lock = threading.Lock()

    def route(
        self,
        category: str = "default",
        agent_id: str = "",
        preferred_engine: str = "",
    ) -> RoutingDecision:
        """Select the best engine for a task.

        Args:
            category: Task category (from TaskCategory enum values).
            agent_id: Agent requesting the routing (for overrides).
            preferred_engine: Explicitly preferred engine (takes priority).

        Returns:
            RoutingDecision with selected engine and model.
        """
        # Check agent-specific override
        if agent_id and agent_id in self._overrides:
            override = self._overrides[agent_id]
            if override in ENGINE_REGISTRY:
                return RoutingDecision(
                    engine_name=override,
                    model=self._models.get(category, ""),
                    category=category,
                    reason=f"Agent override: {agent_id} → {override}",
                )

        # Check explicit preference
        if preferred_engine and preferred_engine in ENGINE_REGISTRY:
            return RoutingDecision(
                engine_name=preferred_engine,
                model=self._models.get(category, ""),
                category=category,
                reason=f"Explicit preference: {preferred_engine}",
            )

        # Get fallback chain for category
        chain = self._rules.get(category, self._rules.get("default", []))

        # Filter by availability
        for engine_name in chain:
            if engine_name not in ENGINE_REGISTRY:
                continue

            health = self._health.get(engine_name)
            if health and not health.available:
                continue

            return RoutingDecision(
                engine_name=engine_name,
                model=self._models.get(category, ""),
                category=category,
                reason=f"Rule match: {category} → {engine_name}",
                fallback_chain=[e for e in chain if e != engine_name],
            )

        # Last resort: any registered engine
        for engine_name in ENGINE_REGISTRY:
            return RoutingDecision(
                engine_name=engine_name,
                model="",
                category=category,
                reason="Last resort: first available engine",
            )

        # Nothing available
        return RoutingDecision(
            engine_name="",
            model="",
            category=category,
            reason="No engines available",
        )

    def set_health(
        self,
        engine_name: str,
        available: bool,
        error_count: int = 0,
        avg_latency_ms: float = 0.0,
    ) -> None:
        """Update engine health for routing decisions.

        Args:
            engine_name: Engine to update.
            available: Whether engine is available.
            error_count: Number of recent errors.
            avg_latency_ms: Average latency in milliseconds.
        """
        with self._lock:
            self._health[engine_name] = EngineHealth(
                engine_name=engine_name,
                available=available,
                error_count=error_count,
                avg_latency_ms=avg_latency_ms,
            )

    def set_override(self, agent_id: str, engine_name: str) -> None:
        """Set a per-agent engine override.

        Args:
            agent_id: Agent to override.
            engine_name: Engine to use for this agent.
        """
        with self._lock:
            self._overrides[agent_id] = engine_name

    def remove_override(self, agent_id: str) -> bool:
        """Remove a per-agent engine override.

        Returns:
            True if override existed and was removed.
        """
        with self._lock:
            if agent_id in self._overrides:
                del self._overrides[agent_id]
                return True
            return False

    def add_rule(self, category: str, engines: list[str]) -> None:
        """Add or update a routing rule.

        Args:
            category: Task category.
            engines: Ordered list of engine preferences.
        """
        with self._lock:
            self._rules[category] = engines

    def remove_rule(self, category: str) -> bool:
        """Remove a routing rule.

        Returns:
            True if rule existed and was removed.
        """
        with self._lock:
            if category in self._rules:
                del self._rules[category]
                return True
            return False

    def get_rules(self) -> dict[str, list[str]]:
        """Return all routing rules."""
        return dict(self._rules)

    def get_categories(self) -> list[str]:
        """Return all known task categories."""
        return sorted(self._rules.keys())

    def status(self) -> dict[str, Any]:
        """Return router status summary."""
        return {
            "rules_count": len(self._rules),
            "categories": self.get_categories(),
            "overrides": dict(self._overrides),
            "health": {
                name: {
                    "available": h.available,
                    "error_count": h.error_count,
                    "avg_latency_ms": h.avg_latency_ms,
                }
                for name, h in self._health.items()
            },
            "registered_engines": sorted(ENGINE_REGISTRY.keys()),
        }
