"""
tool_bridge.py — MCP-to-API Tool Format Conversion

Converts MCP tool definitions to provider-specific formats:
  - Anthropic: input_schema, tool_use_id, tool_result
  - OpenAI: parameters wrapped in function, call_id, function_call_output
  - Gemini: function declarations, function_call, function_response

Architecture Reference: R5_Integration_Roadmap.md C6
Phase: C — Intelligence

Design:
  - Bidirectional conversion (MCP <-> provider)
  - Zero-dependency (pure Python, no SDK imports)
  - Validates schemas during conversion
  - Handles missing/optional fields gracefully
"""

from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# MCP → Anthropic
# ---------------------------------------------------------------------------

def mcp_to_anthropic(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic Messages API format.

    MCP format:
        {"name": "...", "description": "...", "inputSchema": {...}}

    Anthropic format:
        {"name": "...", "description": "...", "input_schema": {...}}

    Args:
        mcp_tools: List of MCP tool definitions.

    Returns:
        List of Anthropic tool definitions.
    """
    result: list[dict[str, Any]] = []
    for tool in mcp_tools:
        converted = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": _extract_schema(tool),
        }
        result.append(converted)
    return result


def anthropic_tool_call_to_mcp(
    tool_use_id: str,
    name: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """Convert Anthropic tool_use block to MCP tool call format.

    Args:
        tool_use_id: Anthropic tool use ID.
        name: Tool name.
        input_data: Tool input arguments.

    Returns:
        MCP-style tool call dict.
    """
    return {
        "id": tool_use_id,
        "name": name,
        "arguments": input_data,
    }


def mcp_result_to_anthropic(
    tool_use_id: str,
    result: str,
    is_error: bool = False,
) -> dict[str, Any]:
    """Convert MCP tool result to Anthropic tool_result block.

    Args:
        tool_use_id: Matching tool use ID.
        result: Result content string.
        is_error: Whether this is an error result.

    Returns:
        Anthropic tool_result content block.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": result,
        "is_error": is_error,
    }


# ---------------------------------------------------------------------------
# MCP → OpenAI
# ---------------------------------------------------------------------------

def mcp_to_openai(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to OpenAI function calling format.

    MCP format:
        {"name": "...", "description": "...", "inputSchema": {...}}

    OpenAI format:
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

    Args:
        mcp_tools: List of MCP tool definitions.

    Returns:
        List of OpenAI tool definitions.
    """
    result: list[dict[str, Any]] = []
    for tool in mcp_tools:
        schema = _extract_schema(tool)
        # OpenAI uses "parameters" not "input_schema"
        converted = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": schema,
            },
        }
        result.append(converted)
    return result


def openai_tool_call_to_mcp(
    call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Convert OpenAI function_call to MCP tool call format.

    Args:
        call_id: OpenAI call ID.
        name: Function name.
        arguments: Function arguments.

    Returns:
        MCP-style tool call dict.
    """
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
    }


def mcp_result_to_openai(
    call_id: str,
    result: str,
) -> dict[str, Any]:
    """Convert MCP tool result to OpenAI function_call_output format.

    Args:
        call_id: Matching call ID.
        result: Result content string.

    Returns:
        OpenAI function call output.
    """
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": result,
    }


# ---------------------------------------------------------------------------
# MCP → Gemini
# ---------------------------------------------------------------------------

def mcp_to_gemini(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Gemini function declaration format.

    MCP format:
        {"name": "...", "description": "...", "inputSchema": {...}}

    Gemini format:
        {"name": "...", "description": "...", "parameters": {...}}
        (wrapped in function_declarations for the API call)

    Args:
        mcp_tools: List of MCP tool definitions.

    Returns:
        List of Gemini function declarations.
    """
    result: list[dict[str, Any]] = []
    for tool in mcp_tools:
        schema = _extract_schema(tool)
        # Gemini strips $schema and additionalProperties
        cleaned = _clean_schema_for_gemini(schema)
        converted = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": cleaned,
        }
        result.append(converted)
    return result


def gemini_tool_call_to_mcp(
    name: str,
    args: dict[str, Any],
    call_id: str = "",
) -> dict[str, Any]:
    """Convert Gemini function_call to MCP tool call format.

    Gemini doesn't use explicit call IDs — we generate one if not provided.

    Args:
        name: Function name.
        args: Function arguments.
        call_id: Optional call ID (generated if empty).

    Returns:
        MCP-style tool call dict.
    """
    return {
        "id": call_id or f"gemini_{name}",
        "name": name,
        "arguments": args,
    }


def mcp_result_to_gemini(
    name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Convert MCP tool result to Gemini function_response format.

    Args:
        name: Function name.
        result: Result as dict.

    Returns:
        Gemini function response.
    """
    return {
        "name": name,
        "response": result,
    }


# ---------------------------------------------------------------------------
# Schema Extraction & Cleaning
# ---------------------------------------------------------------------------

def _extract_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Extract the JSON Schema from an MCP tool definition.

    Checks for 'inputSchema' (MCP standard) and 'input_schema' (common variant).

    Args:
        tool: MCP tool definition.

    Returns:
        JSON Schema dict, defaults to empty object schema.
    """
    schema = tool.get("inputSchema") or tool.get("input_schema")
    if schema:
        return copy.deepcopy(schema)
    return {"type": "object", "properties": {}}


def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Clean a JSON Schema for Gemini compatibility.

    Gemini doesn't support:
    - $schema key
    - additionalProperties
    - Certain nested constructs

    Args:
        schema: JSON Schema dict.

    Returns:
        Cleaned schema suitable for Gemini.
    """
    cleaned = copy.deepcopy(schema)
    cleaned.pop("$schema", None)
    cleaned.pop("additionalProperties", None)
    # Recursively clean nested properties
    if "properties" in cleaned:
        for prop_name, prop_schema in cleaned["properties"].items():
            if isinstance(prop_schema, dict):
                cleaned["properties"][prop_name] = _clean_schema_for_gemini(
                    prop_schema
                )
    return cleaned


# ---------------------------------------------------------------------------
# Batch Conversion
# ---------------------------------------------------------------------------

def convert_tools(
    mcp_tools: list[dict[str, Any]],
    target: str,
) -> list[dict[str, Any]]:
    """Convert MCP tools to a target provider format.

    Args:
        mcp_tools: List of MCP tool definitions.
        target: Target format — "anthropic", "openai", or "gemini".

    Returns:
        Converted tool definitions.

    Raises:
        ValueError: If target is not recognized.
    """
    converters = {
        "anthropic": mcp_to_anthropic,
        "openai": mcp_to_openai,
        "gemini": mcp_to_gemini,
    }
    if target not in converters:
        available = ", ".join(sorted(converters.keys()))
        raise ValueError(f"Unknown target '{target}'. Available: {available}")
    return converters[target](mcp_tools)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_mcp_tool(tool: dict[str, Any]) -> list[str]:
    """Validate an MCP tool definition.

    Args:
        tool: Tool definition to validate.

    Returns:
        List of validation errors (empty if valid).
    """
    errors: list[str] = []

    if "name" not in tool:
        errors.append("Missing required field: name")
    elif not isinstance(tool["name"], str) or not tool["name"].strip():
        errors.append("Field 'name' must be a non-empty string")

    if "description" not in tool:
        errors.append("Missing recommended field: description")

    schema = tool.get("inputSchema") or tool.get("input_schema")
    if schema is not None:
        if not isinstance(schema, dict):
            errors.append("Schema must be a dict")
        elif schema.get("type") != "object":
            errors.append("Schema type should be 'object'")

    return errors


def validate_mcp_tools(tools: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Validate a list of MCP tool definitions.

    Args:
        tools: List of tool definitions.

    Returns:
        Dict mapping tool name/index to errors. Empty if all valid.
    """
    all_errors: dict[str, list[str]] = {}
    for i, tool in enumerate(tools):
        name = tool.get("name", f"tool[{i}]")
        errors = validate_mcp_tool(tool)
        if errors:
            all_errors[name] = errors
    return all_errors
