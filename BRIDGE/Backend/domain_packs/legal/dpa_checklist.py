"""Legal Domain Pack — DPA/GDPR Art. 28 Checklist.

Automated check of Data Processing Agreements against GDPR Article 28(3).
Supports DSGVO (German implementation) and general GDPR requirements.

Each mandatory clause from Art. 28(3) is checked for:
- Presence (is the clause in the contract?)
- Completeness (is it specific enough?)
- Compliance level: COMPLIANT / PARTIAL / MISSING / NOT_APPLICABLE

Also covers BDSG specifics (German Federal Data Protection Act) and
nDSG (Swiss revised Data Protection Act) where applicable.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Art. 28(3) GDPR — Mandatory DPA Clauses
# ---------------------------------------------------------------------------

DPA_MANDATORY_CLAUSES: list[dict[str, Any]] = [
    {
        "id": "dpa_01",
        "article": "Art. 28(3)(a)",
        "title": "Subject matter and duration",
        "title_de": "Gegenstand und Dauer der Verarbeitung",
        "description": "The DPA must specify the subject matter and duration of data processing.",
        "check_keywords": [
            "subject matter", "duration", "gegenstand", "dauer",
            "term of processing", "verarbeitungsdauer",
        ],
        "completeness_criteria": [
            "Specific processing activities described",
            "Duration or termination trigger defined",
        ],
    },
    {
        "id": "dpa_02",
        "article": "Art. 28(3)(a)",
        "title": "Nature and purpose of processing",
        "title_de": "Art und Zweck der Verarbeitung",
        "description": "The DPA must define the nature and purpose of data processing.",
        "check_keywords": [
            "nature", "purpose", "art", "zweck",
            "processing activities", "verarbeitungstaetigkeiten",
        ],
        "completeness_criteria": [
            "Processing purpose clearly stated",
            "Types of processing operations listed",
        ],
    },
    {
        "id": "dpa_03",
        "article": "Art. 28(3)(a)",
        "title": "Types of personal data",
        "title_de": "Art der personenbezogenen Daten",
        "description": "Categories of personal data being processed must be listed.",
        "check_keywords": [
            "types of personal data", "categories of data", "art der daten",
            "datenkategorien", "personenbezogene daten",
        ],
        "completeness_criteria": [
            "Data categories explicitly listed",
            "Special categories (Art. 9) flagged if applicable",
        ],
    },
    {
        "id": "dpa_04",
        "article": "Art. 28(3)(a)",
        "title": "Categories of data subjects",
        "title_de": "Kategorien betroffener Personen",
        "description": "Categories of data subjects must be specified.",
        "check_keywords": [
            "data subjects", "categories of individuals", "betroffene personen",
            "kategorien betroffener", "data subject categories",
        ],
        "completeness_criteria": [
            "Data subject categories explicitly listed",
        ],
    },
    {
        "id": "dpa_05",
        "article": "Art. 28(3)(a)",
        "title": "Instructions from controller",
        "title_de": "Weisungsgebundenheit",
        "description": "Processor must act only on documented instructions from the controller.",
        "check_keywords": [
            "instructions", "documented instructions", "weisungsgebunden",
            "weisung", "auf weisung", "controller instructions",
        ],
        "completeness_criteria": [
            "Processor bound to documented instructions",
            "Process for new/changed instructions defined",
            "Processor must inform if instruction violates law",
        ],
    },
    {
        "id": "dpa_06",
        "article": "Art. 28(3)(b)",
        "title": "Confidentiality obligations",
        "title_de": "Vertraulichkeit",
        "description": "Persons authorized to process data must be under confidentiality obligation.",
        "check_keywords": [
            "confidentiality", "vertraulichkeit", "secrecy",
            "verpflichtung zur vertraulichkeit", "geheimhaltung",
        ],
        "completeness_criteria": [
            "Staff under confidentiality obligation",
            "Statutory obligation referenced if applicable",
        ],
    },
    {
        "id": "dpa_07",
        "article": "Art. 28(3)(c)",
        "title": "Technical and organizational measures",
        "title_de": "Technische und organisatorische Massnahmen (TOMs)",
        "description": "Processor must implement appropriate technical and organizational security measures.",
        "check_keywords": [
            "technical and organizational", "security measures", "TOMs",
            "technische und organisatorische", "sicherheitsmassnahmen",
            "art. 32", "artikel 32",
        ],
        "completeness_criteria": [
            "TOMs described or referenced in annex",
            "Encryption mentioned",
            "Access controls mentioned",
            "Regular review/audit of measures",
        ],
    },
    {
        "id": "dpa_08",
        "article": "Art. 28(3)(d)",
        "title": "Sub-processors",
        "title_de": "Unterauftragsverarbeiter",
        "description": "Conditions for engaging sub-processors must be defined.",
        "check_keywords": [
            "sub-processor", "subcontractor", "unterauftragsverarbeiter",
            "sub-processing", "weitere auftragsverarbeiter",
            "prior authorization", "vorherige genehmigung",
        ],
        "completeness_criteria": [
            "Prior written authorization required",
            "Same obligations imposed on sub-processors",
            "List of current sub-processors or process to obtain it",
            "Right to object to new sub-processors",
        ],
    },
    {
        "id": "dpa_09",
        "article": "Art. 28(3)(e)",
        "title": "Assistance with data subject rights",
        "title_de": "Unterstuetzung bei Betroffenenrechten",
        "description": "Processor must assist controller in responding to data subject requests.",
        "check_keywords": [
            "data subject rights", "betroffenenrechte", "right of access",
            "right to erasure", "auskunftsrecht", "loeschungsrecht",
            "assist the controller", "unterstuetzung",
        ],
        "completeness_criteria": [
            "Assistance obligation clearly stated",
            "Response timeframe defined or referenced",
        ],
    },
    {
        "id": "dpa_10",
        "article": "Art. 28(3)(f)",
        "title": "Assistance with security and breach notification",
        "title_de": "Unterstuetzung bei Sicherheitsvorfaellen",
        "description": "Processor must assist with security obligations, breach notification, and DPIAs.",
        "check_keywords": [
            "data breach", "security incident", "sicherheitsvorfall",
            "datenschutzverletzung", "notification", "meldepflicht",
            "DPIA", "data protection impact", "folgenabschaetzung",
        ],
        "completeness_criteria": [
            "Breach notification timeframe defined (typically 24-72h)",
            "Assistance with Art. 33/34 obligations",
            "DPIA assistance if applicable",
        ],
    },
    {
        "id": "dpa_11",
        "article": "Art. 28(3)(g)",
        "title": "Deletion or return after contract end",
        "title_de": "Loeschung/Rueckgabe nach Vertragsende",
        "description": "After processing ends, all data must be deleted or returned.",
        "check_keywords": [
            "deletion", "return", "loeschung", "rueckgabe",
            "after termination", "nach vertragsende",
            "destroy", "vernichtung",
        ],
        "completeness_criteria": [
            "Delete or return — controller's choice",
            "Timeframe for deletion specified",
            "Confirmation of deletion provided",
            "Exceptions for legal retention noted",
        ],
    },
    {
        "id": "dpa_12",
        "article": "Art. 28(3)(h)",
        "title": "Audit rights",
        "title_de": "Nachweispflichten und Audits",
        "description": "Controller must have audit rights to verify processor compliance.",
        "check_keywords": [
            "audit", "inspection", "nachweispflicht", "pruefung",
            "kontrolle", "demonstrate compliance", "nachweis",
        ],
        "completeness_criteria": [
            "Right to conduct audits",
            "Reasonable notice period defined",
            "Processor must provide necessary information",
            "Right to engage third-party auditors",
        ],
    },
]


# ---------------------------------------------------------------------------
# DPA Check Engine
# ---------------------------------------------------------------------------


def check_dpa_clause(
    clause_id: str,
    text_present: bool,
    completeness_checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Check a single DPA mandatory clause.

    Args:
        clause_id: DPA clause ID (dpa_01 through dpa_12)
        text_present: Whether matching text was found in the document
        completeness_checks: Map of completeness criteria → met (True/False)

    Returns:
        Check result with compliance status.
    """
    clause_def = None
    for c in DPA_MANDATORY_CLAUSES:
        if c["id"] == clause_id:
            clause_def = c
            break
    if not clause_def:
        return {"clause_id": clause_id, "status": "UNKNOWN", "error": "Unknown clause ID"}

    completeness_checks = completeness_checks or {}
    criteria = clause_def.get("completeness_criteria", [])

    if not text_present:
        status = "MISSING"
        score = 0
    else:
        met = sum(1 for c in criteria if completeness_checks.get(c, False))
        total = len(criteria)
        if total == 0:
            score = 100
        else:
            score = int((met / total) * 100)
        if score >= 80:
            status = "COMPLIANT"
        elif score >= 40:
            status = "PARTIAL"
        else:
            status = "INCOMPLETE"

    return {
        "clause_id": clause_id,
        "article": clause_def["article"],
        "title": clause_def["title"],
        "title_de": clause_def["title_de"],
        "status": status,
        "completeness_score": score,
        "criteria_total": len(criteria),
        "criteria_met": sum(1 for c in criteria if completeness_checks.get(c, False)),
        "criteria_details": {c: completeness_checks.get(c, False) for c in criteria},
        "keywords": clause_def["check_keywords"],
    }


def run_dpa_check(
    clause_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run full DPA Art. 28 check.

    Args:
        clause_results: Map of clause_id → {present: bool, completeness: {criterion: bool}}

    Returns:
        Full DPA compliance report.
    """
    results: list[dict[str, Any]] = []
    missing = 0
    partial = 0
    compliant = 0
    incomplete = 0

    for clause_def in DPA_MANDATORY_CLAUSES:
        cid = clause_def["id"]
        data = clause_results.get(cid, {})
        present = data.get("present", False)
        completeness = data.get("completeness", {})

        result = check_dpa_clause(cid, present, completeness)
        results.append(result)

        status = result["status"]
        if status == "MISSING":
            missing += 1
        elif status == "PARTIAL":
            partial += 1
        elif status == "INCOMPLETE":
            incomplete += 1
        elif status == "COMPLIANT":
            compliant += 1

    total = len(DPA_MANDATORY_CLAUSES)

    if missing > 0:
        overall = "NON_COMPLIANT"
    elif partial > 0 or incomplete > 0:
        overall = "PARTIALLY_COMPLIANT"
    else:
        overall = "COMPLIANT"

    return {
        "check_type": "GDPR_Art28_DPA",
        "overall_status": overall,
        "total_clauses": total,
        "compliant": compliant,
        "partial": partial,
        "incomplete": incomplete,
        "missing": missing,
        "compliance_percentage": int((compliant / total) * 100) if total > 0 else 0,
        "clause_results": results,
        "requires_remediation": missing > 0 or incomplete > 0,
        "recommendation": _overall_recommendation(overall, missing, partial, incomplete),
    }


def _overall_recommendation(overall: str, missing: int, partial: int, incomplete: int) -> str:
    """Generate overall recommendation based on DPA check results."""
    if overall == "COMPLIANT":
        return "DPA meets GDPR Art. 28(3) requirements. Regular review recommended."
    parts = []
    if missing > 0:
        parts.append(f"{missing} mandatory clause(s) missing — must be added before signing")
    if incomplete > 0:
        parts.append(f"{incomplete} clause(s) present but lack required detail")
    if partial > 0:
        parts.append(f"{partial} clause(s) partially compliant — review specifics")
    return "; ".join(parts) + ". Attorney review recommended before execution."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_dpa_clauses() -> list[dict[str, Any]]:
    """List all 12 mandatory DPA clauses with metadata."""
    return [
        {
            "id": c["id"],
            "article": c["article"],
            "title": c["title"],
            "title_de": c["title_de"],
            "description": c["description"],
            "criteria_count": len(c.get("completeness_criteria", [])),
        }
        for c in DPA_MANDATORY_CLAUSES
    ]


def get_dpa_keywords() -> dict[str, list[str]]:
    """Get keyword lists for each DPA clause — useful for text search/extraction."""
    return {c["id"]: c["check_keywords"] for c in DPA_MANDATORY_CLAUSES}
