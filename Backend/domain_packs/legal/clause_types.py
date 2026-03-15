"""Legal Domain Pack — Clause Types.

Defines legal WorkItem types and the CUAD clause taxonomy (41 categories).
CUAD = Contract Understanding Atticus Dataset (NeurIPS 2021).
Source: github.com/TheAtticusProject/cuad, License: CC BY 4.0.

Each clause type has:
- description: What the clause covers
- risk_weight: Base risk weight (1-5) for cross-jurisdictional analysis
- typical_section: Where this clause typically appears in a contract
- jurisdictions: Which jurisdictions commonly require/expect this clause
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# CUAD Clause Taxonomy — 41 categories
# ---------------------------------------------------------------------------

CUAD_CLAUSE_TYPES: dict[str, dict[str, Any]] = {
    "document_name": {
        "description": "Name/title of the agreement",
        "risk_weight": 1,
        "typical_section": "header",
        "jurisdictions": ["universal"],
    },
    "parties": {
        "description": "Contracting parties and their roles",
        "risk_weight": 2,
        "typical_section": "preamble",
        "jurisdictions": ["universal"],
    },
    "agreement_date": {
        "description": "Effective date of the agreement",
        "risk_weight": 2,
        "typical_section": "preamble",
        "jurisdictions": ["universal"],
    },
    "effective_date": {
        "description": "Date when obligations begin (may differ from agreement date)",
        "risk_weight": 2,
        "typical_section": "preamble",
        "jurisdictions": ["universal"],
    },
    "expiration_date": {
        "description": "Date when the agreement expires",
        "risk_weight": 3,
        "typical_section": "term",
        "jurisdictions": ["universal"],
    },
    "renewal_term": {
        "description": "Automatic renewal provisions and notice periods",
        "risk_weight": 3,
        "typical_section": "term",
        "jurisdictions": ["universal"],
    },
    "notice_period_to_terminate_renewal": {
        "description": "Required notice to prevent automatic renewal",
        "risk_weight": 4,
        "typical_section": "term",
        "jurisdictions": ["universal"],
    },
    "governing_law": {
        "description": "Applicable law / jurisdiction for disputes",
        "risk_weight": 5,
        "typical_section": "general_provisions",
        "jurisdictions": ["universal"],
    },
    "most_favored_nation": {
        "description": "MFN clause ensuring best available terms",
        "risk_weight": 3,
        "typical_section": "commercial_terms",
        "jurisdictions": ["US", "UK"],
    },
    "non_compete": {
        "description": "Restrictions on competitive activities",
        "risk_weight": 5,
        "typical_section": "restrictive_covenants",
        "jurisdictions": ["US", "DE", "EU"],
    },
    "exclusivity": {
        "description": "Exclusive dealing or supply arrangements",
        "risk_weight": 4,
        "typical_section": "commercial_terms",
        "jurisdictions": ["universal"],
    },
    "no_solicitation_of_customers": {
        "description": "Prohibition on soliciting the other party's customers",
        "risk_weight": 3,
        "typical_section": "restrictive_covenants",
        "jurisdictions": ["US", "UK"],
    },
    "no_solicitation_of_employees": {
        "description": "Prohibition on recruiting the other party's employees",
        "risk_weight": 3,
        "typical_section": "restrictive_covenants",
        "jurisdictions": ["US", "UK", "DE"],
    },
    "competitive_restriction_exception": {
        "description": "Exceptions to non-compete or exclusivity clauses",
        "risk_weight": 3,
        "typical_section": "restrictive_covenants",
        "jurisdictions": ["US", "DE"],
    },
    "change_of_control": {
        "description": "Rights/obligations upon ownership change (M&A trigger)",
        "risk_weight": 4,
        "typical_section": "general_provisions",
        "jurisdictions": ["universal"],
    },
    "anti_assignment": {
        "description": "Restrictions on assigning the contract to third parties",
        "risk_weight": 3,
        "typical_section": "general_provisions",
        "jurisdictions": ["universal"],
    },
    "revenue_profit_sharing": {
        "description": "Revenue or profit sharing arrangements",
        "risk_weight": 4,
        "typical_section": "commercial_terms",
        "jurisdictions": ["universal"],
    },
    "price_restrictions": {
        "description": "Price caps, floors, or adjustment mechanisms",
        "risk_weight": 3,
        "typical_section": "commercial_terms",
        "jurisdictions": ["universal"],
    },
    "minimum_commitment": {
        "description": "Minimum purchase/service commitments",
        "risk_weight": 4,
        "typical_section": "commercial_terms",
        "jurisdictions": ["universal"],
    },
    "volume_restriction": {
        "description": "Maximum volume or capacity limitations",
        "risk_weight": 3,
        "typical_section": "commercial_terms",
        "jurisdictions": ["universal"],
    },
    "ip_ownership_assignment": {
        "description": "Intellectual property ownership and assignment terms",
        "risk_weight": 5,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "joint_ip_ownership": {
        "description": "Joint ownership of created intellectual property",
        "risk_weight": 4,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "license_grant": {
        "description": "License to use intellectual property",
        "risk_weight": 4,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "non_transferable_license": {
        "description": "License that cannot be transferred to third parties",
        "risk_weight": 3,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "affiliate_license_licensee": {
        "description": "License extending to affiliates of the licensee",
        "risk_weight": 3,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "affiliate_license_licensor": {
        "description": "License extending to affiliates of the licensor",
        "risk_weight": 3,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "unlimited_all_you_can_eat_license": {
        "description": "Unrestricted usage license without volume limits",
        "risk_weight": 4,
        "typical_section": "ip_provisions",
        "jurisdictions": ["US", "UK"],
    },
    "irrevocable_or_perpetual_license": {
        "description": "License that cannot be revoked or has no expiration",
        "risk_weight": 5,
        "typical_section": "ip_provisions",
        "jurisdictions": ["universal"],
    },
    "source_code_escrow": {
        "description": "Source code held in escrow for specified trigger events",
        "risk_weight": 3,
        "typical_section": "ip_provisions",
        "jurisdictions": ["US", "UK", "DE"],
    },
    "post_termination_services": {
        "description": "Services or support obligations after contract ends",
        "risk_weight": 3,
        "typical_section": "term",
        "jurisdictions": ["universal"],
    },
    "audit_rights": {
        "description": "Right to audit the other party's books/records/systems",
        "risk_weight": 3,
        "typical_section": "general_provisions",
        "jurisdictions": ["universal"],
    },
    "uncapped_liability": {
        "description": "No cap on liability (unlimited financial exposure)",
        "risk_weight": 5,
        "typical_section": "liability",
        "jurisdictions": ["universal"],
    },
    "cap_on_liability": {
        "description": "Maximum liability amount or formula",
        "risk_weight": 4,
        "typical_section": "liability",
        "jurisdictions": ["universal"],
    },
    "liquidated_damages": {
        "description": "Pre-determined damages for specific breaches",
        "risk_weight": 4,
        "typical_section": "liability",
        "jurisdictions": ["US", "UK"],
    },
    "warranty_duration": {
        "description": "Time period for warranty claims",
        "risk_weight": 3,
        "typical_section": "warranties",
        "jurisdictions": ["universal"],
    },
    "insurance": {
        "description": "Insurance requirements for parties",
        "risk_weight": 3,
        "typical_section": "general_provisions",
        "jurisdictions": ["US", "UK"],
    },
    "covenant_not_to_sue": {
        "description": "Agreement not to bring legal action",
        "risk_weight": 4,
        "typical_section": "liability",
        "jurisdictions": ["US"],
    },
    "third_party_beneficiary": {
        "description": "Rights granted to non-contracting parties",
        "risk_weight": 3,
        "typical_section": "general_provisions",
        "jurisdictions": ["US", "UK"],
    },
    "confidentiality": {
        "description": "Obligations to keep information confidential",
        "risk_weight": 4,
        "typical_section": "confidentiality",
        "jurisdictions": ["universal"],
    },
    "termination_for_convenience": {
        "description": "Right to terminate without cause",
        "risk_weight": 4,
        "typical_section": "term",
        "jurisdictions": ["universal"],
    },
    "rofr_rofo_rofn": {
        "description": "Right of first refusal / first offer / first negotiation",
        "risk_weight": 3,
        "typical_section": "commercial_terms",
        "jurisdictions": ["US", "UK"],
    },
}


# ---------------------------------------------------------------------------
# Legal WorkItem Types (content types for the legal domain)
# ---------------------------------------------------------------------------

LEGAL_CONTENT_TYPES: dict[str, dict[str, Any]] = {
    "contract_review": {
        "description": "Full contract review with clause extraction and risk assessment",
        "default_stages": ["extract", "analyze", "risk_assess", "redline", "report"],
        "requires_document": True,
        "max_variants": 1,
    },
    "clause_analysis": {
        "description": "Analysis of a specific clause or clause set",
        "default_stages": ["analyze", "risk_assess"],
        "requires_document": False,
        "max_variants": 3,
    },
    "dpa_check": {
        "description": "Data Processing Agreement check against GDPR Art. 28",
        "default_stages": ["extract", "analyze", "report"],
        "requires_document": True,
        "max_variants": 1,
    },
    "nda_triage": {
        "description": "Quick NDA review: standard-approve / counsel-review / full-review",
        "default_stages": ["extract", "analyze", "report"],
        "requires_document": True,
        "max_variants": 1,
    },
    "contract_comparison": {
        "description": "Side-by-side comparison of two contract versions (diff)",
        "default_stages": ["extract", "analyze", "report"],
        "requires_document": True,
        "max_variants": 1,
    },
    "legal_memo": {
        "description": "Legal memorandum or opinion draft",
        "default_stages": ["analyze", "report"],
        "requires_document": False,
        "max_variants": 2,
    },
    "playbook_entry": {
        "description": "Clause template or playbook rule for the clause library",
        "default_stages": [],
        "requires_document": False,
        "max_variants": 1,
    },
    "redline_draft": {
        "description": "Redline markup with suggested contract modifications",
        "default_stages": ["analyze", "redline"],
        "requires_document": True,
        "max_variants": 2,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_clause_type(clause_name: str) -> dict[str, Any] | None:
    """Get CUAD clause type definition."""
    return CUAD_CLAUSE_TYPES.get(clause_name)


def list_clause_types() -> dict[str, dict[str, Any]]:
    """List all 41 CUAD clause types."""
    return dict(CUAD_CLAUSE_TYPES)


def get_content_type(type_name: str) -> dict[str, Any] | None:
    """Get legal content type definition."""
    return LEGAL_CONTENT_TYPES.get(type_name)


def list_content_types() -> dict[str, dict[str, Any]]:
    """List all legal content types."""
    return dict(LEGAL_CONTENT_TYPES)


def clauses_for_jurisdiction(jurisdiction: str) -> dict[str, dict[str, Any]]:
    """Filter clause types relevant to a specific jurisdiction."""
    result = {}
    for name, clause in CUAD_CLAUSE_TYPES.items():
        jurisdictions = clause.get("jurisdictions", [])
        if "universal" in jurisdictions or jurisdiction.upper() in [j.upper() for j in jurisdictions]:
            result[name] = clause
    return result
