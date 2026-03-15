#!/usr/bin/env python3
"""n8n MCP Server — Wraps n8n REST API as MCP tools (stdio transport).

Provides 5 tools for agent access to n8n workflows:
  - n8n_workflow_list: List all workflows
  - n8n_workflow_trigger: Execute a workflow
  - n8n_workflow_create: Create a new workflow
  - n8n_workflow_status: Get workflow details + execution history
  - n8n_credentials_list: List configured credentials

Configuration:
  N8N_BASE_URL  — n8n instance URL (default: http://localhost:5678)
  N8N_API_KEY   — API key for authenticated access (default: empty for local)
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config — load from env or /home/user/.config/bridge/n8n.env
# ---------------------------------------------------------------------------
_N8N_ENV_FILE = os.path.expanduser("~/.config/bridge/n8n.env")

def _load_env_file(path: str) -> dict[str, str]:
    """Load KEY=VALUE pairs from an env file."""
    result: dict[str, str] = {}
    if not os.path.isfile(path):
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result

_env = _load_env_file(_N8N_ENV_FILE)
N8N_BASE_URL = os.environ.get("N8N_BASE_URL", _env.get("N8N_BASE_URL", "http://localhost:5678")).rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", _env.get("N8N_API_KEY", ""))
REQUEST_TIMEOUT = 30.0

log = logging.getLogger("n8n_mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [n8n_mcp] %(message)s")

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if N8N_API_KEY:
        h["X-N8N-API-KEY"] = N8N_API_KEY
    return h


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{N8N_BASE_URL}/api/v1{path}"
    resp = httpx.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict[str, Any] | None = None) -> Any:
    url = f"{N8N_BASE_URL}/api/v1{path}"
    resp = httpx.post(url, headers=_headers(), json=body or {}, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        log.error("POST %s → %d: %s", path, resp.status_code, resp.text[:500])
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("n8n")


@mcp.tool(
    name="n8n_workflow_list",
    description=(
        "List all n8n workflows. Returns id, name, active status, "
        "createdAt, updatedAt for each workflow. Optional limit/cursor."
    ),
)
def n8n_workflow_list(limit: int = 50, cursor: str = "") -> str:
    """List workflows from n8n."""
    try:
        params: dict[str, Any] = {"limit": min(limit, 250)}
        if cursor:
            params["cursor"] = cursor
        data = _get("/workflows", params=params)
        workflows = data.get("data", [])
        result = []
        for wf in workflows:
            result.append({
                "id": wf.get("id"),
                "name": wf.get("name"),
                "active": wf.get("active"),
                "createdAt": wf.get("createdAt"),
                "updatedAt": wf.get("updatedAt"),
                "tags": [t.get("name", "") for t in wf.get("tags", [])],
            })
        return json.dumps({
            "count": len(result),
            "workflows": result,
            "nextCursor": data.get("nextCursor"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="n8n_workflow_trigger",
    description=(
        "Execute/trigger an n8n workflow by ID. "
        "Pass optional input_data as JSON object to provide data to the workflow. "
        "Returns execution result."
    ),
)
def n8n_workflow_trigger(workflow_id: str, input_data: dict[str, Any] | None = None) -> str:
    """Trigger a workflow execution."""
    try:
        exec_body: dict[str, Any] = {
            "workflowId": workflow_id,
        }
        if input_data:
            exec_body["data"] = input_data

        data = _post(f"/workflows/{workflow_id}/run", exec_body)
        return json.dumps({"ok": True, "execution": data})
    except httpx.HTTPStatusError as exc:
        # If /run endpoint not available, try activate + webhook
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="n8n_workflow_create",
    description=(
        "Create a new n8n workflow. Provide name and optionally nodes/connections. "
        "For simple workflows, just provide name and the system creates an empty workflow. "
        "Returns the created workflow ID."
    ),
)
def n8n_workflow_create(
    name: str,
    nodes: list[dict[str, Any]] | None = None,
    connections: dict[str, Any] | None = None,
) -> str:
    """Create a new workflow in n8n."""
    try:
        if not name or not name.strip():
            return json.dumps({"error": "name is required"})

        # Validate workflow before creating
        if nodes:
            try:
                from workflow_validator import validate_workflow
                vr = validate_workflow({"name": name, "nodes": nodes, "connections": connections or {}})
                if not vr.valid:
                    return json.dumps({"error": "Validation failed", "details": vr.errors, "warnings": vr.warnings})
                if vr.warnings:
                    log.info("Workflow '%s' has warnings: %s", name, vr.warnings)
            except ImportError:
                pass  # validator not available, skip

        body: dict[str, Any] = {
            "name": name.strip(),
            "nodes": nodes or [
                {
                    "parameters": {},
                    "name": "Manual Trigger",
                    "type": "n8n-nodes-base.manualTrigger",
                    "typeVersion": 1,
                    "position": [250, 300],
                }
            ],
            "connections": connections or {},
            "settings": {
                "executionOrder": "v1",
            },
        }

        data = _post("/workflows", body)
        return json.dumps({
            "ok": True,
            "workflow": {
                "id": data.get("id"),
                "name": data.get("name"),
                "active": data.get("active"),
                "createdAt": data.get("createdAt"),
            },
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="n8n_workflow_status",
    description=(
        "Get detailed status of a workflow by ID. "
        "Returns workflow metadata and recent execution history."
    ),
)
def n8n_workflow_status(workflow_id: str, execution_limit: int = 5) -> str:
    """Get workflow details and recent executions."""
    try:
        # Get workflow details
        wf = _get(f"/workflows/{workflow_id}")

        # Get recent executions
        execs_data = _get("/executions", params={
            "workflowId": workflow_id,
            "limit": min(execution_limit, 20),
        })
        executions = []
        for ex in execs_data.get("data", []):
            executions.append({
                "id": ex.get("id"),
                "status": ex.get("status"),
                "startedAt": ex.get("startedAt"),
                "stoppedAt": ex.get("stoppedAt"),
                "mode": ex.get("mode"),
            })

        return json.dumps({
            "workflow": {
                "id": wf.get("id"),
                "name": wf.get("name"),
                "active": wf.get("active"),
                "createdAt": wf.get("createdAt"),
                "updatedAt": wf.get("updatedAt"),
                "nodeCount": len(wf.get("nodes", [])),
                "tags": [t.get("name", "") for t in wf.get("tags", [])],
            },
            "executions": executions,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="n8n_credentials_list",
    description=(
        "List all configured credentials in n8n. "
        "Returns credential name, type, createdAt. "
        "Does NOT expose secret values."
    ),
)
def n8n_credentials_list(limit: int = 50) -> str:
    """List credentials (names/types only, no secrets)."""
    try:
        data = _get("/credentials", params={"limit": min(limit, 250)})
        creds = []
        for c in data.get("data", []):
            creds.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "type": c.get("type"),
                "createdAt": c.get("createdAt"),
                "updatedAt": c.get("updatedAt"),
            })
        return json.dumps({"count": len(creds), "credentials": creds})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Template deployment
# ---------------------------------------------------------------------------
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow_templates")

def _load_template(template_id: str) -> dict[str, Any] | None:
    """Load a workflow template by ID from the templates directory."""
    if not os.path.isdir(TEMPLATES_DIR):
        return None
    for fname in os.listdir(TEMPLATES_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(TEMPLATES_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                tpl = json.load(f)
            if tpl.get("template_id") == template_id:
                return tpl
        except Exception:
            continue
    return None


def _substitute_variables(obj: Any, variables: dict[str, str]) -> Any:
    """Recursively substitute {{key}} placeholders in template."""
    if isinstance(obj, str):
        for key, value in variables.items():
            obj = obj.replace("{{" + key + "}}", str(value))
        return obj
    if isinstance(obj, dict):
        return {k: _substitute_variables(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_variables(item, variables) for item in obj]
    return obj


@mcp.tool(
    name="n8n_template_list",
    description=(
        "List available workflow templates. "
        "Templates are pre-built workflows for common tasks "
        "(email notifications, status reports, monitoring). "
        "Returns template_id, name, description, difficulty, variables."
    ),
)
def n8n_template_list() -> str:
    """List all available workflow templates."""
    try:
        if not os.path.isdir(TEMPLATES_DIR):
            return json.dumps({"templates": [], "count": 0})
        templates = []
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(TEMPLATES_DIR, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    tpl = json.load(f)
                templates.append({
                    "template_id": tpl.get("template_id"),
                    "name": tpl.get("name"),
                    "description": tpl.get("description"),
                    "category": tpl.get("category"),
                    "difficulty": tpl.get("difficulty"),
                    "variables": tpl.get("variables", []),
                })
            except Exception:
                continue
        return json.dumps({"templates": templates, "count": len(templates)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    name="n8n_template_deploy",
    description=(
        "Deploy a workflow template to n8n. "
        "Provide the template_id and variable values. "
        "Creates the workflow in n8n and optionally subscribes to Bridge events. "
        "Example: n8n_template_deploy('tpl_task_email', {'email_to': 'susi@example.com'})"
    ),
)
def n8n_template_deploy(template_id: str, variables: dict[str, str] | None = None) -> str:
    """Deploy a workflow template to n8n with variable substitution."""
    try:
        tpl = _load_template(template_id)
        if not tpl:
            return json.dumps({"error": f"Template '{template_id}' not found"})

        vars_dict = variables or {}

        # Check required variables
        for var_def in tpl.get("variables", []):
            key = var_def["key"]
            if var_def.get("required") and key not in vars_dict:
                if "default" in var_def:
                    vars_dict[key] = str(var_def["default"])
                else:
                    return json.dumps({"error": f"Required variable '{key}' missing"})
            elif key not in vars_dict and "default" in var_def:
                vars_dict[key] = str(var_def["default"])

        # Substitute variables in workflow definition
        workflow_def = _substitute_variables(tpl["n8n_workflow"], vars_dict)

        # Create workflow in n8n (active is read-only on creation in v2.10+)
        should_activate = workflow_def.get("active", False)
        body = {
            "name": workflow_def.get("name", tpl["name"]),
            "nodes": workflow_def.get("nodes", []),
            "connections": workflow_def.get("connections", {}),
            "settings": workflow_def.get("settings", {"executionOrder": "v1"}),
        }
        data = _post("/workflows", body)

        # Activate if requested (separate API call)
        wf_id = data.get("id")
        if should_activate and wf_id:
            try:
                _post(f"/workflows/{wf_id}/activate", {})
                data["active"] = True
            except Exception as exc:
                log.warning("Could not activate workflow %s: %s", wf_id, exc)

        result: dict[str, Any] = {
            "ok": True,
            "template_id": template_id,
            "workflow": {
                "id": data.get("id"),
                "name": data.get("name"),
                "active": data.get("active"),
            },
            "variables_used": vars_dict,
        }

        # Register Bridge event subscription if template defines one
        bridge_sub = tpl.get("bridge_subscription")
        if bridge_sub and bridge_sub.get("event_type"):
            # Find the webhook URL from the created workflow
            webhook_path = None
            for node in workflow_def.get("nodes", []):
                if node.get("type", "").endswith(".webhook"):
                    webhook_path = node.get("parameters", {}).get("path")
                    break
            if webhook_path:
                result["bridge_subscription"] = {
                    "event_type": bridge_sub["event_type"],
                    "webhook_url": f"{N8N_BASE_URL}/webhook/{webhook_path}",
                    "note": "Register this subscription via POST /events/subscribe on Bridge server",
                }

        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("n8n MCP Server starting (base_url=%s, auth=%s)", N8N_BASE_URL, "key" if N8N_API_KEY else "none")
    mcp.run(transport="stdio")
