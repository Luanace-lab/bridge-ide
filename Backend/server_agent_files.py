"""Agent instruction/config/permission helpers extracted from server.py."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

_INSTRUCTION_FILE_BY_ENGINE: dict[str, str] = {}
_ENSURE_PARENT_DIR_FN: Callable[[str], None] = lambda _path: None


def init(
    *,
    instruction_file_by_engine: dict[str, str],
    ensure_parent_dir_fn: Callable[[str], None],
) -> None:
    """Bind shared config and utility callbacks from server.py."""
    global _INSTRUCTION_FILE_BY_ENGINE
    global _ENSURE_PARENT_DIR_FN

    _INSTRUCTION_FILE_BY_ENGINE = dict(instruction_file_by_engine)
    _ENSURE_PARENT_DIR_FN = ensure_parent_dir_fn


def agent_instruction_file(project_path: str, engine: str) -> str:
    filename = _INSTRUCTION_FILE_BY_ENGINE.get(engine.lower(), "CLAUDE.md")
    return os.path.join(project_path, filename)


def _update_instruction_roles(file_path: str, roles: list[tuple[str, str]]) -> None:
    active = [(label, role) for label, role in roles if role]
    if not active:
        return

    if len(active) == 1:
        _, role = active[0]
        new_section = f"## Rolle: {role}"
    else:
        parts = ["## Rollen", ""]
        for label, role in active:
            parts.append(f"- {label}: {role}")
        new_section = "\n".join(parts)

    _ENSURE_PARENT_DIR_FN(file_path)
    if os.path.exists(file_path):
        content = Path(file_path).read_text(encoding="utf-8")
    else:
        engine_name = os.path.splitext(os.path.basename(file_path))[0]
        content = f"# {engine_name}\n"

    content = re.sub(
        r"\n*## Rollen?[:\s].*?(?=\n## |\Z)",
        "",
        content,
        flags=re.DOTALL,
    )
    content = content.rstrip("\n") + "\n\n" + new_section + "\n"
    Path(file_path).write_text(content, encoding="utf-8")


def agent_config_file(project_path: str, engine: str) -> str:
    e = engine.lower()
    if e == "claude":
        return os.path.join(project_path, ".claude", "settings.json")
    if e == "codex":
        return os.path.join(project_path, ".codex", "config.toml")
    if e in ("gemini", "qwen"):
        return os.path.join(project_path, f".{e}", "settings.json")
    return os.path.join(project_path, ".claude", "settings.json")


def _toml_get_str(content: str, key: str) -> str:
    match = re.search(r"^\s*" + re.escape(key) + r'\s*=\s*"([^"]*)"', content, re.MULTILINE)
    return match.group(1) if match else ""


def _toml_set_str(content: str, key: str, value: str) -> str:
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=.*$", re.MULTILINE)
    new_line = f'{key} = "{value}"'
    if pattern.search(content):
        return pattern.sub(new_line, content)
    prefix = content.rstrip() + "\n" if content.strip() else ""
    return prefix + new_line + "\n"


def _toml_remove_key(content: str, key: str) -> str:
    return re.sub(r"^\s*" + re.escape(key) + r"\s*=.*\n?", "", content, flags=re.MULTILINE)


def _default_permissions() -> dict[str, bool]:
    return {
        "web_search": False,
        "web_fetch": False,
        "file_read": False,
        "file_write": False,
        "shell": False,
        "auto_approve": False,
        "full_filesystem": False,
    }


def read_agent_permissions(project_path: str, engine: str) -> dict[str, bool]:
    config_path = agent_config_file(project_path, engine)
    e = engine.lower()
    if not os.path.exists(config_path):
        return _default_permissions()
    try:
        raw = Path(config_path).read_text(encoding="utf-8")
    except OSError:
        return _default_permissions()

    if e == "claude":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return _default_permissions()
        perms = data.get("permissions", {})
        allow = perms.get("allow", [])
        if not isinstance(allow, list):
            allow = []
        additional_dirs = perms.get("additionalDirectories", [])
        if not isinstance(additional_dirs, list):
            additional_dirs = []
        default_mode = str(perms.get("defaultMode", "")).strip()
        return {
            "web_search": any("WebSearch" in str(a) for a in allow),
            "web_fetch": any("WebFetch" in str(a) for a in allow),
            "file_read": any("Read" in str(a) for a in allow),
            "file_write": default_mode != "plan" and any("Edit" in str(a) or "Write" in str(a) for a in allow),
            "shell": default_mode != "plan" and any("Bash" in str(a) for a in allow),
            "auto_approve": default_mode in ("acceptEdits", "dontAsk", "bypassPermissions", "auto"),
            "full_filesystem": "/" in additional_dirs,
        }

    if e == "codex":
        web_search = _toml_get_str(raw, "web_search")
        sandbox = _toml_get_str(raw, "sandbox_mode")
        approval = _toml_get_str(raw, "approval_policy")
        return {
            "web_search": web_search == "live",
            "web_fetch": False,
            "file_read": sandbox in ("read-only", "workspace-write", "danger-full-access"),
            "file_write": sandbox in ("workspace-write", "danger-full-access"),
            "shell": approval == "never",
            "auto_approve": approval == "never",
            "full_filesystem": sandbox == "danger-full-access",
        }

    if e in ("gemini", "qwen"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return _default_permissions()
        tools = data.get("tools", {})
        allowed = tools.get("allowed", [])
        if not isinstance(allowed, list):
            allowed = []
        if e == "gemini":
            approval_mode = str(data.get("general", {}).get("defaultApprovalMode", "")).strip()
        else:
            approval_mode = str(tools.get("approvalMode", "")).strip()
        if e == "gemini":
            auto_approve = approval_mode in ("auto_edit", "yolo")
        else:
            auto_approve = approval_mode in ("auto-edit", "yolo")
        full_fs = data.get("security", {}).get("folderTrust", {}).get("enabled", False)
        return {
            "web_search": "google_web_search" in allowed,
            "web_fetch": "http_fetch" in allowed,
            "file_read": True,
            "file_write": approval_mode not in ("plan", ""),
            "shell": "run_shell_command" in allowed,
            "auto_approve": auto_approve,
            "full_filesystem": bool(full_fs),
        }

    return _default_permissions()


def write_agent_permission(project_path: str, engine: str, permission: str, value: bool) -> None:
    config_path = agent_config_file(project_path, engine)
    _ENSURE_PARENT_DIR_FN(config_path)
    e = engine.lower()
    raw = ""
    if os.path.exists(config_path):
        try:
            raw = Path(config_path).read_text(encoding="utf-8")
        except OSError:
            raw = ""

    if e == "claude":
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if "permissions" not in data:
            data["permissions"] = {}
        perms = data["permissions"]
        if "allow" not in perms:
            perms["allow"] = []
        allow: list[Any] = perms["allow"]
        perm_tokens = {
            "web_search": "WebSearch",
            "web_fetch": "WebFetch",
            "file_read": "Read(**)",
            "file_write": "Edit(**)",
            "shell": "Bash(**)",
        }
        if permission in perm_tokens:
            token = perm_tokens[permission]
            if value and token not in allow:
                allow.append(token)
            elif not value and token in allow:
                allow.remove(token)
        elif permission == "auto_approve":
            if value:
                perms["defaultMode"] = "acceptEdits"
            else:
                perms.pop("defaultMode", None)
        elif permission == "full_filesystem":
            if "additionalDirectories" not in perms:
                perms["additionalDirectories"] = []
            dirs: list[Any] = perms["additionalDirectories"]
            if value and "/" not in dirs:
                dirs.append("/")
            elif not value and "/" in dirs:
                dirs.remove("/")
        Path(config_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    if e == "codex":
        if permission == "web_search":
            raw = _toml_set_str(raw, "web_search", "live" if value else "disabled")
        elif permission == "file_read":
            if value:
                current = _toml_get_str(raw, "sandbox_mode")
                if current not in ("workspace-write", "danger-full-access"):
                    raw = _toml_set_str(raw, "sandbox_mode", "read-only")
            else:
                raw = _toml_remove_key(raw, "sandbox_mode")
        elif permission == "file_write":
            if value:
                raw = _toml_set_str(raw, "sandbox_mode", "workspace-write")
            elif _toml_get_str(raw, "sandbox_mode") == "workspace-write":
                raw = _toml_set_str(raw, "sandbox_mode", "read-only")
        elif permission in ("shell", "auto_approve"):
            if value:
                raw = _toml_set_str(raw, "approval_policy", "never")
            else:
                raw = _toml_remove_key(raw, "approval_policy")
        elif permission == "full_filesystem":
            if value:
                raw = _toml_set_str(raw, "sandbox_mode", "danger-full-access")
            elif _toml_get_str(raw, "sandbox_mode") == "danger-full-access":
                raw = _toml_set_str(raw, "sandbox_mode", "workspace-write")
        Path(config_path).write_text(raw, encoding="utf-8")
        return

    if e in ("gemini", "qwen"):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if "tools" not in data:
            data["tools"] = {}
        tools_d: dict[str, Any] = data["tools"]
        if "allowed" not in tools_d:
            tools_d["allowed"] = []
        allowed_list: list[Any] = tools_d["allowed"]

        def _add(token: str) -> None:
            if token not in allowed_list:
                allowed_list.append(token)

        def _rem(token: str) -> None:
            if token in allowed_list:
                allowed_list.remove(token)

        if e == "gemini":
            if "general" not in data:
                data["general"] = {}
            approval_mode = str(data["general"].get("defaultApprovalMode", "")).strip()
        else:
            approval_mode = str(tools_d.get("approvalMode", "")).strip()

        if permission == "web_search":
            _add("google_web_search") if value else _rem("google_web_search")
        elif permission == "web_fetch":
            _add("http_fetch") if value else _rem("http_fetch")
        elif permission == "file_write":
            tools_d["sandbox"] = not value
            if e == "gemini":
                data["general"]["defaultApprovalMode"] = approval_mode if value and approval_mode else "default"
                if not value:
                    data["general"]["defaultApprovalMode"] = "plan"
            else:
                if value:
                    tools_d["approvalMode"] = approval_mode if approval_mode and approval_mode != "plan" else "default"
                else:
                    tools_d["approvalMode"] = "plan"
        elif permission == "shell":
            _add("run_shell_command") if value else _rem("run_shell_command")
        elif permission == "auto_approve":
            if e == "gemini":
                data["general"]["defaultApprovalMode"] = "auto_edit" if value else "default"
            else:
                tools_d["approvalMode"] = "auto-edit" if value else "default"
        elif permission == "full_filesystem":
            if "security" not in data:
                data["security"] = {}
            if "folderTrust" not in data["security"]:
                data["security"]["folderTrust"] = {}
            data["security"]["folderTrust"]["enabled"] = value
        Path(config_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
