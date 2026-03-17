"""API Key management routes for Bridge ACE.

Allows users to configure API keys for different AI providers
via the Control Center UI. Keys are stored encrypted via credential_store.
"""

from __future__ import annotations

import json
from typing import Any

# Lazy imports to avoid circular deps
_engine_backend = None
_credential_store = None


def _get_engine_backend():
    global _engine_backend
    if _engine_backend is None:
        import engine_backend
        _engine_backend = engine_backend
    return _engine_backend


def _get_credential_store():
    global _credential_store
    if _credential_store is None:
        import credential_store
        _credential_store = credential_store
    return _credential_store


# Provider metadata for UI rendering
API_PROVIDERS = [
    {
        "id": "anthropic",
        "name": "Anthropic (Claude)",
        "env_var": "ANTHROPIC_API_KEY",
        "engines": ["claude"],
        "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "docs_url": "https://console.anthropic.com/",
    },
    {
        "id": "openai",
        "name": "OpenAI (GPT/Codex)",
        "env_var": "OPENAI_API_KEY",
        "engines": ["codex", "gpt"],
        "models": ["gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-4o"],
        "docs_url": "https://platform.openai.com/api-keys",
    },
    {
        "id": "google",
        "name": "Google AI (Gemini)",
        "env_var": "GOOGLE_AI_API_KEY",
        "engines": ["gemini"],
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "docs_url": "https://aistudio.google.com/apikey",
    },
    {
        "id": "xai",
        "name": "xAI (Grok)",
        "env_var": "XAI_API_KEY",
        "engines": ["grok"],
        "models": ["grok-3", "grok-3-mini"],
        "docs_url": "https://console.x.ai/",
    },
    {
        "id": "alibaba",
        "name": "Alibaba (Qwen)",
        "env_var": "DASHSCOPE_API_KEY",
        "engines": ["qwen"],
        "models": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "docs_url": "https://dashscope.console.aliyun.com/",
    },
]


def handle_api_keys_get(handler, path: str) -> bool:
    """GET /api/keys — List configured API key providers and their status."""
    if path != "/api/keys":
        return False

    eb = _get_engine_backend()
    keys = eb.ApiKeyConfig.from_env()
    available = set(keys.available_providers())

    result = []
    for provider in API_PROVIDERS:
        pid = provider["id"]
        result.append({
            **provider,
            "configured": pid in available,
            "key_preview": _mask_key(keys.get_key(pid)),
        })

    handler._respond(200, {"providers": result})
    return True


def handle_api_keys_post(handler, path: str) -> bool:
    """POST /api/keys — Set API key for a provider."""
    if path != "/api/keys":
        return False

    data = handler._parse_json_body()
    if not data:
        handler._respond(400, {"error": "JSON body required"})
        return True

    provider = str(data.get("provider", "")).strip().lower()
    api_key = str(data.get("api_key", "")).strip()

    if not provider or not api_key:
        handler._respond(400, {"error": "provider and api_key are required"})
        return True

    # Validate provider
    valid_providers = {p["id"] for p in API_PROVIDERS}
    if provider not in valid_providers:
        handler._respond(400, {"error": f"Unknown provider: {provider}. Valid: {sorted(valid_providers)}"})
        return True

    # Store key in credential store (encrypted)
    try:
        cs = _get_credential_store()
        cs.store("api_keys", provider, api_key, agent_id="user")
    except Exception as exc:
        print(f"[api-keys] WARNING: Could not store in credential_store: {exc}")

    # Set environment variable for immediate use
    env_var = next((p["env_var"] for p in API_PROVIDERS if p["id"] == provider), None)
    if env_var:
        import os
        os.environ[env_var] = api_key

    # Re-initialize API backends
    eb = _get_engine_backend()
    results = eb.init_api_backends()

    handler._respond(200, {
        "ok": True,
        "provider": provider,
        "status": results.get(provider, "unknown"),
        "message": f"API key for {provider} configured successfully",
    })
    return True


def handle_api_keys_delete(handler, path: str) -> bool:
    """DELETE /api/keys/{provider} — Remove API key for a provider."""
    if not path.startswith("/api/keys/"):
        return False

    provider = path.split("/api/keys/")[1].strip().lower()
    valid_providers = {p["id"] for p in API_PROVIDERS}
    if provider not in valid_providers:
        handler._respond(400, {"error": f"Unknown provider: {provider}"})
        return True

    # Remove from credential store
    try:
        cs = _get_credential_store()
        cs.delete("api_keys", provider, agent_id="user")
    except Exception:
        pass

    # Clear environment variable
    env_var = next((p["env_var"] for p in API_PROVIDERS if p["id"] == provider), None)
    if env_var:
        import os
        os.environ.pop(env_var, None)

    handler._respond(200, {"ok": True, "provider": provider, "message": f"API key for {provider} removed"})
    return True


def _mask_key(key: str) -> str:
    """Mask API key for display: show first 4 and last 4 chars."""
    if not key or len(key) < 12:
        return ""
    return key[:4] + "..." + key[-4:]
