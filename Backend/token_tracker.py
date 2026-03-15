"""
Token Tracker — Append-only JSONL logging + cost calculation + aggregation.

Tracks token usage per agent, engine, model. Provides cost estimates
based on a centralized price table. Queried by GET /metrics/tokens and
GET /metrics/costs endpoints in server.py.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("token_tracker")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
TOKEN_LOG_FILE = os.path.join(LOG_DIR, "token_log.jsonl")

# ---------------------------------------------------------------------------
# Price table: cost per 1M tokens (input / output) in USD
# ---------------------------------------------------------------------------
MODEL_PRICES: dict[str, dict[str, float]] = {
    # Claude
    "claude-opus-4-6":            {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":          {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001":  {"input": 0.80,  "output": 4.0},
    # Codex / OpenAI
    "o4-mini":                    {"input": 1.10,  "output": 4.40},
    "codex-mini-latest":          {"input": 1.50,  "output": 6.0},
    "o3":                         {"input": 10.0,  "output": 40.0},
    # Gemini
    "gemini-2.5-pro":             {"input": 1.25,  "output": 10.0},
    "gemini-2.5-flash":           {"input": 0.15,  "output": 0.60},
    # Qwen
    "qwen3-coder":                {"input": 0.50,  "output": 2.0},
}

# Fallback for unknown models
_DEFAULT_PRICE = {"input": 5.0, "output": 20.0}

_WRITE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------
def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Calculate cost in USD. Cached tokens are charged at 10% of input price."""
    prices = MODEL_PRICES.get(model, _DEFAULT_PRICE)
    billable_input = max(input_tokens - cached_tokens, 0)
    cached_cost = cached_tokens * prices["input"] * 0.1 / 1_000_000
    input_cost = billable_input * prices["input"] / 1_000_000
    output_cost = output_tokens * prices["output"] / 1_000_000
    return round(input_cost + cached_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log_usage(
    agent_id: str,
    engine: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Append a token usage entry to token_log.jsonl. Returns the entry."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    cost = calculate_cost(model, input_tokens, output_tokens, cached_tokens)
    entry = {
        "agent_id": agent_id,
        "engine": engine,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost,
        "timestamp": ts,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with _WRITE_LOCK:
            with open(TOKEN_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("Failed to write token log: %s", exc)
    return entry


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _parse_period(period: str) -> datetime:
    """Return the cutoff datetime for a period string."""
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    if period == "all":
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _read_entries(since: datetime, agent_id: str = "") -> list[dict[str, Any]]:
    """Read token_log.jsonl entries since cutoff, optionally filtered by agent."""
    entries: list[dict[str, Any]] = []
    if not os.path.exists(TOKEN_LOG_FILE):
        return entries
    try:
        with open(TOKEN_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    continue
                if ts < since:
                    continue
                if agent_id and entry.get("agent_id") != agent_id:
                    continue
                entries.append(entry)
    except OSError:
        pass
    return entries


def get_token_metrics(agent_id: str = "", period: str = "today") -> dict[str, Any]:
    """Aggregate token metrics for a period.

    Returns: {period, agent_id, total_input, total_output, total_cached,
              total_cost_usd, entries_count, by_model: {model: {input, output, cost}}}
    """
    since = _parse_period(period)
    entries = _read_entries(since, agent_id)

    total_input = 0
    total_output = 0
    total_cached = 0
    total_cost = 0.0
    by_model: dict[str, dict[str, Any]] = {}

    for e in entries:
        inp = e.get("input_tokens", 0)
        out = e.get("output_tokens", 0)
        cached = e.get("cached_tokens", 0)
        cost = e.get("cost_usd", 0.0)
        model = e.get("model", "unknown")

        total_input += inp
        total_output += out
        total_cached += cached
        total_cost += cost

        if model not in by_model:
            by_model[model] = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "count": 0}
        by_model[model]["input_tokens"] += inp
        by_model[model]["output_tokens"] += out
        by_model[model]["cached_tokens"] += cached
        by_model[model]["cost_usd"] += cost
        by_model[model]["count"] += 1

    # Round costs
    for m in by_model.values():
        m["cost_usd"] = round(m["cost_usd"], 4)

    return {
        "period": period,
        "agent_id": agent_id or "all",
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cached_tokens": total_cached,
        "total_cost_usd": round(total_cost, 4),
        "entries_count": len(entries),
        "by_model": by_model,
    }


def get_cost_summary(period: str = "today") -> dict[str, Any]:
    """Cost summary across all agents.

    Returns: {period, total_cost_usd, by_agent: {agent: {cost, input, output}},
              top_agents: [{agent, cost}]}
    """
    since = _parse_period(period)
    entries = _read_entries(since)

    total_cost = 0.0
    by_agent: dict[str, dict[str, Any]] = {}

    for e in entries:
        agent = e.get("agent_id", "unknown")
        cost = e.get("cost_usd", 0.0)
        inp = e.get("input_tokens", 0)
        out = e.get("output_tokens", 0)
        total_cost += cost

        if agent not in by_agent:
            by_agent[agent] = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "requests": 0}
        by_agent[agent]["cost_usd"] += cost
        by_agent[agent]["input_tokens"] += inp
        by_agent[agent]["output_tokens"] += out
        by_agent[agent]["requests"] += 1

    for a in by_agent.values():
        a["cost_usd"] = round(a["cost_usd"], 4)

    top_agents = sorted(by_agent.items(), key=lambda x: x[1]["cost_usd"], reverse=True)[:10]

    return {
        "period": period,
        "total_cost_usd": round(total_cost, 4),
        "agent_count": len(by_agent),
        "by_agent": by_agent,
        "top_agents": [{"agent_id": a, "cost_usd": d["cost_usd"]} for a, d in top_agents],
    }
