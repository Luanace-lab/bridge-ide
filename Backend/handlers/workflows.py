"""Workflow/n8n helper extraction from server.py (Slice 12).

This module owns:
- n8n config/request helpers
- workflow registry persistence/projection helpers
- workflow auth-header patching
- workflow deploy/update/subscription/tool registration helpers

Anti-circular-import strategy:
  Shared runtime values are injected via init().
  This module NEVER imports from server.
  Direct imports only from stable modules: event_bus.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit

import event_bus
import workflow_bot
import workflow_builder
import workflow_validator


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_N8N_ENV_FILE = os.path.expanduser("~/.config/bridge/n8n.env")
WORKFLOW_REGISTRY_FILE = os.path.join(_BASE_DIR, "workflow_registry.json")
WORKFLOW_TEMPLATES_DIR = os.path.join(_BASE_DIR, "workflow_templates")
WORKFLOW_REGISTRY: dict[str, dict[str, Any]] = {}
WORKFLOW_REGISTRY_LOCK = threading.Lock()
_WORKFLOW_TOOLS: dict[str, dict[str, Any]] = {}

_get_port: Callable[[], int] | None = None
_get_bridge_user_token: Callable[[], str] | None = None
_get_auth_tier2_post_paths: Callable[[], set[str]] | None = None
_get_auth_tier3_post_paths: Callable[[], set[str]] | None = None
_get_auth_tier3_patterns: Callable[[], list[re.Pattern[str]]] | None = None
_utc_now_iso: Callable[[], str] | None = None

_T = TypeVar("_T")


def init(
    *,
    get_port_fn: Callable[[], int],
    get_bridge_user_token_fn: Callable[[], str],
    get_auth_tier2_post_paths_fn: Callable[[], set[str]],
    get_auth_tier3_post_paths_fn: Callable[[], set[str]],
    get_auth_tier3_patterns_fn: Callable[[], list[re.Pattern[str]]],
    utc_now_iso_fn: Callable[[], str],
) -> None:
    """Bind runtime config getters before using workflow helpers."""
    global _get_port, _get_bridge_user_token
    global _get_auth_tier2_post_paths, _get_auth_tier3_post_paths
    global _get_auth_tier3_patterns, _utc_now_iso

    _get_port = get_port_fn
    _get_bridge_user_token = get_bridge_user_token_fn
    _get_auth_tier2_post_paths = get_auth_tier2_post_paths_fn
    _get_auth_tier3_post_paths = get_auth_tier3_post_paths_fn
    _get_auth_tier3_patterns = get_auth_tier3_patterns_fn
    _utc_now_iso = utc_now_iso_fn


def _require_callback(callback: _T | None, name: str) -> _T:
    if callback is None:
        raise RuntimeError(f"handlers.workflows.init() not called: {name} missing")
    return callback


def _port() -> int:
    return _require_callback(_get_port, "get_port_fn")()


def _bridge_user_token() -> str:
    return _require_callback(_get_bridge_user_token, "get_bridge_user_token_fn")()


def _auth_tier2_post_paths() -> set[str]:
    return _require_callback(_get_auth_tier2_post_paths, "get_auth_tier2_post_paths_fn")()


def _auth_tier3_post_paths() -> set[str]:
    return _require_callback(_get_auth_tier3_post_paths, "get_auth_tier3_post_paths_fn")()


def _auth_tier3_patterns() -> list[re.Pattern[str]]:
    return _require_callback(_get_auth_tier3_patterns, "get_auth_tier3_patterns_fn")()


def _utc_now() -> str:
    return _require_callback(_utc_now_iso, "utc_now_iso_fn")()


def _load_n8n_config() -> tuple[str, str]:
    """Load n8n base URL and API key from env file or environment."""
    env_vars: dict[str, str] = {}
    if os.path.isfile(_N8N_ENV_FILE):
        with open(_N8N_ENV_FILE, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    base_url = os.environ.get("N8N_BASE_URL", env_vars.get("N8N_BASE_URL", "http://localhost:5678")).rstrip("/")
    api_key = os.environ.get("N8N_API_KEY", env_vars.get("N8N_API_KEY", ""))
    return base_url, api_key


def _n8n_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Make HTTP request to n8n API. Returns (status_code, response_json_or_error)."""
    base_url, api_key = _load_n8n_config()
    if not api_key:
        return 503, {"error": "n8n API key not configured (set N8N_API_KEY or ~/.config/bridge/n8n.env)"}
    url = f"{base_url}/api/v1{path}"
    headers = {"Content-Type": "application/json", "X-N8N-API-KEY": api_key}
    try:
        import urllib.error
        import urllib.parse
        import urllib.request

        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            return resp.status, json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
            return exc.code, json.loads(err_body)
        except Exception:
            return exc.code, {"error": f"n8n HTTP {exc.code}"}
    except Exception as exc:
        return 502, {"error": f"n8n connection failed: {exc}"}


def _save_workflow_registry() -> None:
    data = {"workflows": list(WORKFLOW_REGISTRY.values())}
    raw = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    registry_dir = os.path.dirname(WORKFLOW_REGISTRY_FILE) or _BASE_DIR
    fd, tmp = tempfile.mkstemp(dir=registry_dir, prefix=".workflow_registry_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(tmp, WORKFLOW_REGISTRY_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_workflow_registry() -> None:
    WORKFLOW_REGISTRY.clear()
    if not os.path.isfile(WORKFLOW_REGISTRY_FILE):
        return
    try:
        with open(WORKFLOW_REGISTRY_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    for record in data.get("workflows", []):
        workflow_id = str(record.get("workflow_id", "")).strip()
        if workflow_id:
            WORKFLOW_REGISTRY[workflow_id] = record


def _register_workflow_tool(tool_info: dict[str, Any] | None) -> None:
    if not isinstance(tool_info, dict):
        return
    tool_name = str(tool_info.get("name", "")).strip()
    if not tool_name:
        return
    _WORKFLOW_TOOLS[tool_name] = {
        "name": tool_name,
        "workflow_name": tool_info.get("workflow_name", ""),
        "workflow_id": tool_info.get("workflow_id", ""),
        "webhook_url": tool_info.get("webhook_url", ""),
        "registered_at": tool_info.get("registered_at", _utc_now()),
    }


def _restore_workflow_tools_from_registry() -> None:
    _WORKFLOW_TOOLS.clear()
    with WORKFLOW_REGISTRY_LOCK:
        for record in WORKFLOW_REGISTRY.values():
            _register_workflow_tool(record.get("tool_registered"))


def _record_workflow_deployment(
    *,
    workflow_id: str,
    workflow_name: str,
    source: str,
    template_id: str = "",
    bridge_spec: dict[str, Any] | None = None,
    bridge_subscription: dict[str, Any] | None = None,
    tool_registered: dict[str, Any] | None = None,
    compiled_workflow: dict[str, Any] | None = None,
    variables_used: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "workflow_id": workflow_id,
        "name": workflow_name,
        "source": source,
        "template_id": template_id,
        "bridge_spec": bridge_spec,
        "bridge_subscription": bridge_subscription,
        "tool_registered": tool_registered,
        "compiled_workflow": compiled_workflow,
        "variables_used": variables_used or {},
        "updated_at": _utc_now(),
    }
    with WORKFLOW_REGISTRY_LOCK:
        WORKFLOW_REGISTRY[workflow_id] = record
        _save_workflow_registry()
    _register_workflow_tool(tool_registered)
    return record


def _workflow_projection(workflow_data: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(workflow_data.get("id", "")).strip()
    with WORKFLOW_REGISTRY_LOCK:
        record = dict(WORKFLOW_REGISTRY.get(workflow_id, {})) if workflow_id else {}
    source = record.get("source", "n8n")
    template_id = record.get("template_id", "")
    if source == "bridge_builder":
        type_label = "Bridge Builder"
    elif template_id:
        type_label = template_id
    else:
        type_label = workflow_data.get("type") or "n8n"
    return {
        "id": workflow_id,
        "name": workflow_data.get("name"),
        "active": workflow_data.get("active"),
        "createdAt": workflow_data.get("createdAt"),
        "updatedAt": workflow_data.get("updatedAt"),
        "tags": [t.get("name", "") for t in workflow_data.get("tags", [])],
        "source": source,
        "template_id": template_id,
        "type": type_label,
        "template": template_id,
        "bridge_managed": bool(record),
        "definition_available": bool(record.get("bridge_spec") or template_id),
        "tool_registered": bool(record.get("tool_registered")),
        "subscription_registered": bool(record.get("bridge_subscription")),
    }


def _workflow_record_for_id(workflow_id: str) -> dict[str, Any] | None:
    with WORKFLOW_REGISTRY_LOCK:
        record = WORKFLOW_REGISTRY.get(workflow_id)
        return dict(record) if record else None


def _remove_workflow_record(workflow_id: str) -> dict[str, Any] | None:
    with WORKFLOW_REGISTRY_LOCK:
        record = WORKFLOW_REGISTRY.pop(workflow_id, None)
        if record is not None:
            _save_workflow_registry()
    if not record:
        return None
    tool_info = record.get("tool_registered") or {}
    tool_name = str(tool_info.get("name", "")).strip()
    if tool_name:
        _WORKFLOW_TOOLS.pop(tool_name, None)
    return record


def _workflow_delete_cleanup(record: dict[str, Any] | None) -> dict[str, Any]:
    cleanup: dict[str, Any] = {}
    if not record:
        return cleanup
    sub_info = record.get("bridge_subscription") or {}
    sub_id = str(sub_info.get("subscription_id", "")).strip()
    if sub_id:
        if sub_info.get("deduplicated"):
            cleanup["event_subscription_shared"] = True
            cleanup["event_subscription_id"] = sub_id
        else:
            cleanup["event_subscription_deleted"] = event_bus.unsubscribe(sub_id)
            cleanup["event_subscription_id"] = sub_id
    tool_info = record.get("tool_registered") or {}
    tool_name = str(tool_info.get("name", "")).strip()
    if tool_name:
        cleanup["tool_removed"] = tool_name
    return cleanup


def _find_first_webhook_path(workflow_def: dict[str, Any]) -> str:
    for node in workflow_def.get("nodes", []):
        if node.get("type", "").endswith(".webhook"):
            return str(node.get("parameters", {}).get("path", "")).strip()
    return ""


def _workflow_tool_name(workflow_name: str, workflow_id: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", str(workflow_name).strip()).lower().strip("_")
    suffix = re.sub(r"[^a-zA-Z0-9]+", "", str(workflow_id))[:8].lower()
    if suffix:
        return f"{base or 'workflow'}__{suffix}"
    return base or "workflow"


def _normalize_workflow_template_variables(template_id: str, variables: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(variables)
    cron_time = str(normalized.get("cron_time", "")).strip()
    if cron_time:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", cron_time)
        if not match:
            raise ValueError(f"template '{template_id}' requires cron_time in HH:MM format")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError(f"template '{template_id}' requires cron_time in HH:MM format")
        normalized.setdefault("cron_hour", str(hour))
        normalized.setdefault("cron_minute", str(minute))
    return normalized


def _workflow_targets_local_bridge_auth(url: str, method: str) -> bool:
    raw_url = str(url or "").strip()
    raw_method = str(method or "GET").strip().upper() or "GET"
    if not raw_url or raw_method == "GET":
        return False
    try:
        parsed = urlsplit(raw_url)
    except Exception:
        return False
    base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if base not in {f"http://localhost:{_port()}", f"http://127.0.0.1:{_port()}"}:
        return False
    path = parsed.path.rstrip("/") or "/"
    if path in _auth_tier2_post_paths() or path in _auth_tier3_post_paths():
        return True
    if any(pattern.match(path) for pattern in _auth_tier3_patterns()):
        return True
    return False


def _inject_bridge_workflow_auth_headers(workflow_def: dict[str, Any]) -> dict[str, Any]:
    patched = copy.deepcopy(workflow_def)
    bridge_user_token = _bridge_user_token()
    if not bridge_user_token:
        return patched
    for node in patched.get("nodes", []):
        if node.get("type") != "n8n-nodes-base.httpRequest":
            continue
        parameters = node.setdefault("parameters", {})
        url = str(parameters.get("url", "")).strip()
        method = str(parameters.get("method", "GET")).strip().upper() or "GET"
        if not _workflow_targets_local_bridge_auth(url, method):
            continue
        parameters["sendHeaders"] = True
        parameters["specifyHeaders"] = "keypair"
        header_parameters = parameters.get("headerParameters")
        if not isinstance(header_parameters, dict):
            header_parameters = {}
        existing = header_parameters.get("parameters")
        headers = existing if isinstance(existing, list) else []
        found = False
        for header in headers:
            if isinstance(header, dict) and str(header.get("name", "")).strip().lower() == "x-bridge-token":
                header["value"] = bridge_user_token
                found = True
                break
        if not found:
            headers.append({"name": "X-Bridge-Token", "value": bridge_user_token})
        header_parameters["parameters"] = headers
        parameters["headerParameters"] = header_parameters
        parsed_url = urlsplit(url)
        target_path = parsed_url.path.rstrip("/") or "/"
        if target_path == "/send":
            body_parameters = parameters.get("bodyParameters")
            if isinstance(body_parameters, dict):
                params_list = body_parameters.get("parameters")
                if isinstance(params_list, list):
                    for entry in params_list:
                        if not isinstance(entry, dict):
                            continue
                        if str(entry.get("name", "")).strip().lower() != "from":
                            continue
                        value = str(entry.get("value", "")).strip()
                        if value and value not in {"system", "user"}:
                            entry["value"] = "system"
            json_body = parameters.get("jsonBody")
            if isinstance(json_body, str):

                def _replace_sender(match: re.Match[str]) -> str:
                    quote = match.group("quote")
                    value = match.group("value")
                    if value in {"system", "user"}:
                        return match.group(0)
                    return f"{match.group('prefix')}{quote}system{quote}"

                parameters["jsonBody"] = re.sub(
                    r"(?P<prefix>\bfrom\s*:\s*)(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)",
                    _replace_sender,
                    json_body,
                    count=1,
                )
    return patched


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/n8n/executions":
        limit = min(int(query.get("limit", ["20"])[0]), 100)
        status_filter = query.get("status", [None])[0]
        params: dict[str, Any] = {"limit": limit}
        if status_filter:
            params["status"] = status_filter
        status, data = _n8n_request("GET", "/executions", params=params)
        if status >= 400:
            handler._respond(status, data if isinstance(data, dict) else {"error": str(data)})
            return True
        handler._respond(200, data)
        return True

    if path == "/n8n/workflows":
        limit = min(int(query.get("limit", ["50"])[0]), 250)
        status, data = _n8n_request("GET", "/workflows", params={"limit": limit})
        if status >= 400:
            handler._respond(status, data if isinstance(data, dict) else {"error": str(data)})
            return True
        handler._respond(200, data)
        return True

    if path == "/workflows/capabilities":
        handler._respond(200, workflow_builder.list_capabilities())
        return True

    workflow_definition_match = re.match(r"^/workflows/([^/]+)/definition$", path)
    if workflow_definition_match:
        workflow_id = workflow_definition_match.group(1)
        record = _workflow_record_for_id(workflow_id)
        if not record:
            handler._respond(404, {"error": f"workflow '{workflow_id}' has no Bridge definition"})
            return True
        handler._respond(
            200,
            {
                "workflow_id": workflow_id,
                "definition": record.get("bridge_spec"),
                "source": record.get("source", "n8n"),
                "template_id": record.get("template_id", ""),
                "variables_used": record.get("variables_used", {}),
                "compiled_workflow": record.get("compiled_workflow"),
            },
        )
        return True

    if path == "/workflows":
        limit = min(int(query.get("limit", ["50"])[0]), 250)
        status, data = _n8n_request("GET", "/workflows", params={"limit": limit})
        if status >= 400:
            handler._respond(status, data if isinstance(data, dict) else {"error": str(data)})
            return True
        workflows = [_workflow_projection(workflow) for workflow in data.get("data", [])]
        handler._respond(200, {"workflows": workflows, "count": len(workflows)})
        return True

    if path == "/workflows/templates":
        templates: list[dict[str, Any]] = []
        if os.path.isdir(WORKFLOW_TEMPLATES_DIR):
            for filename in sorted(os.listdir(WORKFLOW_TEMPLATES_DIR)):
                if not filename.endswith(".json"):
                    continue
                template_path = os.path.join(WORKFLOW_TEMPLATES_DIR, filename)
                try:
                    with open(template_path, encoding="utf-8") as handle:
                        template = json.load(handle)
                except Exception:
                    continue
                templates.append(
                    {
                        "template_id": template.get("template_id"),
                        "name": template.get("name"),
                        "description": template.get("description"),
                        "category": template.get("category"),
                        "difficulty": template.get("difficulty"),
                        "icon": template.get("icon"),
                        "variables": template.get("variables", []),
                        "setup_steps": template.get("setup_steps", []),
                    }
                )
        handler._respond(200, {"templates": templates, "count": len(templates)})
        return True

    if path == "/workflows/tools":
        tools_list = list(_WORKFLOW_TOOLS.values())
        handler._respond(200, {"tools": tools_list, "count": len(tools_list)})
        return True

    if path == "/workflows/suggest":
        message_text = query.get("message", [""])[0].strip()
        if not message_text:
            handler._respond(400, {"error": "query parameter 'message' is required"})
            return True
        try:
            intent = workflow_bot.detect_workflow_intent(message_text)
            if intent is None:
                handler._respond(200, {"intent": None})
                return True
            intent_type = intent.get("intent", "")
            result: dict[str, Any] = dict(intent)
            if intent_type == "create_workflow":
                result["formatted_response"] = workflow_bot.format_create_response(intent)
            elif intent_type == "list_workflows":
                try:
                    _, workflow_data = _n8n_request("GET", "/workflows", params={"limit": 50})
                    workflows = [
                        {"id": workflow.get("id"), "name": workflow.get("name"), "active": workflow.get("active")}
                        for workflow in (workflow_data.get("data", []) if isinstance(workflow_data, dict) else [])
                    ]
                    result["formatted_response"] = workflow_bot.format_list_response(workflows)
                    result["workflows"] = workflows
                except Exception:
                    result["formatted_response"] = workflow_bot.format_list_response([])
                    result["workflows"] = []
            elif intent_type == "toggle_workflow":
                result["formatted_response"] = workflow_bot.format_toggle_response(intent.get("workflow_name", ""))
            elif intent_type == "delete_workflow":
                result["formatted_response"] = workflow_bot.format_delete_response(intent.get("workflow_name", ""))
            handler._respond(200, result)
        except Exception as exc:
            handler._respond(500, {"error": f"workflow bot error: {exc}"})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path == "/workflows/compile":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        spec = data.get("definition")
        if spec is None:
            spec = data.get("workflow")
        if spec is None:
            spec = data
        if not isinstance(spec, dict):
            handler._respond(400, {"error": "workflow definition must be an object"})
            return True
        try:
            compiled = workflow_builder.compile_bridge_workflow(spec)
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        handler._respond(
            200,
            {
                "ok": True,
                "workflow": compiled["workflow"],
                "node_names_by_id": compiled.get("node_names_by_id", {}),
                "bridge_subscription": compiled.get("bridge_subscription"),
                "validation": compiled.get("validation", {}),
            },
        )
        return True

    if path == "/workflows/deploy":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        spec = data.get("definition")
        if spec is None:
            spec = data.get("workflow")
        if spec is None:
            spec = data
        if not isinstance(spec, dict):
            handler._respond(400, {"error": "workflow definition must be an object"})
            return True
        activate = bool(data.get("activate", True))
        try:
            compiled = workflow_builder.compile_bridge_workflow(spec)
            workflow_def = compiled["workflow"]
            workflow_name = str(workflow_def.get("name", "")).strip() or str(spec.get("name", "")).strip()
            workflow_id, n8n_resp, activation_warning = _deploy_workflow_to_n8n(
                workflow_def,
                workflow_name=workflow_name,
                activate=activate,
            )
            subscription_info = _register_workflow_subscription(
                workflow_name,
                workflow_def,
                compiled.get("bridge_subscription"),
                created_by="workflow-builder",
            )
            tool_info = _register_workflow_webhook_tool(workflow_name, workflow_id, workflow_def)
            _record_workflow_deployment(
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                source="bridge_builder",
                bridge_spec=spec,
                bridge_subscription=subscription_info,
                tool_registered=tool_info,
                compiled_workflow=workflow_def,
            )
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True
        except RuntimeError as exc:
            handler._respond(502, {"error": str(exc)})
            return True

        result: dict[str, Any] = {
            "ok": True,
            "workflow": {
                "id": workflow_id,
                "name": n8n_resp.get("name", workflow_name),
                "active": n8n_resp.get("active"),
            },
            "validation": compiled.get("validation", {}),
        }
        if subscription_info:
            result["event_subscription"] = subscription_info
        if tool_info:
            result["tool_registered"] = tool_info
        if activation_warning:
            result["activation_warning"] = activation_warning
        handler._respond(201, result)
        return True

    if path == "/workflows/deploy-template":
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        template_id = str(data.get("template_id", "")).strip()
        if not template_id:
            handler._respond(400, {"error": "template_id is required"})
            return True
        variables = data.get("variables", {})
        if not isinstance(variables, dict):
            handler._respond(400, {"error": "variables must be a dict"})
            return True

        tpl = None
        if os.path.isdir(WORKFLOW_TEMPLATES_DIR):
            for fname in os.listdir(WORKFLOW_TEMPLATES_DIR):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(WORKFLOW_TEMPLATES_DIR, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        candidate = json.load(f)
                    if candidate.get("template_id") == template_id:
                        tpl = candidate
                        break
                except Exception:
                    continue
        if not tpl:
            handler._respond(404, {"error": f"template '{template_id}' not found"})
            return True

        vars_dict = dict(variables)
        for var_def in tpl.get("variables", []):
            key = var_def["key"]
            if var_def.get("required") and key not in vars_dict:
                if "default" in var_def:
                    vars_dict[key] = str(var_def["default"])
                else:
                    handler._respond(400, {"error": f"required variable '{key}' missing"})
                    return True
            elif key not in vars_dict and "default" in var_def:
                vars_dict[key] = str(var_def["default"])
        try:
            vars_dict = _normalize_workflow_template_variables(template_id, vars_dict)
        except ValueError as exc:
            handler._respond(400, {"error": str(exc)})
            return True

        def _substitute(obj: Any, vs: dict[str, str]) -> Any:
            if isinstance(obj, str):
                for k, v in vs.items():
                    obj = obj.replace("{{" + k + "}}", str(v))
                return obj
            if isinstance(obj, dict):
                return {k: _substitute(v, vs) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_substitute(item, vs) for item in obj]
            return obj

        workflow_def = _substitute(tpl["n8n_workflow"], vars_dict)
        vr = workflow_validator.validate_workflow(workflow_def)
        if not vr.valid:
            handler._respond(400, {"error": "workflow validation failed", "validation": vr.to_dict()})
            return True

        try:
            wf_id, n8n_resp, activation_warning = _deploy_workflow_to_n8n(
                workflow_def,
                workflow_name=str(workflow_def.get("name", tpl["name"])).strip() or str(tpl["name"]),
                activate=True,
            )
        except RuntimeError as exc:
            handler._respond(502, {"error": str(exc)})
            return True

        result: dict[str, Any] = {
            "ok": True,
            "template_id": template_id,
            "workflow": {
                "id": wf_id,
                "name": n8n_resp.get("name"),
                "active": n8n_resp.get("active"),
            },
            "variables_used": vars_dict,
        }

        subscription_info = _register_workflow_subscription(
            str(workflow_def.get("name", tpl["name"])),
            workflow_def,
            tpl.get("bridge_subscription"),
            created_by="workflow-deployer",
        )
        if subscription_info:
            result["event_subscription"] = subscription_info

        tool_info = _register_workflow_webhook_tool(
            str(workflow_def.get("name", tpl["name"])),
            str(wf_id),
            workflow_def,
        )
        if tool_info:
            result["tool_registered"] = tool_info

        _record_workflow_deployment(
            workflow_id=str(wf_id),
            workflow_name=str(workflow_def.get("name", tpl["name"])),
            source="template",
            template_id=template_id,
            bridge_spec={
                "kind": "template_deploy",
                "template_id": template_id,
                "variables": vars_dict,
            },
            bridge_subscription=subscription_info,
            tool_registered=tool_info,
            compiled_workflow=workflow_def,
            variables_used=vars_dict,
        )

        if vr.warnings:
            result["validation_warnings"] = vr.warnings
        if activation_warning:
            result["activation_warning"] = activation_warning
        handler._respond(201, result)
        return True

    return False


def handle_patch(handler: Any, path: str) -> bool:
    toggle_match = re.match(r"^/workflows/([^/]+)/toggle$", path)
    if not toggle_match:
        return False

    wf_id = toggle_match.group(1)
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True
    active = data.get("active")
    if active is None or not isinstance(active, bool):
        handler._respond(400, {"error": "active (boolean) is required"})
        return True

    status, wf_data = _n8n_request("GET", f"/workflows/{wf_id}")
    if status >= 400:
        handler._respond(status, wf_data if isinstance(wf_data, dict) else {"error": str(wf_data)})
        return True

    if active:
        status2, resp = _n8n_request("POST", f"/workflows/{wf_id}/activate")
    else:
        status2, resp = _n8n_request("POST", f"/workflows/{wf_id}/deactivate")
    if status2 >= 400:
        handler._respond(status2, resp if isinstance(resp, dict) else {"error": str(resp)})
        return True

    handler._respond(200, {"ok": True, "workflow": {"id": wf_id, "active": active}})
    return True


def handle_put(handler: Any, path: str) -> bool:
    update_match = re.match(r"^/workflows/([^/]+)/definition$", path)
    if not update_match:
        return False

    workflow_id = update_match.group(1)
    record = _workflow_record_for_id(workflow_id)
    if not record:
        handler._respond(404, {"error": f"workflow '{workflow_id}' has no Bridge definition"})
        return True
    if record.get("source") != "bridge_builder":
        handler._respond(409, {"error": "only Bridge Builder workflows can be updated in place"})
        return True

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    spec = data.get("definition")
    if spec is None:
        spec = data.get("workflow")
    if spec is None:
        spec = data
    if not isinstance(spec, dict):
        handler._respond(400, {"error": "workflow definition must be an object"})
        return True

    try:
        compiled = workflow_builder.compile_bridge_workflow(spec)
        workflow_def = compiled["workflow"]
        workflow_name = str(workflow_def.get("name", "")).strip() or str(spec.get("name", "")).strip()
        updated_resp, activation_warning = _update_workflow_in_n8n(
            workflow_id,
            workflow_def,
            workflow_name=workflow_name,
        )
        old_subscription = record.get("bridge_subscription") or {}
        old_sub_id = str(old_subscription.get("subscription_id", "")).strip()
        if old_sub_id:
            event_bus.unsubscribe(old_sub_id)
        subscription_info = _register_workflow_subscription(
            workflow_name,
            workflow_def,
            compiled.get("bridge_subscription"),
            created_by="workflow-builder",
        )
        tool_info = _register_workflow_webhook_tool(workflow_name, workflow_id, workflow_def)
        _record_workflow_deployment(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            source="bridge_builder",
            bridge_spec=spec,
            bridge_subscription=subscription_info,
            tool_registered=tool_info,
            compiled_workflow=workflow_def,
        )
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    except RuntimeError as exc:
        handler._respond(502, {"error": str(exc)})
        return True

    payload: dict[str, Any] = {
        "ok": True,
        "workflow": {
            "id": workflow_id,
            "name": updated_resp.get("name", workflow_name),
            "active": updated_resp.get("active"),
        },
        "validation": compiled.get("validation", {}),
    }
    if subscription_info:
        payload["event_subscription"] = subscription_info
    if tool_info:
        payload["tool_registered"] = tool_info
    if activation_warning:
        payload["activation_warning"] = activation_warning
    handler._respond(200, payload)
    return True


def handle_delete(handler: Any, path: str) -> bool:
    delete_match = re.match(r"^/workflows/([^/]+)$", path)
    if not delete_match:
        return False

    wf_id = delete_match.group(1)
    record = _workflow_record_for_id(wf_id)
    status, resp = _n8n_request("DELETE", f"/workflows/{wf_id}")
    if status >= 400:
        handler._respond(status, resp if isinstance(resp, dict) else {"error": str(resp)})
        return True
    cleanup = _workflow_delete_cleanup(record)
    if record:
        _remove_workflow_record(wf_id)
    handler._respond(200, {"ok": True, "deleted_workflow": wf_id, "cleanup": cleanup})
    return True


def _deploy_workflow_to_n8n(
    workflow_def: dict[str, Any],
    *,
    workflow_name: str,
    activate: bool = True,
) -> tuple[str, dict[str, Any], str | None]:
    runtime_workflow = _inject_bridge_workflow_auth_headers(workflow_def)
    create_body: dict[str, Any] = {
        "name": workflow_name,
        "nodes": runtime_workflow.get("nodes", []),
        "connections": runtime_workflow.get("connections", {}),
        "settings": runtime_workflow.get("settings", {"executionOrder": "v1"}),
    }
    status, n8n_resp = _n8n_request("POST", "/workflows", body=create_body)
    if status >= 400:
        raise RuntimeError(
            (n8n_resp or {}).get("error", f"n8n workflow create failed (HTTP {status})")
            if isinstance(n8n_resp, dict)
            else f"n8n workflow create failed (HTTP {status})"
        )
    workflow_id = str(n8n_resp.get("id", "")).strip()
    activation_warning = None
    if activate and workflow_id:
        act_status, act_resp = _n8n_request("POST", f"/workflows/{workflow_id}/activate")
        if act_status < 400 and isinstance(act_resp, dict) and act_resp.get("active"):
            n8n_resp["active"] = True
        else:
            activation_warning = (
                f"Workflow deployed but activation failed (HTTP {act_status}). "
                "Check n8n credentials or node configuration."
            )
    return workflow_id, n8n_resp if isinstance(n8n_resp, dict) else {}, activation_warning


def _update_workflow_in_n8n(
    workflow_id: str,
    workflow_def: dict[str, Any],
    *,
    workflow_name: str,
) -> tuple[dict[str, Any], str | None]:
    runtime_workflow = _inject_bridge_workflow_auth_headers(workflow_def)
    status, existing = _n8n_request("GET", f"/workflows/{workflow_id}")
    if status >= 400:
        raise RuntimeError(
            (existing or {}).get("error", f"n8n workflow load failed (HTTP {status})")
            if isinstance(existing, dict)
            else f"n8n workflow load failed (HTTP {status})"
        )
    was_active = bool(existing.get("active")) if isinstance(existing, dict) else False
    update_body: dict[str, Any] = {
        "name": workflow_name,
        "nodes": runtime_workflow.get("nodes", []),
        "connections": runtime_workflow.get("connections", {}),
        "settings": runtime_workflow.get("settings", {"executionOrder": "v1"}),
    }
    put_status, put_resp = _n8n_request("PUT", f"/workflows/{workflow_id}", body=update_body)
    if put_status >= 400:
        raise RuntimeError(
            (put_resp or {}).get("error", f"n8n workflow update failed (HTTP {put_status})")
            if isinstance(put_resp, dict)
            else f"n8n workflow update failed (HTTP {put_status})"
        )
    activation_warning = None
    if was_active:
        act_status, act_resp = _n8n_request("POST", f"/workflows/{workflow_id}/activate")
        if act_status < 400 and isinstance(act_resp, dict) and act_resp.get("active"):
            if isinstance(put_resp, dict):
                put_resp["active"] = True
        else:
            activation_warning = (
                f"Workflow updated but could not be reactivated (HTTP {act_status}). "
                "Check n8n credentials or node configuration."
            )
    return put_resp if isinstance(put_resp, dict) else {}, activation_warning


def _register_workflow_subscription(
    workflow_name: str,
    workflow_def: dict[str, Any],
    bridge_subscription: dict[str, Any] | None,
    *,
    created_by: str,
) -> dict[str, Any] | None:
    if not isinstance(bridge_subscription, dict):
        return None
    event_type = str(bridge_subscription.get("event_type", "")).strip()
    if not event_type:
        return None
    webhook_path = str(bridge_subscription.get("webhook_path", "")).strip() or _find_first_webhook_path(workflow_def)
    if not webhook_path:
        return None
    n8n_base, _ = _load_n8n_config()
    webhook_url = f"{n8n_base}/webhook/{webhook_path}"
    existing_subs = event_bus.list_subscriptions()
    for existing in existing_subs:
        if existing.get("event_type") == event_type and existing.get("webhook_url") == webhook_url and existing.get("active"):
            return {
                "subscription_id": existing.get("id", ""),
                "event_type": event_type,
                "filter": existing.get("filter", {}),
                "webhook_path": webhook_path,
                "webhook_url": webhook_url,
                "label": existing.get("label", ""),
                "deduplicated": True,
            }
    sub = event_bus.subscribe(
        event_type=event_type,
        webhook_url=webhook_url,
        created_by=created_by,
        filter_rules=bridge_subscription.get("filter") if isinstance(bridge_subscription.get("filter"), dict) else {},
        label=f"auto: {workflow_name}",
    )
    return {
        "subscription_id": sub.get("id", ""),
        "event_type": event_type,
        "filter": bridge_subscription.get("filter", {}) if isinstance(bridge_subscription.get("filter"), dict) else {},
        "webhook_path": webhook_path,
        "webhook_url": webhook_url,
        "label": sub.get("label", ""),
    }


def _register_workflow_webhook_tool(
    workflow_name: str,
    workflow_id: str,
    workflow_def: dict[str, Any],
) -> dict[str, Any] | None:
    webhook_path = _find_first_webhook_path(workflow_def)
    if not webhook_path:
        return None
    n8n_base, _ = _load_n8n_config()
    webhook_url = f"{n8n_base}/webhook/{webhook_path}"
    tool_name = _workflow_tool_name(workflow_name, workflow_id)
    tool_info = {
        "name": tool_name,
        "workflow_name": workflow_name,
        "workflow_id": workflow_id,
        "webhook_url": webhook_url,
        "registered_at": _utc_now(),
    }
    _register_workflow_tool(tool_info)
    return tool_info
