#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
CONFIG_DIR = ROOT_DIR / "config"
MCP_CATALOG_PATH = CONFIG_DIR / "mcp_catalog.json"
DEFAULT_OUTPUT_PATH = CONFIG_DIR / "capability_library.json"
REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
SUPPORTED_CLIS = ("claude_code", "codex", "gemini_cli", "qwen_code")
TRUST_OFFICIAL = "official"
TRUST_REGISTRY = "registry"
TRUST_BRIDGE = "bridge"
TRUST_LEGACY = "legacy"

TASK_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("code", ("code", "coding", "compile", "build", "repo", "repository", "git", "test", "debug", "developer", "programming")),
    ("docs", ("docs", "documentation", "knowledge", "wiki", "confluence", "notion", "manual")),
    ("browser", ("browser", "crawl", "scrape", "search engine", "website", "web", "playwright", "page")),
    ("database", ("database", "sql", "postgres", "mysql", "sqlite", "mongodb", "warehouse", "vector", "query engine")),
    ("cloud", ("aws", "azure", "gcp", "cloud", "cloudflare", "workers", "vercel", "render")),
    ("devops", ("docker", "kubernetes", "deploy", "deployment", "infra", "monitor", "ci", "cd", "terraform")),
    ("files", ("file", "files", "storage", "drive", "s3", "r2", "gcs", "pdf", "document", "docsx")),
    ("productivity", ("calendar", "todo", "task", "email", "slack", "discord", "meeting", "project management")),
    ("communication", ("chat", "slack", "discord", "whatsapp", "sms", "phone", "email", "message")),
    ("security", ("security", "identity", "auth", "oauth", "token", "jwt", "trust", "secret", "vulnerability")),
    ("finance", ("trading", "market", "portfolio", "crypto", "billing", "invoice", "payment", "ads performance")),
    ("automation", ("automation", "workflow", "agent", "mcp", "integration", "tooling", "orchestration")),
    ("research", ("research", "paper", "scholar", "retrieve", "retrieval", "rag", "search", "index")),
    ("analytics", ("analytics", "metrics", "dashboard", "reporting", "ads", "campaign", "observability")),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BridgeCapabilityLibraryBuilder/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object from {url}")
    return data


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object in {path}")
    return data


def _slug_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entry"


def _first_non_empty(*values: str) -> str:
    for value in values:
        value = str(value or "").strip()
        if value:
            return value
    return ""


def _parse_repo_owner(repo_url: str) -> str:
    if "github.com/" not in repo_url:
        return ""
    tail = repo_url.split("github.com/", 1)[1].strip("/")
    if not tail:
        return ""
    return tail.split("/", 1)[0]


def _infer_vendor(owner: str, repo_url: str, slug_name: str) -> str:
    repo_owner = _parse_repo_owner(repo_url)
    if repo_owner:
        return repo_owner.lower()
    normalized_owner = owner.strip().lower()
    if "." in normalized_owner:
        return normalized_owner.split(".")[-1]
    if normalized_owner:
        return normalized_owner
    if "/" in slug_name:
        return slug_name.split("/", 1)[0].lower()
    return "unknown"


def _infer_auth_mode(
    env_schema: dict[str, Any] | None,
    headers: list[dict[str, Any]],
) -> str:
    env_schema = env_schema or {}
    required = {
        str(name).strip().upper()
        for name in list(env_schema.get("required", []) or [])
        if str(name).strip()
    }
    properties = {
        str(name).strip().upper()
        for name in dict(env_schema.get("properties", {}) or {}).keys()
        if str(name).strip()
    }
    secret_headers = {
        str(item.get("name", "")).strip().upper()
        for item in headers
        if isinstance(item, dict) and bool(item.get("isSecret"))
    }
    required_headers = {
        str(item.get("name", "")).strip().upper()
        for item in headers
        if isinstance(item, dict) and bool(item.get("isRequired"))
    }
    combined = required | properties | secret_headers | required_headers
    if not combined:
        return "none"
    if any("OAUTH" in name for name in combined):
        return "oauth"
    secretish = ("TOKEN", "KEY", "SECRET", "PASSWORD", "AUTH", "BEARER")
    has_secret = any(any(part in name for part in secretish) for name in combined)
    if has_secret and (required or required_headers or secret_headers):
        return "required_api_key"
    if has_secret:
        return "optional_api_key"
    return "unknown"


def _infer_task_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags = [tag for tag, keywords in TASK_RULES if any(keyword in lowered for keyword in keywords)]
    if "mcp" not in lowered and "automation" not in tags:
        tags.append("automation")
    if not tags:
        tags.append("automation")
    return sorted(set(tags))


def _infer_engine_compatibility(*, documented: tuple[str, ...] = (), inferred_all_mcp: bool = False) -> dict[str, str]:
    compatibility = {engine: "unsupported" for engine in SUPPORTED_CLIS}
    for engine in documented:
        compatibility[engine] = "documented"
    if inferred_all_mcp:
        for engine in SUPPORTED_CLIS:
            if compatibility[engine] == "unsupported":
                compatibility[engine] = "inferred"
    return compatibility


def _install_method(kind: str, **kwargs: Any) -> dict[str, Any]:
    payload = {"kind": kind}
    for key, value in kwargs.items():
        if value not in ("", None, [], {}):
            payload[key] = value
    return payload


def _build_runtime_entries() -> list[dict[str, Any]]:
    catalog = _load_json(MCP_CATALOG_PATH)
    runtime_specs = catalog.get("runtime_servers", {})
    if not isinstance(runtime_specs, dict):
        raise ValueError("runtime_servers missing in mcp_catalog.json")
    entries: list[dict[str, Any]] = []
    for name, spec in runtime_specs.items():
        if not isinstance(spec, dict):
            continue
        owner = str(spec.get("owner", "bridge")).strip().lower() or "bridge"
        reproducible = bool(spec.get("reproducible"))
        production_ready = bool(spec.get("production_ready"))
        status = "runtime_verified" if reproducible and production_ready else "legacy_attached"
        trust_tier = TRUST_BRIDGE if status == "runtime_verified" else TRUST_LEGACY
        entry = {
            "id": f"bridge-runtime::{name}",
            "name": name,
            "title": name,
            "vendor": owner,
            "owner": owner,
            "summary": f"Bridge runtime MCP entry '{name}' from the repo-local MCP catalog.",
            "type": "mcp",
            "protocol": "mcp",
            "transport": [str(spec.get("transport", "stdio")).strip() or "stdio"],
            "install_methods": [
                _install_method(
                    "runtime_command",
                    command=spec.get("command", ""),
                    args=list(spec.get("args", []) or []),
                )
            ],
            "auth_mode": "none",
            "task_tags": _infer_task_tags(f"{name} {owner} runtime bridge mcp"),
            "engine_compatibility": _infer_engine_compatibility(inferred_all_mcp=True),
            "compatibility_basis": "bridge_runtime_and_mcp_protocol",
            "reproducible": reproducible,
            "runtime_verified": status == "runtime_verified",
            "status": status,
            "trust_tier": trust_tier,
            "official_vendor": owner in {"bridge", "microsoft"},
            "source_registry": "bridge_runtime_catalog",
            "source_authority": "bridge_repo",
            "source_url": str(MCP_CATALOG_PATH.relative_to(ROOT_DIR)),
            "documentation_urls": [],
        }
        entries.append(entry)
    return entries


def _official_entries() -> list[dict[str, Any]]:
    docs_entries: list[dict[str, Any]] = [
        {
            "id": "official::openai-docs-mcp",
            "name": "OpenAI Docs MCP",
            "title": "Official OpenAI Docs MCP",
            "vendor": "openai",
            "owner": "openai",
            "summary": "Official hosted MCP for OpenAI API, Apps SDK, and ChatGPT developer documentation.",
            "type": "mcp",
            "protocol": "mcp",
            "transport": ["streamable_http"],
            "install_methods": [
                _install_method("remote_mcp", url="https://mcp.openai.com/mcp"),
            ],
            "auth_mode": "none",
            "task_tags": ["docs", "research", "code", "automation"],
            "engine_compatibility": _infer_engine_compatibility(documented=("codex",), inferred_all_mcp=True),
            "compatibility_basis": "official_openai_docs_and_mcp_protocol",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://platform.openai.com/docs/docs-mcp",
            "documentation_urls": [
                "https://platform.openai.com/docs/docs-mcp",
                "https://platform.openai.com/docs/mcp/",
            ],
        },
        {
            "id": "official::anthropic-claude-code-mcp-client",
            "name": "Claude Code MCP Client",
            "title": "Claude Code MCP Support",
            "vendor": "anthropic",
            "owner": "anthropic",
            "summary": "Official Claude Code support for configuring and consuming MCP servers from the CLI.",
            "type": "native-cli-integration",
            "protocol": "mcp",
            "transport": ["stdio", "sse", "streamable_http"],
            "install_methods": [_install_method("builtin_cli_capability", command="claude")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code", "docs"],
            "engine_compatibility": _infer_engine_compatibility(documented=("claude_code",)),
            "compatibility_basis": "official_anthropic_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://docs.anthropic.com/en/docs/claude-code/mcp",
            "documentation_urls": [
                "https://docs.anthropic.com/en/docs/claude-code/mcp",
                "https://docs.anthropic.com/en/docs/claude-code/settings",
            ],
        },
        {
            "id": "official::anthropic-claude-code-mcp-server",
            "name": "Claude Code as MCP Server",
            "title": "Claude Code MCP Server Mode",
            "vendor": "anthropic",
            "owner": "anthropic",
            "summary": "Official server mode that exposes Claude Code itself as an MCP server via `claude mcp serve`.",
            "type": "tool-adapter",
            "protocol": "mcp",
            "transport": ["stdio"],
            "install_methods": [_install_method("command", command="claude", args=["mcp", "serve"])],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("claude_code",)),
            "compatibility_basis": "official_anthropic_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://docs.anthropic.com/en/docs/claude-code/sdk",
            "documentation_urls": [
                "https://docs.anthropic.com/en/docs/claude-code/sdk",
                "https://docs.anthropic.com/en/docs/claude-code/mcp",
            ],
        },
        {
            "id": "official::anthropic-claude-code-hooks",
            "name": "Claude Code Hooks",
            "title": "Claude Code Hooks",
            "vendor": "anthropic",
            "owner": "anthropic",
            "summary": "Official Claude Code hook system for pre/post command automation inside the CLI.",
            "type": "hook",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="claude")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "devops", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("claude_code",)),
            "compatibility_basis": "official_anthropic_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://docs.anthropic.com/en/docs/claude-code/hooks",
            "documentation_urls": ["https://docs.anthropic.com/en/docs/claude-code/hooks"],
        },
        {
            "id": "official::anthropic-claude-code-slash-commands",
            "name": "Claude Code Slash Commands",
            "title": "Claude Code Slash Commands",
            "vendor": "anthropic",
            "owner": "anthropic",
            "summary": "Official Claude Code slash command system for reusable prompt and workflow commands.",
            "type": "custom-command",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="claude")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "productivity", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("claude_code",)),
            "compatibility_basis": "official_anthropic_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://docs.anthropic.com/en/docs/claude-code/slash-commands",
            "documentation_urls": ["https://docs.anthropic.com/en/docs/claude-code/slash-commands"],
        },
        {
            "id": "official::anthropic-claude-code-subagents",
            "name": "Claude Code Subagents",
            "title": "Claude Code Subagents",
            "vendor": "anthropic",
            "owner": "anthropic",
            "summary": "Official subagent workflow support in Claude Code for bounded delegated tasks.",
            "type": "subagent",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="claude")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code", "productivity"],
            "engine_compatibility": _infer_engine_compatibility(documented=("claude_code",)),
            "compatibility_basis": "official_anthropic_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://docs.anthropic.com/en/docs/claude-code/sub-agents",
            "documentation_urls": ["https://docs.anthropic.com/en/docs/claude-code/sub-agents"],
        },
        {
            "id": "official::google-gemini-cli-mcp",
            "name": "Gemini CLI MCP Support",
            "title": "Gemini CLI MCP Support",
            "vendor": "google",
            "owner": "google",
            "summary": "Official Gemini CLI support for consuming and configuring MCP servers.",
            "type": "native-cli-integration",
            "protocol": "mcp",
            "transport": ["stdio", "sse", "streamable_http"],
            "install_methods": [_install_method("builtin_cli_capability", command="gemini")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code", "docs"],
            "engine_compatibility": _infer_engine_compatibility(documented=("gemini_cli",)),
            "compatibility_basis": "official_gemini_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://geminicli.com/docs/tools/mcp-server",
            "documentation_urls": [
                "https://geminicli.com/docs/tools/mcp-server",
                "https://geminicli.com/docs/cli/configuration",
            ],
        },
        {
            "id": "official::google-gemini-cli-extensions",
            "name": "Gemini CLI Extensions",
            "title": "Gemini CLI Extensions",
            "vendor": "google",
            "owner": "google",
            "summary": "Official Gemini CLI extension system for packaging prompts, tools, hooks, and agent behaviors.",
            "type": "extension",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="gemini")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "productivity", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("gemini_cli",)),
            "compatibility_basis": "official_gemini_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://geminicli.com/docs/extensions/overview",
            "documentation_urls": [
                "https://geminicli.com/docs/extensions/overview",
                "https://geminicli.com/docs/extensions/reference",
            ],
        },
        {
            "id": "official::google-gemini-cli-custom-commands",
            "name": "Gemini CLI Custom Commands",
            "title": "Gemini CLI Custom Commands",
            "vendor": "google",
            "owner": "google",
            "summary": "Official Gemini CLI custom command mechanism for reusable prompt and workflow shortcuts.",
            "type": "custom-command",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="gemini")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "productivity"],
            "engine_compatibility": _infer_engine_compatibility(documented=("gemini_cli",)),
            "compatibility_basis": "official_gemini_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://geminicli.com/docs/cli/commands",
            "documentation_urls": ["https://geminicli.com/docs/cli/commands"],
        },
        {
            "id": "official::google-maps-mcp-server",
            "name": "Google Maps MCP Server",
            "title": "Official Google Maps MCP Server",
            "vendor": "google",
            "owner": "googlemaps",
            "summary": "Official Google Maps Platform MCP server repository for places, routes, geocoding, and map data tasks.",
            "type": "mcp",
            "protocol": "mcp",
            "transport": ["stdio"],
            "install_methods": [_install_method("source_repo", url="https://github.com/googlemaps/google-maps-mcp-server")],
            "auth_mode": "required_api_key",
            "task_tags": ["research", "analytics", "automation"],
            "engine_compatibility": _infer_engine_compatibility(inferred_all_mcp=True),
            "compatibility_basis": "official_google_repo_and_mcp_protocol",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_repo",
            "source_authority": "official_repo",
            "source_url": "https://github.com/googlemaps/google-maps-mcp-server",
            "documentation_urls": ["https://github.com/googlemaps/google-maps-mcp-server"],
        },
        {
            "id": "official::google-genai-toolbox",
            "name": "Google GenAI Toolbox",
            "title": "Official Google GenAI Toolbox",
            "vendor": "google",
            "owner": "googleapis",
            "summary": "Official Google toolbox for exposing databases and services to AI clients via MCP-compatible tooling.",
            "type": "tool-adapter",
            "protocol": "mcp",
            "transport": ["stdio", "http"],
            "install_methods": [_install_method("source_repo", url="https://github.com/googleapis/genai-toolbox")],
            "auth_mode": "mixed",
            "task_tags": ["database", "automation", "code"],
            "engine_compatibility": _infer_engine_compatibility(inferred_all_mcp=True),
            "compatibility_basis": "official_google_repo_and_mcp_protocol",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_repo",
            "source_authority": "official_repo",
            "source_url": "https://github.com/googleapis/genai-toolbox",
            "documentation_urls": ["https://github.com/googleapis/genai-toolbox"],
        },
        {
            "id": "official::qwen-code-mcp",
            "name": "Qwen Code MCP Support",
            "title": "Qwen Code MCP Support",
            "vendor": "qwen",
            "owner": "qwen",
            "summary": "Official Qwen Code support for configuring and consuming MCP servers.",
            "type": "native-cli-integration",
            "protocol": "mcp",
            "transport": ["stdio", "sse", "streamable_http"],
            "install_methods": [_install_method("builtin_cli_capability", command="qwen")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code", "docs"],
            "engine_compatibility": _infer_engine_compatibility(documented=("qwen_code",)),
            "compatibility_basis": "official_qwen_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://qwen.readthedocs.io/en/latest/framework/qwen-code/mcp.html",
            "documentation_urls": ["https://qwen.readthedocs.io/en/latest/framework/qwen-code/mcp.html"],
        },
        {
            "id": "official::qwen-code-extensions",
            "name": "Qwen Code Extensions",
            "title": "Qwen Code Extensions",
            "vendor": "qwen",
            "owner": "qwen",
            "summary": "Official Qwen Code extension system for packaging reusable CLI behaviors and integrations.",
            "type": "extension",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="qwen")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "productivity", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("qwen_code",)),
            "compatibility_basis": "official_qwen_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://qwen.readthedocs.io/en/latest/framework/qwen-code/extensions.html",
            "documentation_urls": ["https://qwen.readthedocs.io/en/latest/framework/qwen-code/extensions.html"],
        },
        {
            "id": "official::qwen-code-hooks",
            "name": "Qwen Code Hooks",
            "title": "Qwen Code Hooks",
            "vendor": "qwen",
            "owner": "qwen",
            "summary": "Official Qwen Code hook system for intercepting and automating CLI events.",
            "type": "hook",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="qwen")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "devops", "code"],
            "engine_compatibility": _infer_engine_compatibility(documented=("qwen_code",)),
            "compatibility_basis": "official_qwen_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://qwen.readthedocs.io/en/latest/framework/qwen-code/hooks.html",
            "documentation_urls": ["https://qwen.readthedocs.io/en/latest/framework/qwen-code/hooks.html"],
        },
        {
            "id": "official::qwen-code-custom-commands",
            "name": "Qwen Code Custom Commands",
            "title": "Qwen Code Custom Commands",
            "vendor": "qwen",
            "owner": "qwen",
            "summary": "Official Qwen Code custom commands for reusable task-specific prompt and workflow commands.",
            "type": "custom-command",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="qwen")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "productivity"],
            "engine_compatibility": _infer_engine_compatibility(documented=("qwen_code",)),
            "compatibility_basis": "official_qwen_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://qwen.readthedocs.io/en/latest/framework/qwen-code/custom-commands.html",
            "documentation_urls": ["https://qwen.readthedocs.io/en/latest/framework/qwen-code/custom-commands.html"],
        },
        {
            "id": "official::qwen-code-subagents",
            "name": "Qwen Code Subagents",
            "title": "Qwen Code Subagents",
            "vendor": "qwen",
            "owner": "qwen",
            "summary": "Official Qwen Code subagent system for delegated, scoped task execution inside the CLI.",
            "type": "subagent",
            "protocol": "local_cli",
            "transport": ["local_process"],
            "install_methods": [_install_method("builtin_cli_capability", command="qwen")],
            "auth_mode": "n/a",
            "task_tags": ["automation", "code", "productivity"],
            "engine_compatibility": _infer_engine_compatibility(documented=("qwen_code",)),
            "compatibility_basis": "official_qwen_docs",
            "reproducible": True,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": TRUST_OFFICIAL,
            "official_vendor": True,
            "source_registry": "official_docs",
            "source_authority": "official_docs",
            "source_url": "https://qwen.readthedocs.io/en/latest/framework/qwen-code/subagents.html",
            "documentation_urls": ["https://qwen.readthedocs.io/en/latest/framework/qwen-code/subagents.html"],
        },
    ]
    return docs_entries


def _normalize_registry_entry(item: dict[str, Any]) -> dict[str, Any] | None:
    server = item.get("server")
    meta = item.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
    if not isinstance(server, dict) or not isinstance(meta, dict) or not meta.get("isLatest"):
        return None
    slug_name = str(server.get("name", "")).strip()
    if not slug_name:
        return None
    owner = slug_name.split("/", 1)[0] if "/" in slug_name else slug_name
    repo = dict(server.get("repository", {}) or {})
    repo_url = str(repo.get("url", "")).strip()
    remotes = list(server.get("remotes", []) or [])
    packages = list(server.get("packages", []) or [])
    headers: list[dict[str, Any]] = []
    for remote in remotes:
        if isinstance(remote, dict):
            headers.extend(list(remote.get("headers", []) or []))
    transport = {
        str(remote.get("type", "")).strip()
        for remote in remotes
        if isinstance(remote, dict) and str(remote.get("type", "")).strip()
    }
    transport.update(
        str(dict(package.get("transport", {}) or {}).get("type", "")).strip()
        for package in packages
        if isinstance(package, dict)
    )
    transport.discard("")
    if not transport:
        transport.add("unknown")
    install_methods: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        install_methods.append(
            _install_method(
                "registry_package",
                registry=package.get("registryType", ""),
                identifier=package.get("identifier", ""),
                version=package.get("version", ""),
                transport=dict(package.get("transport", {}) or {}).get("type", ""),
            )
        )
    for remote in remotes:
        if not isinstance(remote, dict):
            continue
        install_methods.append(
            _install_method(
                "remote_mcp",
                url=remote.get("url", ""),
                transport=remote.get("type", ""),
            )
        )
    if repo_url:
        install_methods.append(_install_method("source_repo", url=repo_url))
    summary = _first_non_empty(str(server.get("description", "")).strip(), str(server.get("title", "")).strip(), slug_name)
    env_schema = server.get("environmentVariablesJsonSchema")
    if not isinstance(env_schema, dict):
        env_schema = {}
    source_url = _first_non_empty(str(server.get("websiteUrl", "")).strip(), repo_url)
    compatibility = _infer_engine_compatibility(inferred_all_mcp=True)
    return {
        "id": f"mcp-registry::{_slug_id(slug_name)}",
        "name": str(server.get("title", "")).strip() or slug_name.split("/", 1)[-1],
        "title": str(server.get("title", "")).strip() or slug_name,
        "vendor": _infer_vendor(owner, repo_url, slug_name),
        "owner": owner.lower(),
        "summary": summary,
        "type": "mcp",
        "protocol": "mcp",
        "transport": sorted(transport),
        "install_methods": install_methods,
        "auth_mode": _infer_auth_mode(env_schema, headers),
        "task_tags": _infer_task_tags(f"{slug_name} {summary}"),
        "engine_compatibility": compatibility,
        "compatibility_basis": "mcp_protocol_inference",
        "reproducible": bool(install_methods),
        "runtime_verified": False,
        "status": "catalogued",
        "trust_tier": TRUST_REGISTRY,
        "official_vendor": False,
        "source_registry": "official_mcp_registry",
        "source_authority": "official_registry",
        "source_url": source_url or "https://modelcontextprotocol.io/registry",
        "documentation_urls": [
            url
            for url in [
                str(server.get("websiteUrl", "")).strip(),
                repo_url,
            ]
            if url
        ],
        "version": str(server.get("version", "")).strip(),
        "registry_slug": slug_name,
        "registry_status": str(meta.get("status", "")).strip(),
        "registry_published_at": str(meta.get("publishedAt", "")).strip(),
        "repository_url": repo_url,
    }


def _fetch_registry_entries(page_size: int, target_latest_entries: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cursor = ""
    latest_entries: dict[str, dict[str, Any]] = {}
    page_count = 0
    raw_count = 0
    while True:
        params = {"limit": str(page_size)}
        if cursor:
            params["cursor"] = cursor
        url = f"{REGISTRY_BASE_URL}?{urllib.parse.urlencode(params)}"
        data = _http_get_json(url)
        page_count += 1
        records = list(data.get("servers", []) or [])
        raw_count += len(records)
        for item in records:
            if not isinstance(item, dict):
                continue
            entry = _normalize_registry_entry(item)
            if entry is None:
                continue
            latest_entries[entry["id"]] = entry
        metadata = dict(data.get("metadata", {}) or {})
        cursor = str(metadata.get("nextCursor", "")).strip()
        if target_latest_entries > 0 and len(latest_entries) >= target_latest_entries:
            break
        if not cursor:
            break
    summary = {
        "page_count": page_count,
        "raw_registry_records": raw_count,
        "latest_entry_count": len(latest_entries),
        "target_latest_entries": target_latest_entries,
        "page_size": page_size,
    }
    return list(latest_entries.values()), summary


AWESOME_MCP_URL = "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md"
BESTOF_MCP_URL = "https://raw.githubusercontent.com/tolkonepiu/best-of-mcp-servers/main/README.md"


def _fetch_github_readme(url: str) -> str:
    """Fetch raw README content from GitHub."""
    request = urllib.request.Request(url, headers={"User-Agent": "BridgeCapabilityLibraryBuilder/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _parse_awesome_readme(readme: str, source_registry: str) -> list[dict[str, Any]]:
    """Parse awesome-mcp-servers style README into library entries.

    Looks for lines like: - [Name](url) - Description
    Tracks current heading as category.
    """
    entries: list[dict[str, Any]] = []
    current_category = ""
    link_pattern = re.compile(r"[-*]\s+\[([^\]]+)\]\(([^)]+)\)\s*[-–—]?\s*(.*)")

    for line in readme.split("\n"):
        line = line.strip()

        # Track category from headings
        if line.startswith("###"):
            current_category = line.lstrip("#").strip()
            continue
        if line.startswith("##"):
            current_category = line.lstrip("#").strip()
            continue

        # Parse entry links
        match = link_pattern.match(line)
        if not match:
            continue

        name = match.group(1).strip()
        url = match.group(2).strip()
        description = match.group(3).strip()

        # Skip non-server entries (clients, tutorials, frameworks, badges)
        if not url or not name:
            continue
        if any(skip in url.lower() for skip in ["awesome.re", "img.shields.io", "discord", "reddit", "youtube"]):
            continue
        if any(skip in current_category.lower() for skip in ["client", "tutorial", "community", "legend", "framework", "tip"]):
            continue

        slug = _slug_id(name)
        entry_id = f"{source_registry}::{slug}"

        # Infer task tags from category
        task_tags = []
        for tag, keywords in TASK_RULES:
            cat_lower = (current_category + " " + description + " " + name).lower()
            if any(kw in cat_lower for kw in keywords):
                task_tags.append(tag)

        # Infer vendor from URL
        vendor = _parse_repo_owner(url) if "github.com" in url else "unknown"

        entry = {
            "id": entry_id,
            "name": name,
            "title": name,
            "vendor": vendor,
            "owner": vendor,
            "summary": description or f"MCP server: {name}",
            "type": "mcp",
            "protocol": "mcp",
            "transport": ["stdio"],
            "install_methods": [],
            "auth_mode": "unknown",
            "task_tags": task_tags or ["automation"],
            "engine_compatibility": {cli: "inferred" for cli in SUPPORTED_CLIS},
            "compatibility_basis": "mcp_protocol_inferred",
            "reproducible": False,
            "runtime_verified": False,
            "status": "catalogued",
            "trust_tier": "community",
            "official_vendor": False,
            "source_registry": source_registry,
            "source_authority": source_registry,
            "source_url": url,
            "documentation_urls": [url] if url else [],
            "category": current_category,
        }
        entries.append(entry)

    return entries


def _fetch_awesome_entries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and parse awesome-mcp-servers."""
    try:
        readme = _fetch_github_readme(AWESOME_MCP_URL)
        entries = _parse_awesome_readme(readme, "awesome_mcp_servers")
        summary = {"source": "awesome_mcp_servers", "url": AWESOME_MCP_URL, "entry_count": len(entries)}
        print(f"  awesome-mcp-servers: {len(entries)} entries parsed")
        return entries, summary
    except Exception as exc:
        print(f"  awesome-mcp-servers: FAILED ({exc})")
        return [], {"source": "awesome_mcp_servers", "error": str(exc), "entry_count": 0}


def _fetch_bestof_entries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and parse best-of-mcp-servers."""
    try:
        readme = _fetch_github_readme(BESTOF_MCP_URL)
        entries = _parse_awesome_readme(readme, "bestof_mcp_servers")
        summary = {"source": "bestof_mcp_servers", "url": BESTOF_MCP_URL, "entry_count": len(entries)}
        print(f"  best-of-mcp-servers: {len(entries)} entries parsed")
        return entries, summary
    except Exception as exc:
        print(f"  best-of-mcp-servers: FAILED ({exc})")
        return [], {"source": "bestof_mcp_servers", "error": str(exc), "entry_count": 0}


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = str(entry.get("id", "")).strip()
        if not entry_id:
            continue
        deduped[entry_id] = entry
    return sorted(deduped.values(), key=lambda item: (item.get("trust_tier", ""), item.get("name", ""), item.get("id", "")))


def build_library(page_size: int, registry_target: int) -> dict[str, Any]:
    print("Building capability library...")
    runtime_entries = _build_runtime_entries()
    print(f"  Bridge runtime: {len(runtime_entries)} entries")
    docs_entries = _official_entries()
    print(f"  Official docs: {len(docs_entries)} entries")
    registry_entries, registry_summary = _fetch_registry_entries(page_size=page_size, target_latest_entries=registry_target)
    print(f"  Official registry: {len(registry_entries)} entries")

    # Community sources
    awesome_entries, awesome_summary = _fetch_awesome_entries()
    bestof_entries, bestof_summary = _fetch_bestof_entries()

    all_entries = runtime_entries + docs_entries + registry_entries + awesome_entries + bestof_entries
    entries = _dedupe_entries(all_entries)

    official_count = sum(1 for entry in entries if entry.get("trust_tier") == TRUST_OFFICIAL)
    runtime_verified_count = sum(1 for entry in entries if entry.get("runtime_verified"))
    community_count = sum(1 for entry in entries if entry.get("trust_tier") == "community")

    print(f"  Total after dedup: {len(entries)} (official: {official_count}, community: {community_count})")

    metadata = {
        "version": 2,
        "generated_at": _utc_now_iso(),
        "entry_count": len(entries),
        "official_entry_count": official_count,
        "runtime_verified_count": runtime_verified_count,
        "community_entry_count": community_count,
        "sources": [
            {
                "name": "bridge_runtime_catalog",
                "type": "local_repo",
                "url": str(MCP_CATALOG_PATH.relative_to(ROOT_DIR)),
                "entry_count": len(runtime_entries),
            },
            {
                "name": "official_docs",
                "type": "curated",
                "url": "https://docs.anthropic.com/en/docs/claude-code/mcp",
                "entry_count": len(docs_entries),
            },
            {
                "name": "official_mcp_registry",
                "type": "live_api",
                "url": REGISTRY_BASE_URL,
                "entry_count": len(registry_entries),
                "fetch": registry_summary,
            },
            {
                "name": "awesome_mcp_servers",
                "type": "github_readme",
                "url": AWESOME_MCP_URL,
                "entry_count": awesome_summary.get("entry_count", 0),
            },
            {
                "name": "bestof_mcp_servers",
                "type": "github_readme",
                "url": BESTOF_MCP_URL,
                "entry_count": bestof_summary.get("entry_count", 0),
            },
        ],
        "bridge_target_clis": list(SUPPORTED_CLIS),
        "minimum_target_entry_count": 500,
    }
    return {"metadata": metadata, "entries": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Bridge capability library from live MCP sources.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output JSON path")
    parser.add_argument("--page-size", type=int, default=100, help="Registry API page size")
    parser.add_argument("--registry-target", type=int, default=0, help="Target latest MCP registry entries (0=all)")
    args = parser.parse_args(argv)

    library = build_library(page_size=max(10, min(args.page_size, 100)), registry_target=max(0, args.registry_target))
    entry_count = int(dict(library.get("metadata", {})).get("entry_count", 0))
    if entry_count < 500:
        raise SystemExit(f"capability library build failed: only {entry_count} entries generated")

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(library, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"Wrote {entry_count} entries to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
