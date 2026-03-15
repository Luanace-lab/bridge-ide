"""
Workflow Bot — Deterministic intent detection for chat-based workflow management.

Detects workflow-related intents in chat messages using keyword matching.
No LLM — purely deterministic, fast, predictable.

Used by server.py POST /send handler for auto-responses when users
message "@auto" or mention workflow keywords.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger("workflow_bot")

# ---------------------------------------------------------------------------
# Keyword sets (German + English)
# ---------------------------------------------------------------------------
_CREATE_KEYWORDS = [
    "automatisierung erstellen", "workflow erstellen", "workflow anlegen",
    "erstelle automatisierung", "erstelle workflow", "neue automatisierung",
    "neuer workflow", "benachrichtige mich", "benachrichtigung einrichten",
    "email wenn", "alarm wenn", "alert wenn",
    "jeden tag", "jeden morgen", "jede woche", "report erstellen",
    "informiere mich", "bericht erstellen",
    "email benachrichtigung", "task benachrichtigung",
    "create workflow", "create automation", "notify me", "email when",
    "alert when", "every day", "every morning", "every week",
    "daily report", "weekly report", "set up notification",
    "new workflow", "new automation",
]

_LIST_KEYWORDS = [
    "welche workflows", "meine automatisierungen", "was laeuft",
    "aktive workflows", "zeige workflows", "workflow liste",
    "list workflows", "show workflows", "my automations",
    "active workflows", "what workflows", "running workflows",
]

_TOGGLE_KEYWORDS = [
    "pausiere", "stoppe", "aktiviere", "starte workflow",
    "workflow pausieren", "workflow stoppen", "workflow aktivieren",
    "pause workflow", "stop workflow", "activate workflow",
    "enable workflow", "disable workflow", "start workflow",
]

_DELETE_KEYWORDS = [
    "loesche workflow", "entferne automatisierung", "workflow entfernen",
    "workflow loeschen", "automatisierung loeschen",
    "delete workflow", "remove workflow", "remove automation",
    "delete automation",
]

# ---------------------------------------------------------------------------
# Template metadata (loaded once, cached)
# ---------------------------------------------------------------------------
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow_templates")
_TEMPLATE_CACHE: list[dict[str, Any]] | None = None


def _load_templates() -> list[dict[str, Any]]:
    """Load template metadata from workflow_templates/ directory."""
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    templates: list[dict[str, Any]] = []
    if not os.path.isdir(TEMPLATES_DIR):
        _TEMPLATE_CACHE = templates
        return templates

    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(TEMPLATES_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                tpl = json.load(f)
            templates.append({
                "template_id": tpl.get("template_id", ""),
                "name": tpl.get("name", ""),
                "description": tpl.get("description", ""),
                "category": tpl.get("category", ""),
                "difficulty": tpl.get("difficulty", ""),
                "variables": tpl.get("variables", []),
            })
        except Exception:
            continue

    _TEMPLATE_CACHE = templates
    return templates


def invalidate_template_cache() -> None:
    """Clear template cache (call after template changes)."""
    global _TEMPLATE_CACHE
    _TEMPLATE_CACHE = None


# ---------------------------------------------------------------------------
# Template scoring — match templates to user message
# ---------------------------------------------------------------------------
_TEMPLATE_SCORING_KEYWORDS: dict[str, list[str]] = {
    "tpl_task_email": [
        "task", "aufgabe", "benachrichtigung", "notification",
        "email", "mail", "neue aufgabe", "new task",
    ],
    "tpl_daily_status": [
        "status", "taeglich", "daily", "morgen", "morning",
        "report", "bericht", "uebersicht", "overview",
    ],
    "tpl_agent_offline": [
        "agent", "offline", "ausfall", "alarm", "alert",
        "monitoring", "ueberwachung", "crash", "down",
    ],
    "tpl_chat_summary": [
        "chat", "zusammenfassung", "summary", "nachrichten",
        "messages", "kommunikation", "communication",
    ],
    "tpl_weekly_report": [
        "woche", "weekly", "wochenreport", "sprint",
        "freitag", "friday", "performance", "wochen",
    ],
}


def _score_templates(message_lower: str) -> list[dict[str, Any]]:
    """Score templates against a message. Returns sorted list with scores > 0."""
    templates = _load_templates()
    scored: list[dict[str, Any]] = []

    for tpl in templates:
        tid = tpl["template_id"]
        score = 0
        matched_keywords: list[str] = []

        # Score from keyword map
        for kw in _TEMPLATE_SCORING_KEYWORDS.get(tid, []):
            if kw in message_lower:
                score += 1
                matched_keywords.append(kw)

        # Score from template name/description
        name_lower = tpl.get("name", "").lower()
        desc_lower = tpl.get("description", "").lower()
        words = set(re.findall(r"\w{4,}", message_lower))
        for w in words:
            if w in name_lower:
                score += 1
            if w in desc_lower:
                score += 0.5

        if score > 0:
            scored.append({
                "template_id": tid,
                "name": tpl["name"],
                "description": tpl["description"],
                "category": tpl.get("category", ""),
                "difficulty": tpl.get("difficulty", ""),
                "variables": tpl.get("variables", []),
                "score": score,
                "matched_keywords": matched_keywords,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Intent detection (main API)
# ---------------------------------------------------------------------------
def _match_keywords(message_lower: str, keywords: list[str]) -> list[str]:
    """Return all keywords found in the message."""
    return [kw for kw in keywords if kw in message_lower]


def _extract_workflow_name(message: str) -> str:
    """Try to extract a workflow name from the message."""
    # Match patterns like "workflow 'name'" or 'workflow "name"'
    m = re.search(r"""(?:workflow|automatisierung)\s+['"]([^'"]+)['"]""", message, re.IGNORECASE)
    if m:
        return m.group(1)
    # Match patterns like "workflow XYZ stoppen"
    m = re.search(
        r"(?:pausiere|stoppe|aktiviere|starte|loesche|entferne|pause|stop|activate|start|delete|remove)"
        r"\s+(?:workflow|automatisierung)?\s*(.+?)(?:\s*$|\s+(?:bitte|please))",
        message, re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip().strip("'\"")
        if name and len(name) < 100:
            return name
    return ""


def detect_workflow_intent(message: str) -> dict[str, Any] | None:
    """Detect workflow intent in a chat message.

    Returns None if no intent detected, or a dict:
    - intent: "create_workflow" | "list_workflows" | "toggle_workflow" | "delete_workflow"
    - keywords_matched: list of matched keywords
    - suggested_templates: list of scored templates (for create intent)
    - workflow_name: extracted workflow name (for toggle/delete)
    """
    if not message or len(message) < 3:
        return None

    msg_lower = message.lower().strip()

    # Check DELETE first (more specific than toggle)
    delete_matches = _match_keywords(msg_lower, _DELETE_KEYWORDS)
    if delete_matches:
        return {
            "intent": "delete_workflow",
            "keywords_matched": delete_matches,
            "workflow_name": _extract_workflow_name(message),
        }

    # Check TOGGLE
    toggle_matches = _match_keywords(msg_lower, _TOGGLE_KEYWORDS)
    if toggle_matches:
        return {
            "intent": "toggle_workflow",
            "keywords_matched": toggle_matches,
            "workflow_name": _extract_workflow_name(message),
        }

    # Check LIST
    list_matches = _match_keywords(msg_lower, _LIST_KEYWORDS)
    if list_matches:
        return {
            "intent": "list_workflows",
            "keywords_matched": list_matches,
        }

    # Check CREATE
    create_matches = _match_keywords(msg_lower, _CREATE_KEYWORDS)
    if create_matches:
        scored = _score_templates(msg_lower)
        return {
            "intent": "create_workflow",
            "keywords_matched": create_matches,
            "suggested_templates": scored[:5],
        }

    return None


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------
def format_create_response(intent_result: dict[str, Any]) -> str:
    """Format a chat response for create_workflow intent."""
    templates = intent_result.get("suggested_templates", [])
    if not templates:
        all_templates = _load_templates()
        if all_templates:
            lines = ["Ich habe keine passende Vorlage gefunden. Verfuegbare Vorlagen:"]
            for i, tpl in enumerate(all_templates, 1):
                lines.append(f"  {i}. {tpl['name']} — {tpl['description'][:80]}")
            lines.append("\nAntworte mit dem Namen um eine Vorlage zu deployen.")
            return "\n".join(lines)
        return "Keine Workflow-Vorlagen verfuegbar. Erstelle eine unter /workflows/templates."

    if len(templates) == 1:
        t = templates[0]
        return (
            f"Passende Vorlage gefunden:\n"
            f"  {t['name']} — {t['description'][:100]}\n\n"
            f"Soll ich diese Vorlage deployen? Antworte mit 'ja' oder konfiguriere sie unter Workflows."
        )

    lines = [f"Ich habe {len(templates)} passende Vorlagen gefunden:"]
    for i, t in enumerate(templates, 1):
        lines.append(f"  {i}. {t['name']} — {t['description'][:80]}")
    lines.append("\nAntworte mit der Nummer oder dem Namen um eine Vorlage zu deployen.")
    return "\n".join(lines)


def format_list_response(workflows: list[dict[str, Any]]) -> str:
    """Format a chat response listing workflows."""
    if not workflows:
        return "Keine Workflows gefunden. Erstelle einen neuen mit 'workflow erstellen'."

    active = [w for w in workflows if w.get("active")]
    inactive = [w for w in workflows if not w.get("active")]

    lines = [f"{len(workflows)} Workflows gefunden:"]
    if active:
        lines.append(f"\nAktiv ({len(active)}):")
        for w in active:
            lines.append(f"  - {w.get('name', '?')} (ID: {w.get('id', '?')})")
    if inactive:
        lines.append(f"\nInaktiv ({len(inactive)}):")
        for w in inactive:
            lines.append(f"  - {w.get('name', '?')} (ID: {w.get('id', '?')})")

    return "\n".join(lines)


def format_toggle_response(workflow_name: str) -> str:
    """Format a chat response for toggle intent."""
    if workflow_name:
        return (
            f"Workflow '{workflow_name}' umschalten?\n"
            f"Nutze die Workflow-Verwaltung unter /workflows oder antworte mit 'ja'."
        )
    return "Welchen Workflow moechtest du umschalten? Nenne den Namen oder die ID."


def format_delete_response(workflow_name: str) -> str:
    """Format a chat response for delete intent."""
    if workflow_name:
        return (
            f"Workflow '{workflow_name}' wirklich loeschen?\n"
            f"Das kann nicht rueckgaengig gemacht werden. Antworte mit 'ja loeschen' zur Bestaetigung."
        )
    return "Welchen Workflow moechtest du loeschen? Nenne den Namen oder die ID."
