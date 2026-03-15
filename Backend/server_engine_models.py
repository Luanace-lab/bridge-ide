"""Engine/model discovery helpers extracted from server.py (Slice 35)."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import runtime_layout

_TEXT_CACHE: dict[str, tuple[int, str]] = {}
_BINARY_CACHE: dict[str, tuple[int, bytes]] = {}


def _cached_text(path: str) -> str:
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    cache_key = os.path.abspath(path)
    cached = _TEXT_CACHE.get(cache_key)
    sig = (int(stat.st_mtime_ns),)
    if cached and cached[0] == sig[0]:
        return cached[1]
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    _TEXT_CACHE[cache_key] = (sig[0], text)
    return text


def _cached_bytes(path: str) -> bytes:
    try:
        stat = os.stat(path)
    except OSError:
        return b""
    cache_key = os.path.abspath(path)
    cached = _BINARY_CACHE.get(cache_key)
    sig = (int(stat.st_mtime_ns),)
    if cached and cached[0] == sig[0]:
        return cached[1]
    try:
        data = Path(path).read_bytes()
    except OSError:
        return b""
    _BINARY_CACHE[cache_key] = (sig[0], data)
    return data


def _load_json_file(path: str) -> Any:
    raw = _cached_text(path)
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _load_toml_file(path: str) -> dict[str, Any]:
    raw = _cached_text(path)
    if not raw.strip():
        return {}
    data: dict[str, Any] = {}
    for key, value in re.findall(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', raw, re.MULTILINE):
        if key not in data:
            data[key] = value
    return data


def _settings_model_name(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    model_cfg = payload.get("model")
    if isinstance(model_cfg, str):
        return model_cfg.strip()
    if isinstance(model_cfg, dict):
        return str(model_cfg.get("name", "")).strip()
    return ""


def _decode_js_string(value: str) -> str:
    decoded = value
    for _ in range(2):
        if "\\u" not in decoded and "\\x" not in decoded and "\\n" not in decoded and "\\t" not in decoded:
            break
        try:
            next_value = bytes(decoded, encoding="utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            break
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _title_from_description(model_id: str, description: str) -> str:
    text = description.strip()
    if not text:
        return model_id
    for sep in (" — ", " - ", " -- "):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if head:
                return head
    return text if len(text) <= 48 else model_id


def _normalize_model_entries(
    entries: list[dict[str, Any]],
    *,
    default_model: str = "",
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or entry.get("slug") or entry.get("name") or "").strip()
        if not model_id or model_id in seen:
            continue
        label = str(entry.get("label") or entry.get("display_name") or entry.get("name") or model_id).strip() or model_id
        description = str(entry.get("description", "")).strip()
        alias = str(entry.get("alias", "")).strip()
        item: dict[str, Any] = {"id": model_id, "label": label}
        if alias:
            item["alias"] = alias
        if description:
            item["description"] = description
        normalized.append(item)
        seen.add(model_id)

    if default_model and default_model not in seen:
        normalized.insert(0, {
            "id": default_model,
            "label": default_model,
            "description": "Configured current model",
        })
        seen.add(default_model)

    if default_model:
        for item in normalized:
            item["default"] = item["id"] == default_model
    elif normalized:
        normalized[0]["default"] = True
    return normalized


def _registry_engine_key(engine: str) -> str:
    key = str(engine or "").strip().lower()
    if key == "openai":
        return "codex"
    if key.startswith("claude"):
        return "claude"
    return key


def _resolved_qwen_cli_path(path: str = "") -> str:
    if path:
        return path
    binary = shutil.which("qwen")
    if not binary:
        return ""
    try:
        return str(Path(binary).resolve())
    except OSError:
        return ""


def _resolved_claude_cli_path(path: str = "") -> str:
    if path:
        return path
    binary = shutil.which("claude")
    if not binary:
        return ""
    try:
        return str(Path(binary).resolve())
    except OSError:
        return ""


def _parse_claude_model_id(model_id: str) -> tuple[str, int, int, int] | None:
    modern = re.match(r"^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d+))?(?:-(\d{8}))?$", model_id)
    if modern:
        family, major, minor_or_stamp, stamp = modern.groups()
        minor = 0
        if stamp:
            minor = int(minor_or_stamp or 0)
        elif minor_or_stamp:
            if len(minor_or_stamp) == 8:
                stamp = minor_or_stamp
            else:
                minor = int(minor_or_stamp)
        return (family, int(major or 0), minor, int(stamp or 0))

    legacy = re.match(r"^claude-(\d+)(?:-(\d+))?-(opus|sonnet|haiku)(?:-(\d{8}))?$", model_id)
    if legacy:
        major, minor_or_stamp, family, stamp = legacy.groups()
        minor = 0
        if stamp:
            minor = int(minor_or_stamp or 0)
        elif minor_or_stamp:
            if len(minor_or_stamp) == 8:
                stamp = minor_or_stamp
            else:
                minor = int(minor_or_stamp)
        return (family, int(major or 0), minor, int(stamp or 0))
    return None


def _claude_model_label(model_id: str) -> str:
    alias = model_id.strip().lower()
    if alias in {"opus", "sonnet", "haiku"}:
        return alias.title()
    parsed = _parse_claude_model_id(model_id)
    if not parsed:
        return model_id
    family, major, minor, _stamp = parsed
    version = f"{major}.{minor}" if minor else str(major)
    return f"{family.title()} {version}"


def _claude_models_from_cli(
    *,
    settings_path: str = "",
    binary_path: str = "",
) -> list[dict[str, Any]]:
    cfg_path = settings_path or str(Path.home() / ".claude" / "settings.json")
    settings = _load_json_file(cfg_path)
    current_model = _settings_model_name(settings)
    raw = _cached_bytes(_resolved_claude_cli_path(binary_path))
    candidates: set[str] = set()
    for pattern in (
        rb"claude-(?:opus|sonnet|haiku)-\d+(?:-\d+)?(?:-\d{8})?",
        rb"claude-\d+(?:-\d+)?-(?:opus|sonnet|haiku)(?:-\d{8})?",
    ):
        for match in re.findall(pattern, raw):
            try:
                candidates.add(match.decode("ascii"))
            except UnicodeDecodeError:
                continue
    latest_by_family: dict[str, tuple[tuple[int, int, int, int], str]] = {}
    for model_id in candidates:
        parsed = _parse_claude_model_id(model_id)
        if not parsed:
            continue
        family, major, minor, stamp = parsed
        rank = (major, minor, stamp, len(model_id))
        current = latest_by_family.get(family)
        if current is None or rank > current[0]:
            latest_by_family[family] = (rank, model_id)
    entries: list[dict[str, Any]] = []
    for family in ("opus", "sonnet", "haiku"):
        match = latest_by_family.get(family)
        if not match:
            continue
        model_id = match[1]
        entries.append({"id": model_id, "alias": family, "label": _claude_model_label(model_id)})
    current_key = current_model.strip().lower()
    if current_key in latest_by_family:
        current_model = latest_by_family[current_key][1]
    if current_model and not any(str(item.get("id", "")).strip() == current_model for item in entries):
        entries.insert(0, {
            "id": current_model,
            "label": _claude_model_label(current_model),
            "description": "Configured current model",
        })
    if not entries and not current_model:
        return []
    return _normalize_model_entries(entries, default_model=current_model)


def _resolved_gemini_models_path(path: str = "") -> str:
    if path:
        return path
    binary = shutil.which("gemini")
    if not binary:
        return ""
    try:
        package_root = Path(binary).resolve().parents[1]
    except OSError:
        return ""
    models_js = package_root / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "src" / "config" / "models.js"
    return str(models_js)


def _qwen_oauth_models(cli_js_path: str = "") -> list[dict[str, Any]]:
    path = _resolved_qwen_cli_path(cli_js_path)
    raw = _cached_text(path)
    if not raw:
        return []
    match = re.search(
        r"QWEN_OAUTH_MODELS\s*=\s*\[(.*?)\]\s*;\s*QWEN_OAUTH_ALLOWED_MODELS",
        raw,
        flags=re.DOTALL,
    )
    if not match:
        return []
    block = match.group(1)
    entries: list[dict[str, Any]] = []
    for item_match in re.finditer(
        r'id:\s*"([^"]+)"\s*,\s*name:\s*"([^"]+)"\s*,\s*description:\s*"([^"]+)"',
        block,
        flags=re.DOTALL,
    ):
        model_id = _decode_js_string(item_match.group(1)).strip()
        name = _decode_js_string(item_match.group(2)).strip() or model_id
        description = _decode_js_string(item_match.group(3)).strip()
        label = _title_from_description(name, description)
        entries.append({"id": model_id, "label": label, "description": description})
    return entries


def _qwen_models_from_cli(
    *,
    settings_path: str = "",
    cli_js_path: str = "",
) -> list[dict[str, Any]]:
    cfg_path = settings_path or str(Path.home() / ".qwen" / "settings.json")
    settings = _load_json_file(cfg_path)
    current_model = _settings_model_name(settings)
    selected_type = ""
    provider_models: list[dict[str, Any]] = []
    if isinstance(settings, dict):
        selected_type = str(settings.get("security", {}).get("auth", {}).get("selectedType", "")).strip()
        model_providers = settings.get("modelProviders", {})
        if isinstance(model_providers, dict) and selected_type:
            raw_models = model_providers.get(selected_type)
            if isinstance(raw_models, list):
                for item in raw_models:
                    if not isinstance(item, dict):
                        continue
                    model_id = str(item.get("id") or item.get("name") or "").strip()
                    if not model_id:
                        continue
                    description = str(item.get("description", "")).strip()
                    label = str(item.get("name", "")).strip() or _title_from_description(model_id, description)
                    provider_models.append({"id": model_id, "label": label, "description": description})
    if not provider_models and selected_type == "qwen-oauth":
        provider_models = _qwen_oauth_models(cli_js_path)
    if not provider_models and not current_model:
        return []
    default_model = current_model or next(
        (str(item.get("id", "")).strip() for item in provider_models if item.get("default")),
        "",
    )
    return _normalize_model_entries(provider_models, default_model=default_model)


def _gemini_model_constants(models_js_path: str = "") -> dict[str, str]:
    path = _resolved_gemini_models_path(models_js_path)
    raw = _cached_text(path)
    if not raw:
        return {}
    constants: dict[str, str] = {}
    for name, value in re.findall(r"export const ([A-Z0-9_]+)\s*=\s*'([^']+)';", raw):
        constants[name] = value
    return constants


def _resolve_gemini_selected_model(current_model: str, constants: dict[str, str]) -> str:
    model = current_model.strip()
    if not model:
        return constants.get("PREVIEW_GEMINI_MODEL_AUTO", "auto-gemini-3")
    alias_map = {
        "auto": constants.get("PREVIEW_GEMINI_MODEL_AUTO", "auto-gemini-3"),
        "pro": constants.get("PREVIEW_GEMINI_MODEL", "gemini-3-pro-preview"),
        "flash": constants.get("PREVIEW_GEMINI_FLASH_MODEL", "gemini-3-flash-preview"),
        "flash-lite": constants.get("DEFAULT_GEMINI_FLASH_LITE_MODEL", "gemini-2.5-flash-lite"),
    }
    return alias_map.get(model, model)


def _gemini_models_from_cli(
    *,
    settings_path: str = "",
    models_js_path: str = "",
) -> list[dict[str, Any]]:
    cfg_path = settings_path or str(Path.home() / ".gemini" / "settings.json")
    settings = _load_json_file(cfg_path)
    constants = _gemini_model_constants(models_js_path)
    if not constants:
        return []

    current_model = os.environ.get("GEMINI_MODEL", "").strip() or _settings_model_name(settings)
    default_model = _resolve_gemini_selected_model(current_model, constants)
    entries = [
        {
            "id": constants.get("PREVIEW_GEMINI_MODEL_AUTO", "auto-gemini-3"),
            "label": "Auto (Gemini 3)",
            "description": "Gemini CLI default auto-routing",
        },
        {
            "id": constants.get("DEFAULT_GEMINI_MODEL_AUTO", "auto-gemini-2.5"),
            "label": "Auto (Gemini 2.5)",
            "description": "Gemini CLI stable auto-routing",
        },
        {"id": constants.get("DEFAULT_GEMINI_MODEL", "gemini-2.5-pro"), "label": constants.get("DEFAULT_GEMINI_MODEL", "gemini-2.5-pro")},
        {"id": constants.get("DEFAULT_GEMINI_FLASH_MODEL", "gemini-2.5-flash"), "label": constants.get("DEFAULT_GEMINI_FLASH_MODEL", "gemini-2.5-flash")},
        {"id": constants.get("DEFAULT_GEMINI_FLASH_LITE_MODEL", "gemini-2.5-flash-lite"), "label": constants.get("DEFAULT_GEMINI_FLASH_LITE_MODEL", "gemini-2.5-flash-lite")},
    ]
    return _normalize_model_entries(entries, default_model=default_model)


def _codex_models_from_cli(
    *,
    config_path: str = "",
    cache_path: str = "",
) -> list[dict[str, Any]]:
    cfg_path = config_path or str(Path.home() / ".codex" / "config.toml")
    models_path = cache_path or str(Path.home() / ".codex" / "models_cache.json")
    config = _load_toml_file(cfg_path)
    current_model = str(config.get("model", "")).strip() if isinstance(config, dict) else ""
    cache_payload = _load_json_file(models_path)
    entries: list[dict[str, Any]] = []
    if isinstance(cache_payload, dict):
        cache_models = cache_payload.get("models", [])
        if isinstance(cache_models, list):
            visible_models = [
                item for item in cache_models
                if isinstance(item, dict) and str(item.get("visibility", "list")).strip() == "list"
            ]
            visible_models.sort(key=lambda item: (int(item.get("priority", 9999)), str(item.get("display_name", ""))))
            for item in visible_models:
                model_id = str(item.get("slug", "")).strip()
                if not model_id:
                    continue
                entries.append({
                    "id": model_id,
                    "label": str(item.get("display_name", "")).strip() or model_id,
                    "description": str(item.get("description", "")).strip(),
                })
    if not entries and not current_model:
        return []
    return _normalize_model_entries(entries, default_model=current_model)


def build_engine_model_registry(
    *,
    engine_models: dict[str, dict[str, Any]],
    detect_available_engines_fn: Callable[[], set[str]],
    claude_models_from_cli_fn: Callable[[], list[dict[str, Any]]],
    codex_models_from_cli_fn: Callable[[], list[dict[str, Any]]],
    gemini_models_from_cli_fn: Callable[[], list[dict[str, Any]]],
    qwen_models_from_cli_fn: Callable[[], list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    available = detect_available_engines_fn()
    for engine, spec in engine_models.items():
        models = [dict(item) for item in spec.get("models", [])]
        source = "static"
        if engine == "claude":
            discovered = claude_models_from_cli_fn()
            if discovered:
                models = discovered
                source = "claude-settings+cli"
        elif engine == "codex":
            discovered = codex_models_from_cli_fn()
            if discovered:
                models = discovered
                source = "codex-config+cache"
        elif engine == "gemini":
            discovered = gemini_models_from_cli_fn()
            if discovered:
                models = discovered
                source = "gemini-settings+cli"
        elif engine == "qwen":
            discovered = qwen_models_from_cli_fn()
            if discovered:
                models = discovered
                source = "qwen-settings+cli"
        registry[engine] = {
            "models": models,
            "cli_flag": spec["cli_flag"],
            "available": engine in available,
            "source": source,
        }
    return registry


def resolve_engine_model_choice(engine: str, model_id: str, registry: dict[str, dict[str, Any]]) -> str | None:
    raw = str(model_id or "").strip()
    if not raw:
        return ""
    engine_data = registry.get(_registry_engine_key(engine), {})
    entries = engine_data.get("models", []) if isinstance(engine_data, dict) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id", "")).strip()
        if entry_id == raw:
            return entry_id
    lowered = raw.lower()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        alias = str(entry.get("alias", "")).strip().lower()
        entry_id = str(entry.get("id", "")).strip()
        if alias and alias == lowered and entry_id:
            return entry_id
    return None


def detect_available_engines(known_engines: set[str]) -> set[str]:
    return runtime_layout.detect_available_engines(known_engines)
