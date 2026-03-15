"""Legal Domain Pack — Risk Assessment.

Evaluates contract clauses against jurisdiction rules and playbook standards.
Produces structured risk reports with GREEN/YELLOW/RED classification.

Risk levels:
- GREEN: Clause is standard, no action needed
- YELLOW: Clause deviates from standard, review recommended
- RED: Clause is missing, unenforceable, or presents significant risk

Risk score = base_weight (from CUAD) + jurisdiction_modifier + playbook_modifier
Clamped to 1-5 scale. Mapped to GREEN (1-2), YELLOW (3), RED (4-5).
"""

from __future__ import annotations

from typing import Any

from domain_packs.legal.clause_types import CUAD_CLAUSE_TYPES
from domain_packs.legal.jurisdiction_rules import (
    get_jurisdiction,
    get_required_clauses,
    get_risk_modifier,
    is_clause_enforceable,
)


# ---------------------------------------------------------------------------
# Risk Classification
# ---------------------------------------------------------------------------

RISK_LEVELS = {
    1: "GREEN",
    2: "GREEN",
    3: "YELLOW",
    4: "RED",
    5: "RED",
}


def classify_risk(score: int) -> str:
    """Map numeric score (1-5) to GREEN/YELLOW/RED."""
    clamped = max(1, min(5, score))
    return RISK_LEVELS[clamped]


# ---------------------------------------------------------------------------
# Clause Risk Assessment
# ---------------------------------------------------------------------------


def assess_clause_risk(
    clause_type: str,
    jurisdiction: str,
    clause_present: bool = True,
    clause_text: str = "",
    playbook_modifier: int = 0,
) -> dict[str, Any]:
    """Assess risk for a single clause in a specific jurisdiction.

    Args:
        clause_type: CUAD clause type key
        jurisdiction: Jurisdiction code (DE, US, UK, etc.)
        clause_present: Whether the clause exists in the contract
        clause_text: The clause text (for enforceability check)
        playbook_modifier: Additional risk modifier from user's playbook (-2 to +2)

    Returns:
        Risk assessment dict with score, level, findings, recommendations.
    """
    cuad = CUAD_CLAUSE_TYPES.get(clause_type)
    if not cuad:
        return {
            "clause_type": clause_type,
            "risk_score": 3,
            "risk_level": "YELLOW",
            "findings": [f"Unknown clause type: {clause_type}"],
            "recommendations": ["Manual review required — clause type not in CUAD taxonomy"],
            "enforceable": True,
            "jurisdiction": jurisdiction,
        }

    base_weight = cuad.get("risk_weight", 3)
    j_modifier = get_risk_modifier(jurisdiction, clause_type)
    total = base_weight + j_modifier + playbook_modifier
    total = max(1, min(5, total))

    findings: list[str] = []
    recommendations: list[str] = []

    # Missing clause check
    required = get_required_clauses(jurisdiction)
    if not clause_present:
        if clause_type in required:
            total = 5  # Missing required clause = RED
            findings.append(f"MISSING: '{clause_type}' is required in {jurisdiction}")
            recommendations.append(f"Add '{clause_type}' clause — required by {jurisdiction} law")
        else:
            findings.append(f"Clause '{clause_type}' not found in contract")
            if base_weight >= 4:
                total = max(total, 4)
                recommendations.append(f"Consider adding '{clause_type}' — high-risk clause type")
    else:
        findings.append(f"Clause '{clause_type}' present")

    # Enforceability check
    enforceability = is_clause_enforceable(jurisdiction, clause_type)
    if not enforceability["enforceable"]:
        total = max(total, 4)
        findings.append(f"ENFORCEABILITY WARNING: {enforceability['note']}")
        recommendations.append(f"Review '{clause_type}' for {jurisdiction} compliance: {enforceability['note']}")

    # Jurisdiction-specific risk
    if j_modifier > 0:
        findings.append(f"Higher risk in {jurisdiction} (+{j_modifier} modifier)")
    elif j_modifier < 0:
        findings.append(f"Common/lower risk in {jurisdiction} ({j_modifier} modifier)")

    total = max(1, min(5, total))

    return {
        "clause_type": clause_type,
        "clause_description": cuad.get("description", ""),
        "risk_score": total,
        "risk_level": classify_risk(total),
        "base_weight": base_weight,
        "jurisdiction_modifier": j_modifier,
        "playbook_modifier": playbook_modifier,
        "findings": findings,
        "recommendations": recommendations,
        "enforceable": enforceability["enforceable"],
        "enforceability_note": enforceability.get("note", ""),
        "jurisdiction": jurisdiction,
        "clause_present": clause_present,
    }


# ---------------------------------------------------------------------------
# Contract-Level Risk Assessment
# ---------------------------------------------------------------------------


def assess_contract_risk(
    detected_clauses: dict[str, bool],
    jurisdiction: str,
    playbook: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Assess risk for an entire contract.

    Args:
        detected_clauses: Map of clause_type → True (present) / False (missing)
        jurisdiction: Jurisdiction code
        playbook: Optional map of clause_type → playbook risk modifier

    Returns:
        Full contract risk assessment with per-clause results and summary.
    """
    playbook = playbook or {}
    clause_results: list[dict[str, Any]] = []
    red_count = 0
    yellow_count = 0
    green_count = 0

    # Assess all detected/checked clauses
    for clause_type, present in detected_clauses.items():
        result = assess_clause_risk(
            clause_type=clause_type,
            jurisdiction=jurisdiction,
            clause_present=present,
            playbook_modifier=playbook.get(clause_type, 0),
        )
        clause_results.append(result)
        level = result["risk_level"]
        if level == "RED":
            red_count += 1
        elif level == "YELLOW":
            yellow_count += 1
        else:
            green_count += 1

    # Check for required clauses not in detected_clauses
    required = get_required_clauses(jurisdiction)
    for req_clause in required:
        if req_clause not in detected_clauses:
            result = assess_clause_risk(
                clause_type=req_clause,
                jurisdiction=jurisdiction,
                clause_present=False,
                playbook_modifier=playbook.get(req_clause, 0),
            )
            clause_results.append(result)
            red_count += 1

    # Overall risk
    if red_count > 0:
        overall_level = "RED"
    elif yellow_count > 0:
        overall_level = "YELLOW"
    else:
        overall_level = "GREEN"

    # Recommendations summary
    all_recs: list[str] = []
    for r in clause_results:
        all_recs.extend(r.get("recommendations", []))

    return {
        "jurisdiction": jurisdiction,
        "jurisdiction_name": (get_jurisdiction(jurisdiction) or {}).get("name", jurisdiction),
        "overall_risk_level": overall_level,
        "clause_count": len(clause_results),
        "red_count": red_count,
        "yellow_count": yellow_count,
        "green_count": green_count,
        "clause_results": clause_results,
        "recommendations": all_recs,
        "requires_attorney_review": red_count > 0 or yellow_count >= 3,
    }


def compare_across_jurisdictions(
    detected_clauses: dict[str, bool],
    jurisdictions: list[str],
    playbook: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run risk assessment across multiple jurisdictions.

    This is the cross-jurisdictional analysis — the feature no competitor has.

    Returns:
        Map of jurisdiction_code → contract risk assessment.
    """
    results = {}
    for j in jurisdictions:
        results[j] = assess_contract_risk(detected_clauses, j, playbook)
    return results
