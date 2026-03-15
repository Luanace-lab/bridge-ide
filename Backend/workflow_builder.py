"""
Bridge workflow compiler.

Canonical source of truth for Bridge-managed workflows:
- UI edits a Bridge workflow spec
- Backend compiles that spec into n8n nodes/connections
- n8n remains the execution engine, not the user-facing model
"""

from __future__ import annotations

import re
from typing import Any

import workflow_validator

DEFAULT_BRIDGE_URL = "http://localhost:9111"
_LOCAL_BRIDGE_URLS = {
    "http://localhost:9111",
    "http://127.0.0.1:9111",
}

BRIDGE_CAPABILITIES: list[dict[str, Any]] = [
    {
        "kind": "bridge.trigger.schedule",
        "label": "Zeitplan",
        "category": "trigger",
        "description": "Startet den Workflow nach Cron-Zeitplan.",
        "config_schema": {"cron": "string"},
    },
    {
        "kind": "bridge.trigger.event",
        "label": "Bridge-Event",
        "category": "trigger",
        "description": "Reagiert auf Bridge-Events wie task.created oder agent.offline.",
        "config_schema": {"event_type": "string", "filter": "object?"},
    },
    {
        "kind": "bridge.action.send_message",
        "label": "Bridge-Nachricht",
        "category": "action",
        "description": "Sendet eine Nachricht in die Bridge.",
        "config_schema": {"to": "string", "content": "string"},
    },
    {
        "kind": "bridge.action.create_task",
        "label": "Bridge-Task",
        "category": "action",
        "description": "Erstellt einen strukturierten Bridge-Task.",
        "config_schema": {
            "title": "string",
            "description": "string?",
            "task_type": "string?",
            "priority": "int?",
            "team": "string?",
            "assigned_to": "string?",
        },
    },
    {
        "kind": "n8n.raw",
        "label": "Beliebiger n8n-Node",
        "category": "advanced",
        "description": "Volle n8n-Power via UI. Node-Typ und Parameter werden direkt angegeben.",
        "config_schema": {"node_type": "string", "parameters": "object?"},
    },
]


def list_capabilities() -> dict[str, Any]:
    """Return the canonical capability registry for UI consumers."""
    raw_types = sorted(workflow_validator.KNOWN_NODE_TYPES)
    return {
        "bridge_capabilities": BRIDGE_CAPABILITIES,
        "raw_node_types": raw_types,
        "count": len(BRIDGE_CAPABILITIES) + len(raw_types),
    }


def compile_bridge_workflow(spec: dict[str, Any]) -> dict[str, Any]:
    """Compile a Bridge workflow spec into an n8n workflow payload."""
    if not isinstance(spec, dict):
        raise ValueError("workflow spec must be an object")

    name = str(spec.get("name", "")).strip()
    nodes_spec = spec.get("nodes", [])
    edges_spec = spec.get("edges", [])
    settings = spec.get("settings", {"executionOrder": "v1"})

    if not name:
        raise ValueError("workflow name is required")
    if not isinstance(nodes_spec, list) or not nodes_spec:
        raise ValueError("workflow must contain at least one node")
    if not isinstance(edges_spec, list):
        raise ValueError("workflow edges must be a list")

    compiled_nodes: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    name_by_id: dict[str, str] = {}
    bridge_subscription: dict[str, Any] | None = None

    for idx, node_spec in enumerate(nodes_spec):
        compiled, node_meta = _compile_node(node_spec, idx)
        node_id = node_meta["id"]
        if node_id in nodes_by_id:
            raise ValueError(f"duplicate node id: {node_id}")
        if compiled["name"] in name_by_id.values():
            raise ValueError(f"duplicate node name: {compiled['name']}")
        compiled_nodes.append(compiled)
        nodes_by_id[node_id] = compiled
        name_by_id[node_id] = compiled["name"]
        if node_meta.get("bridge_subscription"):
            if bridge_subscription is not None:
                raise ValueError("only one bridge.trigger.event node is supported per workflow")
            bridge_subscription = node_meta["bridge_subscription"]

    connections = _build_connections(edges_spec, name_by_id)
    workflow = {
        "name": name,
        "nodes": compiled_nodes,
        "connections": connections,
        "settings": settings if isinstance(settings, dict) else {"executionOrder": "v1"},
    }

    validation = workflow_validator.validate_workflow(workflow)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    return {
        "workflow": workflow,
        "nodes_by_id": nodes_by_id,
        "node_names_by_id": name_by_id,
        "bridge_subscription": bridge_subscription,
        "validation": validation.to_dict(),
    }


def _default_bridge_sender(bridge_url: str, configured_sender: Any) -> str:
    sender = str(configured_sender or "").strip()
    if sender:
        return sender
    normalized = bridge_url.rstrip("/")
    if normalized in _LOCAL_BRIDGE_URLS:
        return "system"
    return "workflow"


def _compile_node(node_spec: dict[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(node_spec, dict):
        raise ValueError(f"node {index} must be an object")

    node_id = str(node_spec.get("id", "")).strip()
    kind = str(node_spec.get("kind", "")).strip()
    node_name = str(node_spec.get("name", "")).strip()
    config = node_spec.get("config", {})
    if not node_id:
        raise ValueError(f"node {index} missing id")
    if not kind:
        raise ValueError(f"node '{node_id}' missing kind")
    if not isinstance(config, dict):
        raise ValueError(f"node '{node_id}' config must be an object")

    position = node_spec.get("position")
    if not (isinstance(position, list) and len(position) == 2):
        position = [250 + (index % 4) * 360, 220 + (index // 4) * 220]

    if kind == "bridge.trigger.schedule":
        cron = str(config.get("cron", "")).strip()
        if not cron:
            raise ValueError(f"node '{node_id}' requires config.cron")
        node = {
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}},
            "name": node_name or f"Schedule {node_id}",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": position,
        }
        return node, {"id": node_id}

    if kind == "bridge.trigger.event":
        event_type = str(config.get("event_type", "")).strip()
        if not event_type:
            raise ValueError(f"node '{node_id}' requires config.event_type")
        webhook_path = str(config.get("webhook_path", "")).strip() or _slug(f"bridge-{node_id}-{event_type}")
        node = {
            "parameters": {
                "httpMethod": "POST",
                "path": webhook_path,
                "responseMode": "onReceived",
                "responseCode": 200,
            },
            "name": node_name or f"Bridge Event {event_type}",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": position,
            "webhookId": webhook_path,
        }
        return node, {
            "id": node_id,
            "bridge_subscription": {
                "event_type": event_type,
                "filter": config.get("filter", {}) if isinstance(config.get("filter"), dict) else {},
                "webhook_path": webhook_path,
            },
        }

    if kind == "bridge.action.send_message":
        recipient = str(config.get("to", "")).strip()
        content = str(config.get("content", "")).strip()
        if not recipient or not content:
            raise ValueError(f"node '{node_id}' requires config.to and config.content")
        bridge_url = str(config.get("bridge_url", DEFAULT_BRIDGE_URL)).strip() or DEFAULT_BRIDGE_URL
        sender = _default_bridge_sender(bridge_url, config.get("from"))
        node = {
            "parameters": {
                "method": "POST",
                "url": f"{bridge_url}/send",
                "sendBody": True,
                "bodyParameters": {
                    "parameters": [
                        {"name": "from", "value": sender},
                        {"name": "to", "value": recipient},
                        {"name": "content", "value": content},
                    ]
                },
                "options": {},
            },
            "name": node_name or f"Send Message {node_id}",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": position,
        }
        return node, {"id": node_id}

    if kind == "bridge.action.create_task":
        title = str(config.get("title", "")).strip()
        if not title:
            raise ValueError(f"node '{node_id}' requires config.title")
        bridge_url = str(config.get("bridge_url", DEFAULT_BRIDGE_URL)).strip() or DEFAULT_BRIDGE_URL
        task_type = str(config.get("type", config.get("task_type", "general"))).strip() or "general"
        params = [
            {"name": "title", "value": title},
            {"name": "description", "value": str(config.get("description", "")).strip()},
            {"name": "type", "value": task_type},
            {"name": "priority", "value": str(int(config.get("priority", 1)))},
            {"name": "created_by", "value": str(config.get("created_by", "workflow")).strip() or "workflow"},
            {"name": "payload", "value": "{}"},
        ]
        team = str(config.get("team", "")).strip()
        if team:
            params.append({"name": "team", "value": team})
        assigned_to = str(config.get("assigned_to", "")).strip()
        if assigned_to:
            params.append({"name": "assigned_to", "value": assigned_to})
        node = {
            "parameters": {
                "method": "POST",
                "url": f"{bridge_url}/task/create",
                "sendBody": True,
                "bodyParameters": {"parameters": params},
                "options": {},
            },
            "name": node_name or f"Create Task {node_id}",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": position,
        }
        return node, {"id": node_id}

    if kind == "n8n.raw":
        node_type = str(node_spec.get("node_type") or config.get("node_type", "")).strip()
        if not node_type:
            raise ValueError(f"node '{node_id}' requires node_type")
        parameters = node_spec.get("parameters", config.get("parameters", {}))
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise ValueError(f"node '{node_id}' parameters must be an object")
        node = {
            "parameters": parameters,
            "name": node_name or f"Node {node_id}",
            "type": node_type,
            "typeVersion": float(node_spec.get("type_version", config.get("type_version", 1)) or 1),
            "position": position,
        }
        return node, {"id": node_id}

    raise ValueError(f"unsupported workflow node kind: {kind}")


def _build_connections(edges_spec: list[dict[str, Any]], name_by_id: dict[str, str]) -> dict[str, Any]:
    connections: dict[str, Any] = {}
    for edge in edges_spec:
        if not isinstance(edge, dict):
            raise ValueError("each edge must be an object")
        source_ref = edge.get("from")
        target_ref = edge.get("to")
        if not source_ref or not target_ref:
            raise ValueError("edge requires from and to")

        source_id, source_output = _parse_endpoint(source_ref)
        target_id, target_input = _parse_endpoint(target_ref)

        if source_id not in name_by_id:
            raise ValueError(f"edge references unknown source node: {source_id}")
        if target_id not in name_by_id:
            raise ValueError(f"edge references unknown target node: {target_id}")

        source_name = name_by_id[source_id]
        target_name = name_by_id[target_id]

        bucket = connections.setdefault(source_name, {"main": []})
        while len(bucket["main"]) <= source_output:
            bucket["main"].append([])
        bucket["main"][source_output].append({
            "node": target_name,
            "type": "main",
            "index": target_input,
        })
    return connections


def _parse_endpoint(value: Any) -> tuple[str, int]:
    if isinstance(value, dict):
        node_id = str(value.get("node", "")).strip()
        index = int(value.get("index", 0) or 0)
        if not node_id:
            raise ValueError("edge endpoint dict requires node")
        return node_id, index
    text = str(value).strip()
    if not text:
        raise ValueError("edge endpoint is empty")
    if ":" not in text:
        return text, 0
    node_id, _, raw_index = text.partition(":")
    node_id = node_id.strip()
    raw_index = raw_index.strip()
    if not node_id:
        raise ValueError("edge endpoint missing node id")
    try:
        return node_id, int(raw_index)
    except ValueError as exc:
        raise ValueError(f"edge endpoint index must be numeric: {text}") from exc


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "workflow"
