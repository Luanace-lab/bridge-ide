"""Legal Domain Pack — Jurisdiction Rules.

Cross-jurisdictional rule engine for EU, US, DE, AT, CH, UK.
Each jurisdiction defines:
- Regulatory framework (which laws apply)
- Data sovereignty requirements
- Language requirements
- Risk modifiers (clauses that are riskier in this jurisdiction)
- Required clauses (clauses that MUST exist for validity)
- Prohibited clauses (clauses that are unenforceable)
- Anonymization requirements

This is the core differentiator: no existing tool covers EU+US in one system.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Jurisdiction Definitions
# ---------------------------------------------------------------------------

JURISDICTIONS: dict[str, dict[str, Any]] = {
    "DE": {
        "name": "Germany",
        "name_local": "Deutschland",
        "legal_system": "civil_law",
        "languages": ["de", "en"],
        "primary_language": "de",
        "regulatory_framework": {
            "data_protection": ["DSGVO/GDPR", "BDSG", "TTDSG"],
            "ai_regulation": ["EU AI Act (ab 02.08.2026)"],
            "professional": ["BRAO §43a Abs. 2", "BORA §2"],
            "contract_law": ["BGB", "HGB"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": True,
            "anonymization_required": True,
            "dpa_required_for_processing": True,
            "betriebsrat_involvement": True,
        },
        "risk_modifiers": {
            # Clauses that carry HIGHER risk in DE than baseline
            "non_compete": +2,  # Heavily regulated under §74 HGB
            "uncapped_liability": +1,  # Unusual in DE, courts may limit
            "governing_law": +1,  # Must match if DE parties involved
            "confidentiality": +1,  # Anwaltliche Verschwiegenheitspflicht
            "termination_for_convenience": -1,  # More common/accepted in DE
        },
        "required_clauses": [
            "governing_law",
            "parties",
            "confidentiality",
        ],
        "prohibited_or_unenforceable": {
            "covenant_not_to_sue": "Generally unenforceable under German law",
            "non_compete": "Must comply with §74 HGB: compensation, max 2 years, geographic limit",
            "liquidated_damages": "Subject to §§305ff BGB (AGB-Kontrolle) if in standard terms",
        },
        "statute_of_limitations": {
            "general": "3 years (§195 BGB)",
            "property": "30 years (§197 BGB)",
            "commercial": "3 years (§195 BGB)",
        },
    },
    "AT": {
        "name": "Austria",
        "name_local": "Oesterreich",
        "legal_system": "civil_law",
        "languages": ["de", "en"],
        "primary_language": "de",
        "regulatory_framework": {
            "data_protection": ["DSGVO/GDPR", "DSG"],
            "ai_regulation": ["EU AI Act"],
            "contract_law": ["ABGB", "UGB"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": True,
            "anonymization_required": True,
            "dpa_required_for_processing": True,
            "betriebsrat_involvement": True,
        },
        "risk_modifiers": {
            "non_compete": +2,
            "uncapped_liability": +1,
        },
        "required_clauses": ["governing_law", "parties"],
        "prohibited_or_unenforceable": {
            "covenant_not_to_sue": "Generally unenforceable",
            "non_compete": "Max 1 year, reasonable scope required (§36 AngG)",
        },
        "statute_of_limitations": {
            "general": "3 years (§1489 ABGB)",
            "property": "30 years",
        },
    },
    "CH": {
        "name": "Switzerland",
        "name_local": "Schweiz",
        "legal_system": "civil_law",
        "languages": ["de", "fr", "it", "en"],
        "primary_language": "de",
        "regulatory_framework": {
            "data_protection": ["nDSG (rev. 01.09.2023)", "DSV"],
            "contract_law": ["OR", "ZGB"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": False,  # Not EU but adequate
            "anonymization_required": True,
            "dpa_required_for_processing": True,
            "betriebsrat_involvement": False,
        },
        "risk_modifiers": {
            "non_compete": +1,
            "governing_law": +1,  # CH law often preferred by CH parties
        },
        "required_clauses": ["governing_law", "parties"],
        "prohibited_or_unenforceable": {
            "non_compete": "Max 3 years, must not endanger livelihood (Art. 340a OR)",
        },
        "statute_of_limitations": {
            "general": "10 years (Art. 127 OR)",
            "tort": "3 years (Art. 60 OR)",
        },
    },
    "US": {
        "name": "United States",
        "name_local": "United States",
        "legal_system": "common_law",
        "languages": ["en"],
        "primary_language": "en",
        "regulatory_framework": {
            "data_protection": ["State-level (CCPA, CPRA, Colorado AI Act)"],
            "ai_regulation": ["EO 14179 (Innovation-focused)", "Colorado AI Act (Feb 2026)"],
            "professional": ["ABA Model Rules", "State Bar Rules"],
            "contract_law": ["UCC", "Restatement (Second) of Contracts", "State common law"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": False,
            "anonymization_required": False,  # Best practice, not legally required
            "dpa_required_for_processing": False,  # GDPR DPA only if EU data subjects
            "betriebsrat_involvement": False,
        },
        "risk_modifiers": {
            "uncapped_liability": +2,  # Very risky in litigious US market
            "liquidated_damages": -1,  # Common and enforceable
            "covenant_not_to_sue": -1,  # Common and enforceable
            "non_compete": +1,  # FTC scrutiny, some states ban (CA)
            "termination_for_convenience": -1,  # Very common
            "insurance": +1,  # Often contractually required
        },
        "required_clauses": [
            "governing_law",
            "parties",
        ],
        "prohibited_or_unenforceable": {
            "non_compete": "Banned in CA; heavily restricted in CO, MN, ND, OK; FTC proposed ban pending",
        },
        "statute_of_limitations": {
            "general": "Varies by state (typically 3-6 years)",
            "ucc": "4 years (UCC §2-725)",
        },
    },
    "UK": {
        "name": "United Kingdom",
        "name_local": "United Kingdom",
        "legal_system": "common_law",
        "languages": ["en"],
        "primary_language": "en",
        "regulatory_framework": {
            "data_protection": ["UK GDPR", "Data Protection Act 2018"],
            "contract_law": ["Common law", "Sale of Goods Act", "UCTA 1977"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": False,  # EU adequacy decision
            "anonymization_required": True,
            "dpa_required_for_processing": True,
            "betriebsrat_involvement": False,
        },
        "risk_modifiers": {
            "liquidated_damages": -1,  # Enforceable if genuine pre-estimate
            "uncapped_liability": +1,
            "non_compete": +1,  # Must be reasonable in scope/duration
        },
        "required_clauses": ["governing_law", "parties"],
        "prohibited_or_unenforceable": {
            "non_compete": "Must be reasonable: duration, geography, scope (restraint of trade doctrine)",
        },
        "statute_of_limitations": {
            "general": "6 years (Limitation Act 1980)",
            "personal_injury": "3 years",
        },
    },
    "EU": {
        "name": "European Union (General)",
        "name_local": "Europaeische Union",
        "legal_system": "civil_law",
        "languages": ["en", "de", "fr", "es", "it", "nl", "pt", "pl"],
        "primary_language": "en",
        "regulatory_framework": {
            "data_protection": ["GDPR"],
            "ai_regulation": ["EU AI Act (fully enforceable 02.08.2026)"],
            "contract_law": ["National law applies (Rome I Regulation for choice of law)"],
        },
        "data_sovereignty": {
            "requires_eu_hosting": True,
            "anonymization_required": True,
            "dpa_required_for_processing": True,
            "betriebsrat_involvement": False,  # Depends on member state
        },
        "risk_modifiers": {
            "governing_law": +1,  # Rome I may override choice
            "confidentiality": +1,  # GDPR requirements
        },
        "required_clauses": ["governing_law", "parties", "confidentiality"],
        "prohibited_or_unenforceable": {},
        "statute_of_limitations": {
            "general": "Varies by member state",
        },
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_jurisdiction(code: str) -> dict[str, Any] | None:
    """Get jurisdiction definition by ISO code."""
    return JURISDICTIONS.get(code.upper())


def list_jurisdictions() -> dict[str, dict[str, Any]]:
    """List all supported jurisdictions."""
    return dict(JURISDICTIONS)


def supported_jurisdiction_codes() -> list[str]:
    """Return list of supported jurisdiction codes."""
    return list(JURISDICTIONS.keys())


def get_risk_modifier(jurisdiction: str, clause_type: str) -> int:
    """Get risk modifier for a clause type in a specific jurisdiction.

    Returns 0 if no modifier exists (use base risk weight).
    Positive = higher risk in this jurisdiction.
    Negative = lower risk / more common.
    """
    j = JURISDICTIONS.get(jurisdiction.upper())
    if not j:
        return 0
    return j.get("risk_modifiers", {}).get(clause_type, 0)


def is_clause_enforceable(jurisdiction: str, clause_type: str) -> dict[str, Any]:
    """Check if a clause type is enforceable in a jurisdiction.

    Returns:
        {"enforceable": True/False, "note": "..." if restricted}
    """
    j = JURISDICTIONS.get(jurisdiction.upper())
    if not j:
        return {"enforceable": True, "note": "Unknown jurisdiction — assume enforceable"}
    prohibited = j.get("prohibited_or_unenforceable", {})
    if clause_type in prohibited:
        return {"enforceable": False, "note": prohibited[clause_type]}
    return {"enforceable": True, "note": ""}


def get_required_clauses(jurisdiction: str) -> list[str]:
    """Get list of clause types required in this jurisdiction."""
    j = JURISDICTIONS.get(jurisdiction.upper())
    if not j:
        return []
    return list(j.get("required_clauses", []))


def requires_dpa(jurisdiction: str) -> bool:
    """Check if jurisdiction requires a Data Processing Agreement for AI processing."""
    j = JURISDICTIONS.get(jurisdiction.upper())
    if not j:
        return False
    return j.get("data_sovereignty", {}).get("dpa_required_for_processing", False)


def detect_jurisdiction_from_governing_law(governing_law_text: str) -> str | None:
    """Heuristic: detect jurisdiction from governing law clause text.

    Returns jurisdiction code or None.
    """
    text = governing_law_text.lower()
    # German
    for marker in ["deutsches recht", "german law", "recht der bundesrepublik",
                    "bgb", "hgb", "landgericht", "amtsgericht"]:
        if marker in text:
            return "DE"
    # Austrian
    for marker in ["oesterreichisches recht", "austrian law", "abgb"]:
        if marker in text:
            return "AT"
    # Swiss
    for marker in ["schweizer recht", "swiss law", "schweizerisches recht",
                    "obligationenrecht"]:
        if marker in text:
            return "CH"
    # UK
    for marker in ["english law", "laws of england", "england and wales"]:
        if marker in text:
            return "UK"
    # US — state-level
    for marker in ["new york law", "state of new york", "delaware law",
                    "state of delaware", "california law", "state of california",
                    "laws of the state of", "united states"]:
        if marker in text:
            return "US"
    # EU generic
    for marker in ["eu law", "european union"]:
        if marker in text:
            return "EU"
    return None
