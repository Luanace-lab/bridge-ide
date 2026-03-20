# Approval-Gate Analysis: CDP/Desktop Tool Access Control

Status: Analysis Complete | Author: Assi (Projektleiter) | Date: 2026-03-17

## Problem

CDP (Chrome DevTools Protocol) and Desktop tools (xdotool) give agents full browser/desktop access. Current policy is log-only (OPUS-004 audit logging added). No approval gate exists.

## Existing Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| Approval Requests | handlers/approvals.py | Active |
| Standing Approvals | standing_approvals.json | Active |
| RBAC Hierarchy | server.py:810+ (Level 0-3) | Active |
| Task System | task_queue, assigned_to | Active |
| PAAP Protocol | handlers/approvals.py | Active |

## Tools Requiring Approval Gate

### Tier 1: Critical (Browser Execute)
- `bridge_stealth_evaluate` — arbitrary JS in automation browser
- `bridge_cdp_evaluate` — arbitrary JS in the owner's browser
- `bridge_browser_eval` — arbitrary JS in unified session
- `bridge_cdp_navigate` — navigate the owner's browser

### Tier 2: High (Desktop Control)
- `bridge_desktop_click` — click on the owner's desktop
- `bridge_desktop_type` — type on the owner's desktop
- `bridge_desktop_key` — send keystrokes
- `bridge_desktop_drag` — drag operations

### Tier 3: Medium (Data Access)
- `bridge_credential_store` — read/write credentials (already gated by SEC-001)
- `bridge_stealth_start` — open automation browser
- `bridge_cdp_connect` — connect to the owner's browser

## Proposed 2-Tier Approval Model

### Tier 1: Human → Leader
the owner grants permission to leader agents (Level 1):
- Scoped by: tool category, time limit, task binding
- Mechanism: `POST /approval/standing` with `scope: "cdp"` or `scope: "desktop"`
- Revocation: `DELETE /approval/standing/{id}`

### Tier 2: Leader → Agent
Leader delegates to sub-agents (Level 2+):
- ALWAYS task-bound — agent can only use tool for assigned task
- Mechanism: `bridge_approval_request` + `bridge_approval_check`
- Auto-revoke: when task completes (`bridge_task_done`)

## Implementation Points

### 1. Tool Guard Function
```python
async def _require_tool_approval(tool_name: str, agent_id: str) -> bool:
    """Check if agent has active approval for tool."""
    # Check standing approval
    if _check_standing_approval(agent_id, tool_name):
        return True
    # Check task-bound approval
    active_task = _get_agent_active_task(agent_id)
    if active_task and _check_task_approval(agent_id, tool_name, active_task):
        return True
    return False
```

### 2. Where to Insert
Each Tier 1/2 tool in bridge_mcp.py adds at the start:
```python
if not await _require_tool_approval("cdp_evaluate", _agent_id):
    return json.dumps({"error": "Approval required for cdp_evaluate"})
```

### 3. Standing Approval Extension
Extend standing_approvals.json format:
```json
{
    "id": "sa_001",
    "agent_id": "assi",
    "scope": "cdp",
    "tools": ["bridge_cdp_evaluate", "bridge_cdp_navigate"],
    "granted_by": "user",
    "task_id": null,
    "expires_at": "2026-03-18T00:00:00Z"
}
```

### 4. Task-Bound Auto-Revoke
In `bridge_task_done`: Clear all task-bound approvals for the completing agent.

### 5. Audit Trail
Each approval check logs: `[APPROVAL] agent=X tool=Y task=Z result=granted/denied`

## UI Integration

1. Control Center → "Approvals" section (already exists)
2. WebSocket push for approval requests
3. Quick-approve buttons for Leader agents

## Effort Estimate

- Guard function + tool integration: 2-3 days
- Standing approval extension: 1 day
- Task-bound auto-revoke: 0.5 days
- UI refinements: 1 day
- Tests: 1 day
- Total: ~5-6 days

## Decision

Recommended for post-release implementation. The approval infrastructure exists — this is an extension, not a new system.
