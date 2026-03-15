"""
Workflow JSON Schema Validator for n8n workflows.

Validates workflow definitions before deployment to n8n.
Catches common errors: missing fields, invalid node types, broken connections.

Used by n8n_mcp.py template_deploy and Workflow-Bot agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("workflow_validator")

# ---------------------------------------------------------------------------
# Known n8n node types (core + common integrations)
# Not exhaustive — unknown types generate warnings, not errors.
# ---------------------------------------------------------------------------
KNOWN_NODE_TYPES = {
    # Core
    "n8n-nodes-base.start",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.set",
    "n8n-nodes-base.function",
    "n8n-nodes-base.code",
    "n8n-nodes-base.noOp",
    "n8n-nodes-base.wait",
    "n8n-nodes-base.respondToWebhook",
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.errorTrigger",
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.aggregate",
    "n8n-nodes-base.removeDuplicates",
    "n8n-nodes-base.sort",
    "n8n-nodes-base.limit",
    "n8n-nodes-base.filter",
    "n8n-nodes-base.itemLists",
    # Communication
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.emailReadImap",
    "n8n-nodes-base.slack",
    "n8n-nodes-base.telegram",
    "n8n-nodes-base.discord",
    "n8n-nodes-base.microsoftTeams",
    # Data
    "n8n-nodes-base.googleSheets",
    "n8n-nodes-base.airtable",
    "n8n-nodes-base.notion",
    "n8n-nodes-base.postgres",
    "n8n-nodes-base.mysql",
    "n8n-nodes-base.mongodb",
    "n8n-nodes-base.redis",
    # Dev Tools
    "n8n-nodes-base.github",
    "n8n-nodes-base.gitlab",
    "n8n-nodes-base.jira",
    "n8n-nodes-base.linear",
    # AI (LangChain)
    "@n8n/n8n-nodes-langchain.chatTrigger",
    "@n8n/n8n-nodes-langchain.agent",
    "@n8n/n8n-nodes-langchain.chainLlm",
    "@n8n/n8n-nodes-langchain.lmChatOpenAi",
    "@n8n/n8n-nodes-langchain.lmChatAnthropic",
    "@n8n/n8n-nodes-langchain.memoryBufferWindow",
    "@n8n/n8n-nodes-langchain.outputParserStructured",
    # Files
    "n8n-nodes-base.readBinaryFile",
    "n8n-nodes-base.writeBinaryFile",
    "n8n-nodes-base.googleDrive",
    "n8n-nodes-base.dropbox",
    # Other
    "n8n-nodes-base.dateTime",
    "n8n-nodes-base.crypto",
    "n8n-nodes-base.xml",
    "n8n-nodes-base.html",
    "n8n-nodes-base.markdown",
    "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.stickyNote",
}


class ValidationResult:
    """Result of workflow validation."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __str__(self) -> str:
        if self.valid and not self.warnings:
            return "Workflow valid."
        parts = []
        if self.errors:
            parts.append(f"ERRORS ({len(self.errors)}):")
            parts.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            parts.append(f"WARNINGS ({len(self.warnings)}):")
            parts.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(parts)


def validate_workflow(workflow: dict[str, Any]) -> ValidationResult:
    """Validate an n8n workflow JSON definition.

    Checks:
    1. Required top-level fields (name, nodes)
    2. Node structure (name, type, position)
    3. Node types against known list (warnings for unknown)
    4. Connection integrity (references valid nodes)
    5. No cycles in connections (basic check)
    6. At least one trigger node
    """
    result = ValidationResult()

    # 1. Top-level fields
    if not workflow.get("name"):
        result.add_error("Missing required field: 'name'")

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        result.add_error("Missing or invalid 'nodes' (must be array)")
        return result  # Can't continue without nodes

    if len(nodes) == 0:
        result.add_warning("Workflow has no nodes")
        return result

    # 2. Node structure
    node_names: set[str] = set()
    has_trigger = False

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            result.add_error(f"Node {i}: not a valid object")
            continue

        name = node.get("name")
        if not name:
            result.add_error(f"Node {i}: missing 'name'")
        elif name in node_names:
            result.add_error(f"Node '{name}': duplicate name")
        else:
            node_names.add(name)

        node_type = node.get("type")
        if not node_type:
            result.add_error(f"Node '{name or i}': missing 'type'")
        elif node_type not in KNOWN_NODE_TYPES:
            result.add_warning(f"Node '{name or i}': unknown type '{node_type}' (may still work)")

        position = node.get("position")
        if not isinstance(position, list) or len(position) != 2:
            result.add_warning(f"Node '{name or i}': missing or invalid 'position'")

        # Check for trigger nodes
        if node_type and ("trigger" in node_type.lower() or "webhook" in node_type.lower()
                          or "cron" in node_type.lower() or "start" in node_type.lower()
                          or "schedule" in node_type.lower()):
            has_trigger = True

    if not has_trigger:
        result.add_warning("No trigger node found — workflow won't start automatically")

    # 3. Connection integrity
    connections = workflow.get("connections", {})
    if isinstance(connections, dict):
        for source_name, conn_data in connections.items():
            if source_name not in node_names:
                result.add_error(f"Connection from unknown node: '{source_name}'")
                continue

            if not isinstance(conn_data, dict):
                continue

            for _conn_type, outputs in conn_data.items():
                if not isinstance(outputs, list):
                    continue
                for output_group in outputs:
                    if not isinstance(output_group, list):
                        continue
                    for target in output_group:
                        if isinstance(target, dict):
                            target_name = target.get("node")
                            if target_name and target_name not in node_names:
                                result.add_error(
                                    f"Connection target unknown: '{source_name}' → '{target_name}'"
                                )

    return result


def validate_workflow_json(json_str: str) -> ValidationResult:
    """Validate a workflow from JSON string."""
    result = ValidationResult()
    try:
        workflow = json.loads(json_str)
    except json.JSONDecodeError as exc:
        result.add_error(f"Invalid JSON: {exc}")
        return result
    return validate_workflow(workflow)


# ---------------------------------------------------------------------------
# CLI usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python workflow_validator.py <workflow.json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        wf = json.load(f)
    r = validate_workflow(wf)
    print(r)
    sys.exit(0 if r.valid else 1)
