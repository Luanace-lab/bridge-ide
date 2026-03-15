from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
_DEFAULT_LIBRARY_PATH = _ROOT_DIR / "config" / "capability_library.json"
_ENGINE_ORDER = ("claude_code", "codex", "gemini_cli", "qwen_code")
_SUPPORTED_COMPATIBILITY = {"documented", "inferred"}
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}
_TRUST_PRIORITY = {"official": 0, "bridge": 1, "registry": 2, "legacy": 3}

_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS: int | None = None
_CACHE_DATA: dict[str, Any] | None = None


def clear_cache() -> None:
    global _CACHE_DATA, _CACHE_MTIME_NS, _CACHE_PATH
    _CACHE_DATA = None
    _CACHE_MTIME_NS = None
    _CACHE_PATH = None


def library_path() -> Path:
    override = os.environ.get("BRIDGE_CAPABILITY_LIBRARY_PATH", "").strip()
    return Path(override).expanduser() if override else _DEFAULT_LIBRARY_PATH


def _read_library() -> dict[str, Any]:
    global _CACHE_DATA, _CACHE_MTIME_NS, _CACHE_PATH
    path = library_path()
    stat = path.stat()
    if _CACHE_DATA is not None and _CACHE_PATH == path and _CACHE_MTIME_NS == stat.st_mtime_ns:
        return _CACHE_DATA
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid capability library at {path}: root must be an object")
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"invalid capability library at {path}: entries must be a list")
    _CACHE_PATH = path
    _CACHE_MTIME_NS = stat.st_mtime_ns
    _CACHE_DATA = data
    return data


def _entry_compatibility(entry: dict[str, Any]) -> dict[str, str]:
    raw = entry.get("engine_compatibility", {})
    if not isinstance(raw, dict):
        return {}
    compatibility: dict[str, str] = {}
    for engine in _ENGINE_ORDER:
        value = str(raw.get(engine, "")).strip().lower()
        if value:
            compatibility[engine] = value
    return compatibility


def _supported_clis(entry: dict[str, Any]) -> list[str]:
    compatibility = _entry_compatibility(entry)
    return [
        engine
        for engine in _ENGINE_ORDER
        if compatibility.get(engine, "") in _SUPPORTED_COMPATIBILITY
    ]


def _normalize_scalar(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_bool(value: str | bool | None) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def parse_bool_filter(value: str | bool | None) -> bool | None:
    return _normalize_bool(value)


def _normalize_cli(value: str) -> str:
    lowered = _normalize_scalar(value)
    aliases = {
        "claude": "claude_code",
        "claude-code": "claude_code",
        "codex-cli": "codex",
        "gemini": "gemini_cli",
        "gemini-cli": "gemini_cli",
        "qwen": "qwen_code",
        "qwen-cli": "qwen_code",
        "qwen-code": "qwen_code",
    }
    return aliases.get(lowered, lowered)


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9_+#.-]+", text.lower()) if token]


def _entry_terms(entry: dict[str, Any]) -> dict[str, set[str]]:
    tag_values = [str(tag).strip().lower() for tag in list(entry.get("task_tags", []) or []) if str(tag).strip()]
    install_methods = list(entry.get("install_methods", []) or [])
    search_blob = " ".join(
        [
            str(entry.get("id", "")),
            str(entry.get("name", "")),
            str(entry.get("title", "")),
            str(entry.get("vendor", "")),
            str(entry.get("owner", "")),
            str(entry.get("summary", "")),
            str(entry.get("source_registry", "")),
            " ".join(tag_values),
            " ".join(str(method.get("kind", "")) for method in install_methods if isinstance(method, dict)),
            " ".join(_supported_clis(entry)),
        ]
    ).lower()
    return {
        "all": set(_tokenize(search_blob)),
        "name": set(_tokenize(f"{entry.get('name', '')} {entry.get('title', '')} {entry.get('id', '')}")),
        "vendor": set(_tokenize(f"{entry.get('vendor', '')} {entry.get('owner', '')}")),
        "tags": set(_tokenize(" ".join(tag_values))),
        "summary": set(_tokenize(str(entry.get("summary", "")))),
    }


def _match_tokens(entry: dict[str, Any], query: str) -> float:
    tokens = _tokenize(query)
    if not tokens:
        return 0.0
    terms = _entry_terms(entry)
    score = 0.0
    all_terms = terms["all"]
    matched_all = True
    for token in tokens:
        matched = False
        if token in terms["name"]:
            score += 8.0
            matched = True
        elif token in terms["tags"]:
            score += 6.0
            matched = True
        elif token in terms["vendor"]:
            score += 4.0
            matched = True
        elif token in terms["summary"]:
            score += 2.0
            matched = True
        elif token in all_terms:
            score += 1.0
            matched = True
        if not matched:
            matched_all = False
    if matched_all:
        score += 3.0
    if entry.get("official_vendor"):
        score += 0.5
    if entry.get("runtime_verified"):
        score += 1.0
    return score


def _matches_filters(
    entry: dict[str, Any],
    *,
    query: str = "",
    entry_type: str = "",
    vendor: str = "",
    cli: str = "",
    task_tag: str = "",
    source_registry: str = "",
    status: str = "",
    trust_tier: str = "",
    official_vendor: bool | None = None,
    reproducible: bool | None = None,
    runtime_verified: bool | None = None,
) -> tuple[bool, float]:
    if entry_type and _normalize_scalar(entry.get("type")) != _normalize_scalar(entry_type):
        return False, 0.0
    if vendor and _normalize_scalar(entry.get("vendor")) != _normalize_scalar(vendor):
        return False, 0.0
    if source_registry and _normalize_scalar(entry.get("source_registry")) != _normalize_scalar(source_registry):
        return False, 0.0
    if status and _normalize_scalar(entry.get("status")) != _normalize_scalar(status):
        return False, 0.0
    if trust_tier and _normalize_scalar(entry.get("trust_tier")) != _normalize_scalar(trust_tier):
        return False, 0.0
    if official_vendor is not None and bool(entry.get("official_vendor")) is not official_vendor:
        return False, 0.0
    if reproducible is not None and bool(entry.get("reproducible")) is not reproducible:
        return False, 0.0
    if runtime_verified is not None and bool(entry.get("runtime_verified")) is not runtime_verified:
        return False, 0.0
    if cli:
        requested_cli = _normalize_cli(cli)
        compatibility = _entry_compatibility(entry)
        if compatibility.get(requested_cli, "") not in _SUPPORTED_COMPATIBILITY:
            return False, 0.0
    if task_tag:
        normalized_tag = _normalize_scalar(task_tag)
        tags = {_normalize_scalar(tag) for tag in list(entry.get("task_tags", []) or [])}
        if normalized_tag not in tags:
            return False, 0.0
    score = _match_tokens(entry, query)
    if query and score <= 0:
        return False, 0.0
    return True, score


def metadata() -> dict[str, Any]:
    data = _read_library()
    return dict(data.get("metadata", {}) or {})


def total_entries() -> int:
    return len(list(_read_library().get("entries", [])))


def list_entries(
    *,
    query: str = "",
    entry_type: str = "",
    vendor: str = "",
    cli: str = "",
    task_tag: str = "",
    source_registry: str = "",
    status: str = "",
    trust_tier: str = "",
    official_vendor: bool | None = None,
    reproducible: bool | None = None,
    runtime_verified: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    entries = list(_read_library().get("entries", []))
    scored: list[tuple[float, dict[str, Any]]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        matches, score = _matches_filters(
            raw_entry,
            query=query,
            entry_type=entry_type,
            vendor=vendor,
            cli=cli,
            task_tag=task_tag,
            source_registry=source_registry,
            status=status,
            trust_tier=trust_tier,
            official_vendor=official_vendor,
            reproducible=reproducible,
            runtime_verified=runtime_verified,
        )
        if not matches:
            continue
        entry = dict(raw_entry)
        entry["works_in_clis"] = _supported_clis(raw_entry)
        if query:
            entry["match_score"] = round(score, 3)
        scored.append((score, entry))
    scored.sort(
        key=lambda item: (
            -item[0],
            _TRUST_PRIORITY.get(str(item[1].get("trust_tier", "")), 99),
            item[1].get("name", ""),
            item[1].get("id", ""),
        )
    )
    total = len(scored)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    slice_entries = [item[1] for item in scored[offset:offset + limit]]
    return {
        "entries": slice_entries,
        "count": len(slice_entries),
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {
            "query": query,
            "type": entry_type,
            "vendor": vendor,
            "cli": _normalize_cli(cli) if cli else "",
            "task_tag": task_tag,
            "source_registry": source_registry,
            "status": status,
            "trust_tier": trust_tier,
            "official_vendor": official_vendor,
            "reproducible": reproducible,
            "runtime_verified": runtime_verified,
        },
    }


def get_entry(entry_id: str) -> dict[str, Any] | None:
    target = str(entry_id).strip()
    if not target:
        return None
    for raw_entry in list(_read_library().get("entries", [])):
        if not isinstance(raw_entry, dict):
            continue
        if str(raw_entry.get("id", "")) != target:
            continue
        entry = dict(raw_entry)
        entry["works_in_clis"] = _supported_clis(raw_entry)
        return entry
    return None


def search_entries(
    *,
    query: str,
    entry_type: str = "",
    vendor: str = "",
    cli: str = "",
    task_tag: str = "",
    source_registry: str = "",
    status: str = "",
    trust_tier: str = "",
    official_vendor: bool | None = None,
    reproducible: bool | None = None,
    runtime_verified: bool | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    return list_entries(
        query=query,
        entry_type=entry_type,
        vendor=vendor,
        cli=cli,
        task_tag=task_tag,
        source_registry=source_registry,
        status=status,
        trust_tier=trust_tier,
        official_vendor=official_vendor,
        reproducible=reproducible,
        runtime_verified=runtime_verified,
        limit=limit,
        offset=offset,
    )


def recommend_entries(
    *,
    task: str,
    engine: str = "",
    cli: str = "",
    top_k: int = 10,
    official_vendor_only: bool | None = None,
) -> dict[str, Any]:
    resolved_cli = _normalize_cli(cli or engine)
    result = search_entries(
        query=task,
        cli=resolved_cli,
        official_vendor=official_vendor_only,
        limit=max(1, min(int(top_k), 50)),
    )
    matches = result["entries"]
    return {
        "matches": matches,
        "count": len(matches),
        "task": task,
        "engine": _normalize_scalar(engine),
        "cli": resolved_cli,
        "filters": result["filters"],
    }


def facets() -> dict[str, Any]:
    vendors: dict[str, int] = {}
    entry_types: dict[str, int] = {}
    clis: dict[str, int] = {}
    task_tags: dict[str, int] = {}
    source_registries: dict[str, int] = {}
    statuses: dict[str, int] = {}
    trust_tiers: dict[str, int] = {}
    entries = list(_read_library().get("entries", []))
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        vendor = _normalize_scalar(raw_entry.get("vendor"))
        entry_type = _normalize_scalar(raw_entry.get("type"))
        source_registry = _normalize_scalar(raw_entry.get("source_registry"))
        status = _normalize_scalar(raw_entry.get("status"))
        trust_tier = _normalize_scalar(raw_entry.get("trust_tier"))
        if vendor:
            vendors[vendor] = vendors.get(vendor, 0) + 1
        if entry_type:
            entry_types[entry_type] = entry_types.get(entry_type, 0) + 1
        if source_registry:
            source_registries[source_registry] = source_registries.get(source_registry, 0) + 1
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        if trust_tier:
            trust_tiers[trust_tier] = trust_tiers.get(trust_tier, 0) + 1
        for cli_name in _supported_clis(raw_entry):
            clis[cli_name] = clis.get(cli_name, 0) + 1
        for tag in list(raw_entry.get("task_tags", []) or []):
            normalized_tag = _normalize_scalar(tag)
            if normalized_tag:
                task_tags[normalized_tag] = task_tags.get(normalized_tag, 0) + 1
    return {
        "vendors": sorted(vendors),
        "types": sorted(entry_types),
        "clis": sorted(clis),
        "task_tags": sorted(task_tags),
        "source_registries": sorted(source_registries),
        "statuses": sorted(statuses),
        "trust_tiers": sorted(trust_tiers),
        "stats": {
            "entry_count": len(entries),
            "vendor_count": len(vendors),
            "type_count": len(entry_types),
            "cli_count": len(clis),
            "task_tag_count": len(task_tags),
            "source_registry_count": len(source_registries),
        },
    }
