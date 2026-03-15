from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_CLI_IDENTITY_FIELDS = (
    ("BRIDGE_RESUME_ID", "resume_id"),
    ("BRIDGE_CLI_WORKSPACE", "workspace"),
    ("BRIDGE_CLI_PROJECT_ROOT", "project_root"),
    ("BRIDGE_CLI_INSTRUCTION_PATH", "instruction_path"),
)


def _env_value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key, "")).strip()


def cli_identity_payload_from_env(
    environ: Mapping[str, str],
    *,
    transport_source: str = "",
) -> dict[str, str]:
    """Mirror CLI identity metadata from env into Bridge transport payloads."""
    payload: dict[str, str] = {}
    for env_name, field_name in _CLI_IDENTITY_FIELDS:
        value = _env_value(environ, env_name)
        if value:
            payload[field_name] = value
    source = _env_value(environ, "BRIDGE_CLI_IDENTITY_SOURCE") or transport_source
    if payload and source:
        payload["identity_source"] = source
        payload["cli_identity_source"] = source
    return payload


def self_reflection_agent_configs(
    environ: Mapping[str, str],
    *,
    agent_id: str | None,
    registered_role: str = "",
) -> dict[str, dict[str, Any]]:
    """Build explicit runtime agent config for SelfReflection from CLI env."""
    if not agent_id:
        return {}

    workspace = _env_value(environ, "BRIDGE_CLI_WORKSPACE")
    project_root = _env_value(environ, "BRIDGE_CLI_PROJECT_ROOT")
    home_dir = (
        _env_value(environ, "BRIDGE_CLI_HOME_DIR")
        or workspace
        or project_root
    )
    if not home_dir:
        return {}

    payload: dict[str, Any] = {
        "id": agent_id,
        "role": registered_role or "",
        "home_dir": home_dir,
    }
    resume_id = _env_value(environ, "BRIDGE_RESUME_ID")
    instruction_path = _env_value(environ, "BRIDGE_CLI_INSTRUCTION_PATH")
    identity_source = _env_value(environ, "BRIDGE_CLI_IDENTITY_SOURCE")
    config_dir = _env_value(environ, "BRIDGE_CLI_CONFIG_DIR") or _env_value(
        environ, "CLAUDE_CONFIG_DIR"
    )
    if workspace:
        payload["workspace"] = workspace
    if project_root:
        payload["project_root"] = project_root
    if resume_id:
        payload["resume_id"] = resume_id
    if instruction_path:
        payload["instruction_path"] = instruction_path
    if identity_source:
        payload["identity_source"] = identity_source
    if config_dir:
        payload["config_dir"] = config_dir
    return {agent_id: payload}


def heartbeat_payload(
    environ: Mapping[str, str],
    *,
    agent_id: str | None,
    transport_source: str = "cli_heartbeat",
) -> dict[str, Any]:
    """Build heartbeat payload with mirrored CLI identity fields."""
    payload: dict[str, Any] = {"agent_id": agent_id}
    payload.update(
        cli_identity_payload_from_env(
            environ,
            transport_source=transport_source,
        )
    )
    return payload
