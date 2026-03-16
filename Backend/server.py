#!/usr/bin/env python3
"""
Local bridge server for realtime agent communication and runtime orchestration.

Core endpoints:
  GET  / or /ui
    Serve the visual bridge UI.

  POST /send
    JSON body: {"from": "...", "to": "...", "content": "...", "meta": {...?}}

  GET  /receive/<agent_id>?wait=<seconds>&limit=<n>
    Long-poll unread messages for an agent.

  GET  /history?limit=<n>&after_id=<id>&since=<iso_timestamp>
    Return message history. Optional since= filters to messages after given ISO timestamp.

  GET  /status
    Return server health and runtime summary.

Runtime / IDE-style orchestration:
  GET  /runtime
    Return active pair mode, project path and managed agent status.

  POST /runtime/configure
    Configure and (re)start managed agent loops.

  POST /runtime/stop
    Stop managed agent loops.

Projects and context:
  GET  /projects?base_dir=<path>
    List project directories.

  POST /projects/create
    Create/scaffold a project.

  GET  /context?project_path=<path>
    Return Codex/Claude relevant context paths and file presence.

Logs:
  GET  /logs?name=<agent_log_name>&lines=<n>
    Tail log files for quick diagnostics.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from auth import _RateLimiter
import board_api
import event_bus
import tool_store
import token_tracker
import credential_store
import guardrails
import runtime_layout
import workflow_bot
import workflow_builder
import workflow_validator
from routing_policy import (
    derive_aliases as shared_derive_aliases,
    derive_routes as shared_derive_routes,
    derive_team_routes as shared_derive_team_routes,
)
from persistence_utils import (
    context_bridge_candidates,
    detect_instruction_filename,
    ensure_agent_memory_file,
    find_agent_memory_path,
    find_memory_backup_path,
    first_existing_path,
    instruction_filename_for_engine,
    instruction_candidates,
    resolve_agent_cli_layout,
    soul_candidates,
)
from handlers.cli import (
    write_file_if_missing,
    _run_cli_probe,
    _probe_cli_auth_status,
    _probe_cli_runtime_status,
    _build_subscription_response_item,
    _detect_cli_setup_state,
    _get_cli_setup_state_cached,
    _render_buddy_operator_guide,
    _render_buddy_engine_doc,
    _render_agent_engine_doc,
    _materialize_agent_setup_home,
    _CLI_SETUP_STATE_LOCK,
    _CLI_SETUP_STATE_INFLIGHT,
    _CLI_SETUP_STATE_CACHE,
    _CLI_SETUP_STATE_CACHE_AT,
    _CLI_SETUP_STATE_CACHE_TTL_SECONDS,
    _SETUP_CLI_BINARIES,
    _SETUP_API_ENV_VARS,
    _infer_subscription_provider,
)
from handlers.messages import (
    load_history,
    persist_message,
    append_message,
    messages_for_agent,
    cursor_index_after_message_id,
    _broadcast_fingerprint,
    _is_duplicate_broadcast,
    _is_duplicate_direct,
    _is_echo_ack_message,
    init as _init_messages,
)
from handlers.agents import (
    _registered_agents_snapshot,
    agent_connection_status,
    _agent_liveness_ts,
    _agent_is_live,
    _clear_agent_runtime_presence,
    update_agent_status,
    _notify_agent_back_online,
    _check_tmux_session,
    _get_agent_engine,
    handle_post as _handle_agents_post,
    handle_put as _handle_agents_put,
    _PREV_AGENT_STATUS,
    init as _init_agents,
)
from handlers.runtime import (
    _runtime_project_id,
    _runtime_team_name,
    _normalize_runtime_permission_mode,
    _normalize_runtime_level,
    _normalize_runtime_capabilities,
    _normalize_runtime_tools,
    _normalize_runtime_profile,
    _build_runtime_agent_profiles,
    _runtime_team_members_for_profiles,
    _build_runtime_overlay,
    _persist_runtime_overlay,
    _load_runtime_overlay_from_disk,
    _restore_runtime_from_overlay,
    _current_runtime_overlay,
    _runtime_overlay_orgchart_response,
    _runtime_overlay_team_projects_response,
    _runtime_overlay_board_projects_response,
    _runtime_overlay_teams_response,
    _runtime_overlay_team_detail,
    _runtime_overlay_team_context,
    current_runtime_agent_ids,
    current_runtime_slot_map,
    reset_team_lead_state,
    runtime_agents_for_layout,
    _wait_for_agent_registration,
    _clear_runtime_configuration,
    runtime_snapshot,
    _get_runtime_agent_role,
    init as _init_runtime,
)
from handlers.tasks import (
    _rotate_wal_if_needed,
    _append_task_transition_wal,
    _task_required_capabilities,
    _persist_tasks,
    _count_agent_active_tasks,
    _load_tasks_from_disk,
    _persist_escalation_state,
    _load_escalation_state_from_disk,
    _clear_task_lease,
    _refresh_task_lease,
    _check_task_timeouts,
    _escalate_stage_1,
    _escalate_stage_2,
    _escalate_stage_3,
    _whiteboard_delete_by_task,
    _resolve_escalation,
    _log_task_event,
    ESCALATION_STATE,
    ESCALATION_LOCK,
    init as _init_tasks,
)
from handlers.scope_locks import (
    _persist_scope_locks,
    _load_scope_locks_from_disk,
    _normalize_scope_path,
    _scope_label_for_path,
    _parse_scope_tokens,
    _candidate_scope_paths,
    _resolve_agent_scope_entries,
    _is_edit_activity,
    _check_activity_scope_violation,
    _lock_scope_path,
    _unlock_scope_paths,
    _cleanup_expired_scope_locks,
    _refresh_scope_locks_for_task,
    _log_scope_event,
    init as _init_scope_locks,
)
from handlers.whiteboard import (
    handle_delete as _handle_whiteboard_delete,
    handle_get as _handle_whiteboard_get,
    handle_post as _handle_whiteboard_post,
    _whiteboard_post,
    _cleanup_expired_whiteboard,
    _persist_whiteboard,
    _load_whiteboard_from_disk,
    _log_whiteboard_event,
    init as _init_whiteboard,
)
from handlers.approvals import (
    handle_get as _handle_approvals_get,
    handle_post as _handle_approvals_post,
    APPROVAL_REQUESTS,
    APPROVAL_LOCK,
    APPROVAL_DEFAULT_TIMEOUT,
    _approval_generate_id,
    _approval_expire_check,
    _load_standing_approvals,
    _save_standing_approvals,
    _sa_generate_id,
    _sa_audit_log,
    _check_standing_approval,
    _sa_increment_usage,
    _AGENT_PAAP_CLEARED,
    _load_paap_violations,
    _save_paap_violations,
    _AGENT_PAAP_VIOLATIONS,
    _is_paap_external_action,
    _SA_LOCK,
    init as _init_approvals,
)
from handlers.skills import (
    handle_get as _handle_skills_get,
    handle_post as _handle_skills_post,
    _PROPOSALS_DIR,
    _PROPOSALS_LOCK,
    _SKILL_PROPOSALS,
    _save_proposals,
    _scan_skills,
    _get_skill_full,
    _generate_skills_section,
    _suggest_skills_for_agent,
    _auto_provision_skills,
    init as _init_skills,
)
from handlers.health import (
    _check_agent_memory_health,
    _compute_health,
    init as _init_health,
)
from handlers.guardrails_routes import (
    handle_delete as _handle_guardrails_delete,
    handle_get as _handle_guardrails_get,
    handle_post as _handle_guardrails_post,
    handle_put as _handle_guardrails_put,
    init as _init_guardrails_routes,
)
from handlers.capability_library_routes import (
    handle_get as _handle_capability_library_get,
    handle_post as _handle_capability_library_post,
)
from handlers.shared_tools_routes import (
    handle_delete as _handle_shared_tools_delete,
    handle_get as _handle_shared_tools_get,
    handle_post as _handle_shared_tools_post,
    init as _init_shared_tools_routes,
)
from handlers.chat_files import (
    handle_get as _handle_chat_files_get,
    init as _init_chat_files,
)
from handlers.meta_routes import (
    handle_get as _handle_meta_get,
    init as _init_meta_routes,
)
from handlers.teamlead_scope_routes import (
    handle_get as _handle_teamlead_scope_get,
    handle_post as _handle_teamlead_scope_post,
    init as _init_teamlead_scope_routes,
)
from handlers.logs_routes import (
    handle_get as _handle_logs_get,
    init as _init_logs_routes,
)
from handlers.subscriptions_routes import (
    handle_delete as _handle_subscriptions_delete,
    handle_get as _handle_subscriptions_get,
    handle_post as _handle_subscriptions_post,
    handle_put as _handle_subscriptions_put,
    init as _init_subscriptions_routes,
)
from handlers.event_subscriptions_routes import (
    handle_delete as _handle_event_subscriptions_delete,
    handle_get as _handle_event_subscriptions_get,
    handle_post as _handle_event_subscriptions_post,
    init as _init_event_subscriptions_routes,
)
from handlers.mcp_catalog_routes import (
    handle_get as _handle_mcp_catalog_get,
    handle_post as _handle_mcp_catalog_post,
    init as _init_mcp_catalog_routes,
)
from handlers.board_routes import (
    handle_delete as _handle_board_delete,
    handle_get as _handle_board_get,
    handle_post as _handle_board_post,
    handle_put as _handle_board_put,
    init as _init_board_routes,
)
from handlers.automation_routes import (
    handle_delete as _handle_automation_delete,
    handle_get as _handle_automation_get,
    handle_patch as _handle_automation_patch,
    handle_post as _handle_automation_post,
    handle_put as _handle_automation_put,
    handle_run as _handle_automation_run,
    handle_webhook as _handle_automation_webhook,
    init as _init_automation_routes,
)
from handlers.teams_routes import (
    handle_delete as _handle_teams_delete,
    handle_get as _handle_teams_get,
    handle_post as _handle_teams_post,
    handle_put as _handle_teams_put,
    init as _init_teams_routes,
)
from handlers.metrics_routes import (
    handle_get as _handle_metrics_get,
    handle_post as _handle_metrics_post,
    init as _init_metrics_routes,
)
from handlers.onboarding_routes import (
    handle_get as _handle_onboarding_get,
    handle_post as _handle_onboarding_post,
    init as _init_onboarding_routes,
)
from handlers.media_routes import (
    handle_post as _handle_media_post,
)
from handlers.system_status_routes import (
    handle_get as _handle_system_status_get,
    init as _init_system_status_routes,
)
from handlers.execution_routes import (
    handle_get as _handle_execution_get,
    handle_post as _handle_execution_post,
    init as _init_execution_routes,
)
from handlers.creator import (
    handle_get as _handle_creator_get,
    handle_post as _handle_creator_post,
)
from handlers.data import (
    handle_get as _handle_data_get,
    handle_post as _handle_data_post,
)
from handlers.domain import (
    handle_get as _handle_domain_get,
    handle_post as _handle_domain_post,
)
from handlers.credentials_routes import (
    handle_delete as _handle_credentials_delete,
    handle_get as _handle_credentials_get,
    handle_post as _handle_credentials_post,
)
from handlers.git_lock_routes import (
    handle_delete as _handle_git_lock_delete,
    handle_get as _handle_git_lock_get,
    handle_post as _handle_git_lock_post,
    init as _init_git_lock_routes,
)
from daemons.supervisor import (
    _PROCESS_SUPERVISOR_STATE,
    _SUPERVISOR_INTERVAL,
    _supervisor_check_and_restart,
    _supervisor_daemon_loop,
    _start_supervisor_daemon,
    init as _init_supervisor,
)
from daemons.health_monitor import (
    _HEALTH_MONITOR_INTERVAL,
    _HEALTH_ALERT_COOLDOWN,
    _health_prev_status,
    _health_last_alert,
    _CONTEXT_THRESHOLDS,
    _context_last_alert_level,
    _health_monitor_loop,
    _health_monitor_tick,
    _health_check_component,
    _send_health_alert,
    _check_context_thresholds,
    init as _init_health_monitor,
)
from daemons.cli_monitor import (
    _AGENT_OUTPUT_HASHES,
    _CLI_STUCK_THRESHOLD,
    _CLI_KILL_THRESHOLD,
    _CLI_CHECK_INTERVAL,
    _CLI_STUCK_ALERTED,
    _CLI_STARTUP_PROMPTS,
    _CLI_AUTH_ALERTED,
    _THINKING_PATTERNS,
    _CLI_HEARTBEAT_GRACE,
    _cli_output_monitor_loop,
    _cli_output_monitor_tick,
    init as _init_cli_monitor,
)
from daemons.rate_limit_resume import (
    _RATE_LIMIT_RESUME_INITIAL,
    _RATE_LIMIT_RESUME_MAX,
    _RATE_LIMIT_RESUME_FACTOR,
    _rate_limit_resume_loop,
    _rate_limit_resume_tick,
    init as _init_rate_limit_resume,
)
from daemons.maintenance import (
    _V3_CLEANUP_INTERVAL,
    _TASK_TIMEOUT_INTERVAL,
    _maintenance_cleanup_tick,
    _v3_cleanup_loop,
    _task_timeout_tick,
    _task_timeout_loop,
    init as _init_maintenance,
)
from daemons.heartbeat_prompt import (
    _HEARTBEAT_PROMPT_INTERVAL,
    _heartbeat_prompt_tick,
    _heartbeat_prompt_loop,
    init as _init_heartbeat_prompt,
)
from daemons.codex_hook import (
    _CODEX_HOOK_INTERVAL,
    _CODEX_HOOK_COOLDOWN,
    _CODEX_HOOK_MIN_GAP,
    _codex_hook_tick,
    _codex_hook_loop,
    init as _init_codex_hook,
)
from daemons.task_pusher import (
    _TASK_PUSH_INTERVAL,
    _task_pusher_tick,
    _idle_agent_task_pusher,
    init as _init_task_pusher,
)
from daemons.auto_assign import (
    _AUTO_ASSIGN_INTERVAL,
    _auto_assign_tick,
    _idle_watchdog_auto_assign,
    init as _init_auto_assign,
)
from daemons.buddy_knowledge import (
    _BUDDY_KNOWLEDGE_INTERVAL,
    _buddy_knowledge_tick,
    _buddy_knowledge_loop,
    _generate_buddy_knowledge,
    init as _init_buddy_knowledge,
)
from daemons.distillation import (
    _DISTILLATION_INTERVAL,
    _DISTILLATION_PROMPT,
    _distillation_tick,
    _distillation_daemon_loop,
    init as _init_distillation,
)
from daemons.auto_gen import (
    AUTO_GEN_PENDING,
    AUTO_GEN_LOCK,
    _auto_gen_tick,
    _auto_gen_watcher,
    init as _init_auto_gen,
)
from daemons.agent_health import (
    _MAX_BUSY_SECONDS,
    _CLEANUP_TTL,
    _agent_health_tick,
    _agent_health_checker,
    init as _init_agent_health,
)
from daemons.restart_wake import (
    _restart_wake_phase,
    _restart_wake_enabled,
    _delayed_restart_wake,
    _start_restart_wake_thread,
    init as _init_restart_wake,
)
from daemons.restart_control import (
    RESTART_STATE,
    RESTART_LOCK,
    _get_active_agent_ids,
    _restart_warn_phase,
    _restart_stop_phase,
    _restart_kill_phase,
    _restart_cancel,
    _restart_reset,
    _restart_force,
    _check_all_checkpoints_saved,
    init as _init_restart_control,
)
from handlers.federation import (
    _is_federation_target,
    _federation_runtime_health,
    _handle_federation_inbound,
    _init_federation_runtime,
    _stop_federation_runtime,
    _federation_send_outbound,
    init as _init_federation,
)
from handlers.workflows import (
    _WORKFLOW_TOOLS,
    WORKFLOW_REGISTRY,
    WORKFLOW_REGISTRY_LOCK,
    _load_n8n_config,
    _n8n_request,
    _save_workflow_registry,
    _load_workflow_registry,
    _register_workflow_tool,
    _restore_workflow_tools_from_registry,
    _record_workflow_deployment,
    _workflow_projection,
    _workflow_record_for_id,
    _remove_workflow_record,
    _workflow_delete_cleanup,
    _find_first_webhook_path,
    _workflow_tool_name,
    _normalize_workflow_template_variables,
    _workflow_targets_local_bridge_auth,
    _inject_bridge_workflow_auth_headers,
    _deploy_workflow_to_n8n,
    _update_workflow_in_n8n,
    _register_workflow_subscription,
    _register_workflow_webhook_tool,
    handle_delete as _handle_workflows_delete,
    handle_get as _handle_workflows_get,
    handle_patch as _handle_workflows_patch,
    handle_post as _handle_workflows_post,
    handle_put as _handle_workflows_put,
    init as _init_workflows,
)
from handlers.projects import (
    handle_get as _handle_projects_get,
    sanitize_project_name,
    _generate_claude_md,
    _generate_agents_md,
    _generate_engine_md,
    _derive_permission_allow_list,
    create_project,
    init as _init_projects,
)
from handlers.memory import (
    handle_get as _handle_memory_get,
    handle_post as _handle_memory_post,
    _safe_knowledge_segment,
    _legacy_memory_project_scope,
    _legacy_memory_knowledge_info,
    _sync_legacy_memory_note,
    _sync_legacy_episode_note,
    _legacy_shared_memory_defaults,
    _legacy_agent_default_content,
    _legacy_episode_note_path,
    _load_legacy_memory_candidates,
    migrate_legacy_agent_memory,
    _canonical_memory_note,
    _canonical_episode_entries,
    _resolve_agent_file,
    MEMORY_LOCK,
    _AGENT_FILE_MAP,
    scaffold_agent_memory,
    read_agent_memory,
    write_episode,
    write_agent_memory,
    get_memory_status,
    init as _init_memory,
)
from server_bootstrap import (
    BridgeThreadingHTTPServer,
    _is_address_in_use,
    _create_http_server_with_retry,
    _server_signal_handler,
    init as _init_server_bootstrap,
)
from server_utils import (
    utc_now_iso,
    is_within_directory,
    validate_project_path,
    resolve_team_lead_scope_file,
    ensure_parent_dir,
    parse_wait,
    parse_limit,
    parse_after_id,
    parse_bool,
    parse_non_negative_int,
    normalize_path,
    init as _init_server_utils,
)
from server_engine_models import (
    _claude_models_from_cli,
    _codex_models_from_cli,
    _gemini_models_from_cli,
    _qwen_models_from_cli,
    build_engine_model_registry,
    detect_available_engines as _detect_available_engines_impl,
    resolve_engine_model_choice,
)
from server_runtime_meta import (
    _build_explicit_runtime_layout,
    _capabilities_for_response,
    _capability_match,
    _clone_runtime_layout,
    _get_registered_agent_capabilities,
    _normalize_capability_list,
    _runtime_layout_from_profiles,
    _runtime_layout_from_state,
    _runtime_layout_is_valid,
    _runtime_pair_mode_for_layout,
    _runtime_profile_capabilities,
    _runtime_profile_for_agent,
    _runtime_profile_map_from_state,
    build_runtime_configure_payload_summary as _runtime_configure_payload_summary_impl,
    init as _init_server_runtime_meta,
    pair_mode_of,
    resolve_layout,
    resolve_runtime_specs,
)
from server_agent_state import (
    _AGENT_STATE_CACHE,
    _AGENT_STATE_CACHE_TTL,
    _agent_state_path,
    _cli_identity_bundle,
    _get_agent_home_dir,
    _load_agent_state,
    _normalize_cli_identity_path,
    _normalize_resume_id_value,
    _save_agent_state,
    init as _init_server_agent_state,
)
from server_agent_files import (
    _default_permissions,
    _toml_get_str,
    _toml_remove_key,
    _toml_set_str,
    _update_instruction_roles,
    agent_config_file,
    agent_instruction_file,
    read_agent_permissions,
    write_agent_permission,
    init as _init_server_agent_files,
)
from server_context_restore import (
    resolve_context_restore_artifacts,
    build_context_restore_message as _build_context_restore_message_impl,
    should_send_context_restore as _should_send_context_restore_impl,
    init as _init_server_context_restore,
)
from server_request_auth import (
    _extract_auth_token as _request_extract_auth_token,
    _resolve_auth_identity as _request_resolve_auth_identity,
    _require_authenticated as _request_require_authenticated,
    _require_platform_operator as _request_require_platform_operator,
    _path_requires_auth_get as _request_path_requires_auth_get,
    _path_requires_auth_post as _request_path_requires_auth_post,
    init as _init_server_request_auth,
)
from server_http_io import (
    _check_rate_limit as _http_check_rate_limit,
    _send_cors_headers as _http_send_cors_headers,
    _respond as _http_respond,
    _respond_bytes as _http_respond_bytes,
    _parse_json_body as _http_parse_json_body,
    _parse_multipart as _http_parse_multipart,
    init as _init_server_http_io,
)
from server_frontend_serve import (
    _inject_ui_token as _frontend_inject_ui_token,
    _serve_frontend_request as _frontend_serve_frontend_request,
    init as _init_server_frontend_serve,
)
from server_message_audience import (
    resolve_configured_targets as _resolve_configured_message_targets,
    resolve_live_targets as _resolve_live_message_targets,
    init as _init_server_message_audience,
)
from server_main import (
    preload_runtime_state,
    serve_http_server,
    run_server_main,
    init as _init_server_main,
)
from server_startup import (
    _is_agent_idle,
    _automation_condition_context,
    start_background_services,
    init as _init_server_startup,
)
from websocket_server import (
    WS_CLIENTS,
    ws_broadcast,
    ws_broadcast_message,
    run_websocket_server,
    init as _init_websocket_server,
)
from telephony_integration import TelephonyClient


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
MESSAGES_DIR = os.path.join(BASE_DIR, "messages")
LOG_FILE = os.path.join(MESSAGES_DIR, "bridge.jsonl")
FRONTEND_DIR = os.path.join(ROOT_DIR, "Frontend")
PID_DIR = os.path.join(BASE_DIR, "pids")
AGENT_LOG_DIR = os.path.join(BASE_DIR, "logs")
CHAT_UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
CHAT_UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10 MB per file
CHAT_UPLOAD_ALLOWED_MIME_PREFIXES = ("image/", "application/pdf", "text/plain", "application/json")
PROJECTS_BASE_DIR = os.path.expanduser("~/Desktop")
RUNTIME_TEAM_PATH = os.path.join(BASE_DIR, "runtime_team.json")
# V1 DEPRECATED — agent_client.py no longer used in V2 (tmux sessions replace subprocess agents)
# AGENT_CLIENT_FILE = os.path.join(BASE_DIR, "agent_client.py")


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_host(name: str, default: str) -> str:
    raw = str(os.environ.get(name, "")).strip()
    return raw or default


PORT = _env_int("PORT", 9111)
WS_PORT = _env_int("WS_PORT", 9112)
HTTP_HOST = _env_host("BRIDGE_HTTP_HOST", "127.0.0.1")
WS_HOST = _env_host("BRIDGE_WS_HOST", HTTP_HOST)
MAX_WAIT_SECONDS = 60.0
MAX_LIMIT = 1000
_DEFAULT_ORIGINS = [
    "http://127.0.0.1:9111", "http://127.0.0.1:8765", "http://127.0.0.1:8787",
    "http://localhost:8765", "http://localhost:8787", "http://localhost:9111",
    "http://localhost:8083", "http://127.0.0.1:8083",
    "http://localhost:8082", "http://127.0.0.1:8082",
]
_extra_origins_raw = os.environ.get("BRIDGE_ALLOWED_ORIGINS", "").strip()
if _extra_origins_raw:
    ALLOWED_ORIGINS = _DEFAULT_ORIGINS + [o.strip() for o in _extra_origins_raw.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = _DEFAULT_ORIGINS

# S9: Rate-limiting (per IP + endpoint, sliding window 60s)
RATE_LIMITER = _RateLimiter()
RATE_LIMITS: dict[str, int] = {
    "/send": 120,
    "/register": int(os.environ.get("BRIDGE_REGISTER_RATE_LIMIT", "300")),
    "/control": 30,
    "/runtime/configure": 20,
    "default": 200,
}
RATE_LIMIT_EXEMPT = {"/health", "/heartbeat"}

WORKFLOW_TEMPLATES_DIR = os.path.join(BASE_DIR, "workflow_templates")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    lowered = str(raw).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


BRIDGE_STRICT_AUTH = _env_flag("BRIDGE_STRICT_AUTH", True)
BRIDGE_USER_TOKEN = os.environ.get("BRIDGE_USER_TOKEN", "").strip()
BRIDGE_REGISTER_TOKEN = os.environ.get("BRIDGE_REGISTER_TOKEN", "").strip()
ALLOWED_APPROVAL_ACTIONS = {
    "email_send",
    "email_delete",
    "phone_call",
    "smart_home",
    "slack_send",
    "telegram_send",
    "whatsapp_send",
    "whatsapp_voice",
    "file_delete",
    "trade_execute",
    "browser_login",
    "browser_action",
}

# ---------------------------------------------------------------------------
# Telephony singleton — graceful degradation: None if keys are missing
# ---------------------------------------------------------------------------
_TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
_TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
_TWILIO_FROM = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()
_ELEVENLABS_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
_ELEVENLABS_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()

TELEPHONY_CLIENT: TelephonyClient | None = None
if _TWILIO_SID or _ELEVENLABS_KEY:
    TELEPHONY_CLIENT = TelephonyClient(
        twilio_account_sid=_TWILIO_SID,
        twilio_auth_token=_TWILIO_TOKEN,
        twilio_from_number=_TWILIO_FROM,
        elevenlabs_api_key=_ELEVENLABS_KEY,
        elevenlabs_voice_id=_ELEVENLABS_VOICE or "21m00Tcm4TlvDq8ikWAM",
    )

_HTTP_SERVER_INSTANCE: ThreadingHTTPServer | None = None
CONTROL_PLANE_PID_FILES = {
    "server.pid",
    "restart_wrapper.pid",
    "watcher.pid",
    "output_forwarder.pid",
}

# ===== Auto-Token Generation =====
# If tokens are not configured via env, auto-generate and persist.
_TOKEN_CONFIG_DIR = os.path.join(os.environ.get("HOME", "/tmp"), ".config", "bridge")
_TOKEN_CONFIG_FILE = os.path.join(_TOKEN_CONFIG_DIR, "tokens.json")
_UI_SESSION_TOKEN = ""  # Generated on startup for Frontend browser sessions


def _init_auth_tokens() -> tuple[str, str, str]:
    """Auto-generate missing auth tokens and persist to config file.

    Returns (user_token, register_token, ui_token).
    """
    os.makedirs(_TOKEN_CONFIG_DIR, mode=0o700, exist_ok=True)
    saved: dict[str, str] = {}
    if os.path.exists(_TOKEN_CONFIG_FILE):
        try:
            with open(_TOKEN_CONFIG_FILE, "r") as f:
                saved = json.load(f)
        except Exception:
            saved = {}

    user_tok = BRIDGE_USER_TOKEN or saved.get("user_token", "")
    reg_tok = BRIDGE_REGISTER_TOKEN or saved.get("register_token", "")
    ui_tok = secrets.token_hex(32)  # Always fresh per server start

    if not user_tok:
        user_tok = secrets.token_hex(32)
    if not reg_tok:
        reg_tok = secrets.token_hex(32)

    # Persist for next startup (env vars take precedence on load)
    saved["user_token"] = user_tok
    saved["register_token"] = reg_tok
    tmp = _TOKEN_CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(saved, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _TOKEN_CONFIG_FILE)
        os.chmod(_TOKEN_CONFIG_FILE, 0o600)
    except Exception as exc:
        print(f"[auth] WARNING: could not persist tokens: {exc}")

    return user_tok, reg_tok, ui_tok


BRIDGE_USER_TOKEN, BRIDGE_REGISTER_TOKEN, _UI_SESSION_TOKEN = _init_auth_tokens()

# ===== 3-TIER AUTH MODEL =====
# Tier 1 — Public (NO auth): Always accessible. Frontend + Chat need these.
# Tier 2 — Agent (Session-Token): Write-ops. Needs X-Bridge-Token from /register.
# Tier 3 — Admin (User-Token): Destructive ops. Needs BRIDGE_USER_TOKEN.
# Default: PUBLIC. Only paths explicitly in Tier 2/3 require auth.

# Tier 2: Agent auth — POST paths requiring Session-Token (or User-Token or UI-Token)
AUTH_TIER2_POST_PATHS = {
    "/send", "/activity", "/heartbeat",
    "/stream_chunk", "/task/create", "/memory/write", "/memory/scaffold",
    "/memory/episode", "/memory/migrate", "/scope/lock", "/scope/unlock",
    "/whiteboard", "/whiteboard/post",
    "/events/subscribe",
    "/workflows/compile",
    "/workflows/deploy",
    "/workflows/deploy-template",
    "/chat/upload",
    "/git/lock",
}

# Tier 3: Admin auth — POST/PATCH/DELETE paths requiring User-Token (or UI-Token)
AUTH_TIER3_POST_PATHS = {
    "/runtime/stop", "/runtime/configure", "/agents/cleanup",
    "/server/restart", "/server/restart/force", "/server/restart/cancel", "/server/restart/reset",
    "/teamlead/activate", "/teamlead/control", "/teamlead/scope",
    "/control", "/team/reload",
    "/tools/register",
    "/agents/create",
    "/mcp-catalog",
    "/system/shutdown", "/system/resume",
    "/platform/start", "/platform/stop",
}

# Tier 3 dynamic patterns (checked via regex, not exact match)
# Covers POST, PATCH, and DELETE for agent management endpoints
AUTH_TIER3_PATTERNS = [
    re.compile(r"^/agents/[^/]+/start$"),
    re.compile(r"^/agents/[^/]+/restart$"),
    re.compile(r"^/agents/[^/]+/active$"),
    re.compile(r"^/agents/[^/]+/mode$"),
    re.compile(r"^/agents/[^/]+/parent$"),
    re.compile(r"^/agents/[^/]+/avatar$"),
    re.compile(r"^/tools/[^/]+/execute$"),
    re.compile(r"^/guardrails"),               # C3: All guardrails ops admin-only
]

# Tier 2: Sensitive GET paths requiring Agent or User token in strict auth mode
AUTH_TIER2_GET_PATHS = {
    "/agents",
    "/agent/config",
    "/automations",
    "/events/subscriptions",
    "/history",
    "/logs",
    "/messages",
    "/n8n/executions",
    "/n8n/workflows",
    "/task/queue",
    "/workflows/tools",
}

# Tier 2 dynamic patterns for GET (read paths carrying sensitive operational data)
AUTH_TIER2_GET_PATTERNS = [
    re.compile(r"^/automations/[^/]+$"),
    re.compile(r"^/automations/[^/]+/history$"),
    re.compile(r"^/automations/[^/]+/history/[^/]+$"),
]

# Tier 2 dynamic patterns for PATCH/DELETE (write-ops requiring Agent or User token)
AUTH_TIER2_PATTERNS = [
    re.compile(r"^/messages/\d+/reaction$"),    # POST /messages/{id}/reaction — Chat-Daumen
    re.compile(r"^/credentials/"),             # GET/POST/DELETE /credentials/* — E1 Credential Store
    re.compile(r"^/agents/[^/]+$"),            # PATCH /agents/{id} — Agent-Builder profile update
    re.compile(r"^/agents/[^/]+/setup-home$"), # POST /agents/{id}/setup-home
    re.compile(r"^/task/[^/]+$"),             # PATCH /task/{id}, DELETE /task/{id}
    re.compile(r"^/board/projects/[^/]+$"),    # PATCH/DELETE /board/projects/{id}
    re.compile(r"^/board/projects/[^/]+/teams/[^/]+$"),  # PATCH/DELETE board teams
    re.compile(r"^/board/projects/[^/]+/teams$"),         # POST board teams
    re.compile(r"^/board/projects/[^/]+/teams/[^/]+/members$"),  # POST board members
    re.compile(r"^/board/projects/[^/]+/teams/[^/]+/members/[^/]+$"),  # DELETE members
    re.compile(r"^/subscriptions/[^/]+$"),     # PATCH/DELETE /subscriptions/{id}
    re.compile(r"^/agents/[^/]+/subscription$"),  # PUT /agents/{id}/subscription
    re.compile(r"^/teams/[^/]+$"),             # DELETE /teams/{id}
    re.compile(r"^/teams/[^/]+/members$"),     # PATCH /teams/{id}/members
    re.compile(r"^/whiteboard/[^/]+$"),        # DELETE /whiteboard/{id}
    re.compile(r"^/events/subscriptions/[^/]+$"),  # DELETE /events/subscriptions/{id}
    re.compile(r"^/workflows/[^/]+$"),             # DELETE /workflows/{id}
    re.compile(r"^/workflows/[^/]+/definition$"),  # PUT /workflows/{id}/definition
    re.compile(r"^/workflows/[^/]+/toggle$"),      # PATCH /workflows/{id}/toggle
    re.compile(r"^/automations/[^/]+$"),       # PUT/DELETE /automations/{id}
    re.compile(r"^/automations/[^/]+/active$"),   # PATCH /automations/{id}/active
    re.compile(r"^/automations/[^/]+/pause$"),    # PATCH /automations/{id}/pause
    re.compile(r"^/automations/[^/]+/run$"),      # POST /automations/{id}/run
]

# Dynamic RBAC sets — derived from team.json, refreshed on hot-reload
# Fallback values used when team.json is not loaded
_RBAC_PLATFORM_OPERATORS: set[str] = {"buddy", "viktor", "nova", "ordo", "lucy"}
_RBAC_RESTART_ALLOWED: set[str] = {"viktor", "kai", "user"}
_RBAC_SA_CREATE_ALLOWED: set[str] = {"user", "ordo"}
PLATFORM_OPERATOR_AGENTS = _RBAC_PLATFORM_OPERATORS  # alias for backward compat

# Everything else is PUBLIC (Tier 1) — including:
# GET: /health, /agents, /activity, /receive/*, /board/*, /teams/*,
#      /team/orgchart, /server/restart-status, /approval/pending
# POST: /register (special case, has its own token check)


os.makedirs(MESSAGES_DIR, exist_ok=True)
os.makedirs(PID_DIR, exist_ok=True)
os.makedirs(AGENT_LOG_DIR, exist_ok=True)
os.makedirs(CHAT_UPLOADS_DIR, exist_ok=True)
os.makedirs(PROJECTS_BASE_DIR, exist_ok=True)


import shutil

import mcp_catalog
from tmux_manager import (
    consume_agent_start_failure,
    create_agent_session,
    interrupt_agent,
    interrupt_all_agents,
    kill_agent_session,
    list_agent_sessions,
    is_session_alive,
    send_to_session,
    set_session_name_overrides as _set_tmux_session_overrides,
    _deploy_agent_skills,
    _session_name_for,
    _write_agent_runtime_config,
)

# Auto-detect installed CLIs (live, not cached)
KNOWN_ENGINES = runtime_layout.KNOWN_ENGINES

# Static fallback model registry per engine.
#
# The live source of truth for wrapped CLIs is derived below from the locally
# installed CLIs and their configs/caches. These values are only used when a
# CLI-specific source is unavailable.
ENGINE_MODELS: dict[str, dict] = {
    "claude": {
        "models": [
            {"id": "claude-opus-4-6", "alias": "opus", "label": "Opus 4.6", "default": True},
            {"id": "claude-sonnet-4-6", "alias": "sonnet", "label": "Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "alias": "haiku", "label": "Haiku 4.5"},
        ],
        "cli_flag": "--model",
    },
    "codex": {
        "models": [
            {"id": "gpt-5.4", "label": "gpt-5.4", "default": True},
            {"id": "gpt-5.3-codex", "label": "gpt-5.3-codex"},
            {"id": "gpt-5.2-codex", "label": "gpt-5.2-codex"},
            {"id": "o3", "label": "o3"},
        ],
        "cli_flag": "-m",
    },
    "gemini": {
        "models": [
            {"id": "auto-gemini-3", "label": "Auto (Gemini 3)", "default": True},
            {"id": "auto-gemini-2.5", "label": "Auto (Gemini 2.5)"},
            {"id": "gemini-2.5-pro", "label": "gemini-2.5-pro"},
            {"id": "gemini-2.5-flash", "label": "gemini-2.5-flash"},
            {"id": "gemini-2.5-flash-lite", "label": "gemini-2.5-flash-lite"},
        ],
        "cli_flag": "-m",
    },
    "qwen": {
        "models": [
            {"id": "coder-model", "label": "Qwen 3.5 Plus", "default": True},
        ],
        "cli_flag": "-m",
    },
}

def _resolve_engine_model_choice(engine: str, model_id: str) -> str | None:
    return resolve_engine_model_choice(engine, model_id, _engine_model_registry())


def _engine_model_registry() -> dict[str, dict[str, Any]]:
    return build_engine_model_registry(
        engine_models=ENGINE_MODELS,
        detect_available_engines_fn=_detect_available_engines,
        claude_models_from_cli_fn=_claude_models_from_cli,
        codex_models_from_cli_fn=_codex_models_from_cli,
        gemini_models_from_cli_fn=_gemini_models_from_cli,
        qwen_models_from_cli_fn=_qwen_models_from_cli,
    )


def _detect_available_engines() -> set[str]:
    """Probe system PATH for known CLI binaries. Called on each request so
    newly installed/removed CLIs are picked up without server restart."""
    return _detect_available_engines_impl(set(KNOWN_ENGINES))


# Keep module-level reference for backwards compat (used by CONFIG_ENGINES etc.)
AVAILABLE_ENGINES: set[str] = _detect_available_engines()


# ── Evidenz-Enforcement (M3) ──────────────────────────────────────────
EVIDENCE_WARN_WORDS = {
    "vermutlich", "wahrscheinlich", "moeglicherweise", "eventuell",
    "ich denke", "ich glaube", "probably", "maybe", "perhaps",
    "i think", "i believe", "might be", "could be",
}


def known_agent_names() -> set[str]:
    """Discover all agent names by scanning PID directory for .pid files.

    Also includes names from the current RUNTIME layout so that agents
    started in this session are always covered even if their PID file
    was already removed.
    """
    names: set[str] = set()

    # 1. Scan PID directory (catches all agents that ever wrote a PID file)
    if os.path.isdir(PID_DIR):
        for entry in os.listdir(PID_DIR):
            if entry.endswith(".pid") and entry not in CONTROL_PLANE_PID_FILES:
                names.add(entry.removesuffix(".pid"))

    # 2. Include agents from current RUNTIME config
    with RUNTIME_LOCK:
        for agent in RUNTIME.get("agents", []):
            name = agent.get("name", "")
            if name:
                names.add(name)

    return names


MESSAGES: list[dict[str, Any]] = []
CURSORS: dict[str, int] = {}
_MSG_ID_COUNTER: int = 0  # Monotonically increasing, survives MESSAGES truncation
AGENT_LAST_SEEN: dict[str, float] = {}   # agent_id → time.time() of last /receive/ poll
AGENT_BUSY: dict[str, bool] = {}          # agent_id → True while processing (between recv and send)
REGISTERED_AGENTS: dict[str, dict] = {}   # agent_id → {role, capabilities, registered_at, last_heartbeat}
AGENT_ACTIVITIES: dict[str, dict] = {}    # agent_id → {action, target, description, timestamp}
SESSION_TOKENS: dict[str, str] = {}       # token → agent_id  (S5: anti-impersonation)
AGENT_TOKENS: dict[str, str] = {}         # agent_id → token   (S5: reverse lookup)
# Hardening: Session-Nonce tracking + CONTEXT RESTORE cooldown
AGENT_NONCES: dict[str, str] = {}         # agent_id → session_nonce (from MCP process)
AGENT_LAST_CONTEXT_RESTORE: dict[str, float] = {}  # agent_id → timestamp of last CONTEXT RESTORE

# Rate-Limit Protection: Agents that hit API usage limits
AGENT_RATE_LIMITED: dict[str, dict] = {}  # agent_id → {since: float, last_resume_attempt: float, resume_attempts: int}
_RATE_LIMIT_PATTERNS = (
    "usage limit", "rate limit", "quota exceeded",
    "too many requests", "overloaded_error",
    "exceeded your", "api error: 529", "error 529",
    "429 too many", "rate_limit_error",
)
_RATE_LIMIT_RESUME_INITIAL = 1800    # 30 min initial check
_RATE_LIMIT_RESUME_MAX = 14400       # 4h max backoff
_RATE_LIMIT_RESUME_FACTOR = 2        # exponential backoff factor

# System status: tracks shutdown/resume state
_SYSTEM_STATUS: dict[str, Any] = {
    "shutdown_active": False,
    "shutdown_since": None,
    "shutdown_by": None,
    "shutdown_reason": None,
}
# Graceful shutdown state (separate from _SYSTEM_STATUS to avoid race conditions)
_GRACEFUL_SHUTDOWN: dict[str, Any] = {
    "pending": False,
    "timeout_seconds": 30,
    "started_at": None,
    "acked_agents": [],       # agent_ids that sent [SHUTDOWN_ACK]
    "expected_agents": [],    # online agents at time of shutdown
    "finalized": False,
}
_GRACEFUL_SHUTDOWN_LOCK = threading.Lock()
_GRACEFUL_SHUTDOWN_TIMER: threading.Timer | None = None


CONTEXT_RESTORE_COOLDOWN = 300            # 5 minutes minimum between CONTEXT RESTOREs per agent
# Hardening (H1): Grace period for old tokens during re-registration
GRACE_TOKENS: dict[str, tuple[str, float]] = {}  # old_token → (agent_id, expiry_timestamp)
TOKEN_GRACE_SECONDS = 30                  # Old token stays valid for 30s after re-registration
LOCK = threading.Lock()
COND = threading.Condition(LOCK)
RUNTIME_LOCK = threading.Lock()
AGENT_STATE_LOCK = threading.Lock()  # Guards _PREV_AGENT_STATUS, AGENT_BUSY, AGENT_LAST_SEEN, REGISTERED_AGENTS, SESSION_TOKENS, AGENT_TOKENS, AGENT_RATE_LIMITED
TEAM_CONFIG_LOCK = threading.Lock()  # Guards TEAM_CONFIG writes to team.json
START_TS = time.time()
HTTP_REQUEST_QUEUE_SIZE = max(32, int(os.environ.get("BRIDGE_HTTP_REQUEST_QUEUE_SIZE", "256")))


# ===== STRUCTURED TASK PROTOCOL (Codex-Architektur Phase 3) =====
# In-memory task store. Thread-safe via TASK_LOCK.
# Lifecycle: created → claimed → acked → done | failed
# Spec: docs/CODEX_BRIDGE_ARCHITEKTUR.md
TASKS: dict[str, dict[str, Any]] = {}       # task_id → task object
TASK_LOCK = threading.Lock()
VALID_TASK_TYPES = {"code_change", "review", "test", "research", "general", "task"}
VALID_TASK_PRIORITIES = {1, 2, 3}  # 1=normal, 2=high, 3=critical
TASK_TITLE_MAX_LEN = 120
TASK_LABEL_MAX_COUNT = 10
TASK_LABEL_MAX_LEN = 30
TASK_DEFAULT_ACK_DEADLINE = 300  # seconds (increased from 120 — agents may be mid-task)
TASK_DEFAULT_MAX_RETRIES = 2
# Phase 4: Observability
VALID_RESULT_CODES = {"success", "partial", "skipped", "error", "timeout"}
TASK_BACKLOG_WARN_THRESHOLD = 5  # Alert if agent has >= N active tasks
TASK_MAX_ACTIVE_PER_AGENT = 3
RUNTIME_CONFIGURE_AUDIT_LOG = os.path.join(AGENT_LOG_DIR, "runtime_configure_audit.jsonl")


# ===== V3 SCOPE-LOCKS (T2) =====
# File/directory-level locks to prevent conflicting edits.
# Design: V3_TASK_ARCHITECTURE.md
SCOPE_LOCKS: dict[str, dict[str, Any]] = {}    # normalized_path → lock info
SCOPE_LOCK_LOCK = threading.Lock()              # meta-lock for SCOPE_LOCKS


# ===== V3 SHARED WHITEBOARD / LIVE-BOARD (T4) =====
# Central status board: agents post status updates, UI shows real-time overview.
# Design: V3_TASK_ARCHITECTURE.md + Nova V3_LIVEBOARD_WIREFRAME.md
WHITEBOARD: dict[str, dict[str, Any]] = {}   # entry_id → entry
WHITEBOARD_LOCK = threading.Lock()
WHITEBOARD_VALID_TYPES = {"status", "blocker", "result", "alert", "escalation_response"}
CLI_SETUP_STATE_LOCK = threading.Lock()
CLI_SETUP_STATE_INFLIGHT: threading.Event | None = None
CLI_SETUP_STATE_CACHE: dict[str, Any] | None = None
CLI_SETUP_STATE_CACHE_AT = 0.0
CLI_SETUP_STATE_CACHE_TTL_SECONDS = 30.0


# ESCALATION_STATE and ESCALATION_LOCK are re-imported from handlers.tasks






def _runtime_configure_payload_summary(data: dict[str, Any]) -> dict[str, Any]:
    return _runtime_configure_payload_summary_impl(data)


def _append_runtime_configure_audit(
    event: str,
    request_meta: dict[str, Any],
    payload_summary: dict[str, Any],
    outcome: dict[str, Any] | None = None,
) -> None:
    """Append a JSONL line for runtime.configure calls so runtime changes remain attributable."""
    entry: dict[str, Any] = {
        "ts": utc_now_iso(),
        "event": event,
        "request": request_meta,
        "payload": payload_summary,
    }
    if outcome:
        entry["outcome"] = outcome
    try:
        with open(RUNTIME_CONFIGURE_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

# ===== AGENT STATE STORE (Kontext-Persistenz Phase 1) =====
# Persistent agent state on disk: agent_state/{agent_id}.json
# Auto-saved on /activity, /send; auto-restored on /register.
AGENT_STATE_DIR = os.path.join(BASE_DIR, "agent_state")
os.makedirs(AGENT_STATE_DIR, exist_ok=True)
_AGENT_STATE_WRITE_LOCK = threading.Lock()


_build_context_restore_message = _build_context_restore_message_impl
_should_send_context_restore = _should_send_context_restore_impl
_resolve_context_restore_artifacts = resolve_context_restore_artifacts


RUNTIME: dict[str, Any] = {
    "pair_mode": "codex-claude",
    "agent_a_engine": "codex",
    "agent_b_engine": "claude",
    "project_name": "",
    "project_path": ROOT_DIR,
    "allow_peer_auto": False,
    "peer_auto_require_flag": True,
    "max_peer_hops": 20,
    "max_turns": 0,
    "process_all": False,
    "keep_history": False,
    "timeout": 90,
    "team_lead_timeout": 300,
    "team_lead_enabled": False,
    "team_lead_max_peer_messages": 40,
    "team_lead_cli_enabled": False,
    "team_lead_engine": "codex",
    "team_lead_scope_file": os.path.join(ROOT_DIR, "teamlead.md"),
    "agent_profiles": [],
    "runtime_specs": [],
    "runtime_overlay": None,
    "last_start_at": None,
}


def _restore_receive_cursor_from_state(agent_id: str, state: dict[str, Any]) -> None:
    """Restore an agent's unread cursor from persisted message state.

    Persisted agent state tracks the last delivered message ID, while the live
    queue uses list indices. On manual restart/re-register we need to rebuild
    that index to avoid replaying the full history.

    Explicit runtime keep_history sessions remain authoritative and must not be
    overridden by persisted state.
    """
    if agent_id in current_runtime_agent_ids() and bool(RUNTIME.get("keep_history", False)):
        return

    restored_cursor = cursor_index_after_message_id(state.get("last_message_id_received"))
    if restored_cursor is None:
        return

    with COND:
        current_cursor = CURSORS.get(agent_id)
        if current_cursor is None or restored_cursor > current_cursor:
            CURSORS[agent_id] = restored_cursor
            print(
                f"[register] Restored receive cursor for {agent_id}: "
                f"{current_cursor!r} -> {restored_cursor} "
                f"(last_message_id_received={state.get('last_message_id_received')})"
            )

TEAM_LEAD_ID = "teamlead"
TEAM_LEAD_SCOPE_PATTERNS = [
    re.compile(r"\bscope[_ -]?done\b", re.IGNORECASE),
    re.compile(r"\bscope[_ -]?complete\b", re.IGNORECASE),
    re.compile(r"\bgoal[_ -]?reached\b", re.IGNORECASE),
    re.compile(r"\bmilestone[_ -]?reached\b", re.IGNORECASE),
    re.compile(r"\bziel[_ -]?erreicht\b", re.IGNORECASE),
    re.compile(r"\baufgabe[_ -]?abgeschlossen\b", re.IGNORECASE),
]
TEAM_LEAD_LOCK = threading.Lock()
TEAM_LEAD_STATE: dict[str, Any] = {
    "active": False,
    "stopped": False,
    "kickoff_id": None,
    "kickoff_to": "",
    "peer_count": 0,
    "stop_reason": "",
    "last_event_at": None,
}

# ── Git Advisory Locks (RB2: Multi-User Collaboration) ──
# Delegates to git_collaboration.py to avoid format split-brain.
#
# THREAT MODEL (Lock Enforcement):
#   Layer 1: MCP tools (bridge_git_push) — enforced via _agent_id from registration
#   Layer 2: HTTP endpoints (/git/lock) — identity binding via X-Bridge-Agent header
#            Added to AUTH_TIER2_POST_PATHS for session auth when BRIDGE_STRICT_AUTH=true
#   Layer 3: Git pre-push hook — blocks raw 'git push' when branch is locked
#            Install via git_collaboration.install_pre_push_hook() or bridge_git_hook_install MCP tool
#   Tradeoffs:
#   - Layer 3 is best-effort: hook can be bypassed with --no-verify or by removing the hook file
#   - Without BRIDGE_STRICT_AUTH, Layer 2 relies on honor-system for X-Bridge-Agent header
#   - Full enforcement would require a server-side pre-receive hook on the remote repo (out of scope for local setup)
_GIT_LOCKS_FILE = os.path.join(os.path.dirname(__file__), "data", "git_locks.json")

try:
    from git_collaboration import acquire_lock as _gc_acquire_lock
    from git_collaboration import release_lock as _gc_release_lock
    from git_collaboration import _load_locks as _gc_load_locks
    from git_collaboration import _save_locks as _gc_save_locks
except ImportError:
    _gc_acquire_lock = None  # type: ignore[assignment]
    _gc_release_lock = None  # type: ignore[assignment]
    _gc_load_locks = None  # type: ignore[assignment]
    _gc_save_locks = None  # type: ignore[assignment]

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _all_tmux_agent_ids() -> set[str]:
    """Return all agent IDs for active acw_* and overridden tmux sessions."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return set()
        live_sessions = set(result.stdout.strip().splitlines())
        ids: set[str] = set()
        # Standard acw_ prefix sessions
        for sn in live_sessions:
            if sn.startswith("acw_") and len(sn) > 4:
                ids.add(sn[4:])
        # Overridden sessions (e.g. bb_alpha_lead)
        for aid, override_sn in _SESSION_NAME_MAP.items():
            if override_sn in live_sessions:
                ids.add(aid)
        return ids
    except Exception:
        return set()


def _load_agents_conf() -> dict[str, dict[str, str]]:
    """Parse agents.conf and return agent start metadata by agent_id."""
    conf_candidates = [
        os.path.join(ROOT_DIR, "agents.conf"),
        os.path.join(BASE_DIR, "agents.conf"),
    ]
    conf_path = next((p for p in conf_candidates if os.path.exists(p)), "")
    if not conf_path:
        return {}

    agents: dict[str, dict[str, str]] = {}
    try:
        with open(conf_path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":", maxsplit=4)
                if len(parts) < 3:
                    continue
                agent_id = parts[0].strip()
                if not agent_id:
                    continue
                agents[agent_id] = {
                    "engine": parts[1].strip() if len(parts) > 1 else "claude",
                    "home_dir": parts[2].strip() if len(parts) > 2 else "",
                    "prompt_file": parts[3].strip() if len(parts) > 3 else "",
                    "session_name": parts[4].strip() if len(parts) > 4 else "",
                }
    except Exception:
        return {}
    return agents


def _agents_conf_ids() -> set[str]:
    """Return agent IDs declared in agents.conf."""
    return set(_load_agents_conf().keys())


def _configured_agent_ids() -> set[str]:
    """Return agent IDs declared in team.json or legacy agents.conf."""
    team_ids: set[str] = set()
    with TEAM_CONFIG_LOCK:
        if TEAM_CONFIG:
            for agent in TEAM_CONFIG.get("agents", []):
                agent_id = str(agent.get("id", "")).strip()
                if agent_id:
                    team_ids.add(agent_id)
    return team_ids | _agents_conf_ids()


def _team_config_snapshot() -> dict[str, Any] | None:
    with TEAM_CONFIG_LOCK:
        return json.loads(json.dumps(TEAM_CONFIG)) if TEAM_CONFIG else None


# Session name overrides: agent_id -> tmux session name (e.g. "alpha_lead" -> "bb_alpha_lead")
_SESSION_NAME_MAP: dict[str, str] = {}


def _build_session_name_map() -> None:
    """Build session name map from agents.conf + team.json and propagate to tmux_manager."""
    global _SESSION_NAME_MAP  # noqa: PLW0603
    m: dict[str, str] = {}
    # From agents.conf
    for aid, meta in _load_agents_conf().items():
        sn = meta.get("session_name", "").strip()
        if sn:
            m[aid] = sn
    _SESSION_NAME_MAP = m
    # Propagate to tmux_manager so is_session_alive/kill/list use correct names
    _set_tmux_session_overrides(m)
    if m:
        print(f"[server] session name overrides: {m}")


def _tmux_session_for(agent_id: str) -> str:
    """Return the tmux session name for an agent, respecting overrides."""
    return _SESSION_NAME_MAP.get(agent_id, f"acw_{agent_id}")


def _tmux_session_name_exists(session_name: str) -> bool:
    """Check whether a concrete tmux session name currently exists."""
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _forwarder_aliases(agent_conf: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for raw in agent_conf.get("aliases", []):
        alias = str(raw).strip().lower()
        if alias:
            values.add(alias)
    return values


def _resolve_forwarder_session_name() -> str:
    """Resolve the canonical forwarder tmux session from env/team.json."""
    explicit = str(os.environ.get("FORWARDER_SESSION", "")).strip()
    if explicit:
        return explicit

    with TEAM_CONFIG_LOCK:
        agents = list(TEAM_CONFIG.get("agents", [])) if TEAM_CONFIG else []

    for agent_conf in agents:
        if not bool(agent_conf.get("active", False)):
            continue
        agent_id = str(agent_conf.get("id", "")).strip()
        if not agent_id:
            continue
        role = str(agent_conf.get("role", "")).strip().lower()
        aliases = _forwarder_aliases(agent_conf)
        if role == "manager" or {"manager", "projektleiter", "teamlead"} & aliases:
            return _tmux_session_for(agent_id)

    for agent_conf in agents:
        if not bool(agent_conf.get("active", False)):
            continue
        agent_id = str(agent_conf.get("id", "")).strip()
        if not agent_id or agent_id == "user":
            continue
        try:
            level_value = int(agent_conf.get("level", 99))
        except (TypeError, ValueError):
            continue
        if level_value <= 1:
            return _tmux_session_for(agent_id)

    return "acw_manager"


def _team_members_for(agent_id: str) -> list[dict[str, str]]:
    """Read team members from team.json for the given agent's team."""
    with TEAM_CONFIG_LOCK:
        if not TEAM_CONFIG:
            return []
        agents = TEAM_CONFIG.get("agents", [])
    # Find this agent's team
    my_team = ""
    for a in agents:
        if a.get("id") == agent_id:
            my_team = str(a.get("team", "")).strip()
            break
    if not my_team:
        return []
    # Collect all agents in same team (excluding self)
    members = []
    for a in agents:
        aid = a.get("id", "")
        if aid and aid != agent_id and str(a.get("team", "")).strip() == my_team:
            members.append({"id": aid, "role": str(a.get("description", aid)).strip()})
    return members


def _role_description_for(agent_conf: dict, fallback: str = "") -> str:
    """Extract role_description from team.json agent config."""
    return str(agent_conf.get("description", agent_conf.get("role_description", fallback))).strip() or fallback


def _start_agent_from_conf(agent_id: str) -> bool:
    """Start an agent from team.json agents[] (migrated from agents.conf)."""
    # Read agent config under lock to prevent race with config_dir changes
    agent_conf = None
    with TEAM_CONFIG_LOCK:
        if TEAM_CONFIG:
            for a in TEAM_CONFIG.get("agents", []):
                if a.get("id") == agent_id:
                    agent_conf = dict(a)  # shallow copy under lock
                    break

    if agent_conf:
        home_dir = str(agent_conf.get("home_dir", "")).strip()
        engine = str(agent_conf.get("engine", "claude")).strip() or "claude"
        prompt_file = str(agent_conf.get("prompt_file", "")).strip()
        config_dir = str(agent_conf.get("config_dir", "")).strip()
        source = "team.json"
    else:
        # Fallback: agents.conf (deprecated — will be removed after full migration)
        conf = _load_agents_conf().get(agent_id)
        if not conf:
            return False
        home_dir = str(conf.get("home_dir", "")).strip()
        engine = str(conf.get("engine", "claude")).strip() or "claude"
        prompt_file = str(conf.get("prompt_file", "")).strip()
        config_dir = str(conf.get("config_dir", "")).strip()
        source = "agents.conf"

    if not home_dir:
        print(f"[start] missing home_dir in {source} for {agent_id}")
        return False

    # Prevent double .agent_sessions nesting:
    # If home_dir is already .agent_sessions/{agent_id}, use grandparent as project_path
    home_path = Path(home_dir)
    if home_path.parent.name == ".agent_sessions" and home_path.name == agent_id:
        project_path = str(home_path.parent.parent)
    else:
        project_path = home_dir

    prompt = "Lies deine Dokumentation. Registriere dich via bridge_register."
    if prompt_file and os.path.exists(prompt_file):
        try:
            with open(prompt_file, encoding="utf-8") as fh:
                content = fh.read().strip()
            if content:
                prompt = content
        except Exception:
            pass

    # Hardening (C4): Use description from team.json as role, not agent_id
    _ac = agent_conf or {}
    agent_role = str(_ac.get("description", agent_id)).strip() or agent_id
    agent_mcp_servers = str(_ac.get("mcp_servers", "")).strip()
    agent_model = str(_ac.get("model", "")).strip()
    agent_role_desc = _role_description_for(_ac, fallback=agent_role)
    agent_team_members = _team_members_for(agent_id)
    success = create_agent_session(
        agent_id=agent_id,
        role=agent_role,
        project_path=project_path,
        team_members=agent_team_members,
        engine=engine,
        bridge_port=PORT,
        role_description=agent_role_desc,
        config_dir=config_dir,
        mcp_servers=agent_mcp_servers,
        model=agent_model,
        permissions=_ac.get("permissions"),
        scope=_ac.get("scope"),
        report_recipient=str(_ac.get("reports_to", "")).strip(),
        initial_prompt=prompt,
    )
    if success:
        print(f"[start] Started from {source}: {agent_id} ({engine}){' [sub2]' if config_dir else ''}")
    else:
        print(f"[start] Failed start from {source}: {agent_id} ({engine})")
    return success


def current_pair_agent_ids() -> list[str]:
    with RUNTIME_LOCK:
        agent_a_engine = str(RUNTIME.get("agent_a_engine", "codex"))
        agent_b_engine = str(RUNTIME.get("agent_b_engine", "claude"))
    try:
        layout = resolve_layout(agent_a_engine, agent_b_engine)
    except ValueError:
        layout = resolve_layout("codex", "claude")
    return [spec["id"] for spec in layout]


def contains_scope_done_marker(content: str) -> bool:
    compact = " ".join(str(content).split())
    if not compact:
        return False
    return any(pattern.search(compact) for pattern in TEAM_LEAD_SCOPE_PATTERNS)


def maybe_team_lead_intervene(trigger_msg: dict[str, Any]) -> dict[str, Any] | None:
    with RUNTIME_LOCK:
        enabled = bool(RUNTIME.get("team_lead_enabled", False))
        raw_max_peer = RUNTIME.get("team_lead_max_peer_messages", 0)
    try:
        max_peer_messages = int(raw_max_peer)
    except (TypeError, ValueError):
        max_peer_messages = 0
    if not enabled:
        return None

    agent_ids = set(current_pair_agent_ids())
    sender = str(trigger_msg.get("from", "")).strip()
    recipient = str(trigger_msg.get("to", "")).strip()
    content = str(trigger_msg.get("content", "")).strip()
    msg_id = trigger_msg.get("id")
    meta = trigger_msg.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    control = str(meta_dict.get("control", "")).strip().lower()
    route_to_peer = bool(meta_dict.get("route_to_peer"))
    auto_chain = bool(meta_dict.get("auto_chain"))

    with TEAM_LEAD_LOCK:
        if control == "stop_loop":
            TEAM_LEAD_STATE["active"] = False
            TEAM_LEAD_STATE["stopped"] = True
            TEAM_LEAD_STATE["stop_reason"] = f"external-stop:{sender or 'unknown'}"
            TEAM_LEAD_STATE["last_event_at"] = utc_now_iso()
            return None

        if sender == TEAM_LEAD_ID:
            return None

        if sender == "user" and recipient in agent_ids and route_to_peer:
            TEAM_LEAD_STATE.update(
                {
                    "active": True,
                    "stopped": False,
                    "kickoff_id": msg_id,
                    "kickoff_to": recipient,
                    "peer_count": 0,
                    "stop_reason": "",
                    "last_event_at": utc_now_iso(),
                }
            )
            return None

        if not TEAM_LEAD_STATE.get("active", False) or TEAM_LEAD_STATE.get("stopped", False):
            return None

        if sender not in agent_ids or recipient not in agent_ids:
            return None

        if not auto_chain:
            return None

        TEAM_LEAD_STATE["peer_count"] = int(TEAM_LEAD_STATE.get("peer_count", 0)) + 1
        TEAM_LEAD_STATE["last_event_at"] = utc_now_iso()
        peer_count = int(TEAM_LEAD_STATE["peer_count"])

        stop_reason = ""
        if contains_scope_done_marker(content):
            stop_reason = "scope_marker"
        elif max_peer_messages > 0 and peer_count >= max_peer_messages:
            stop_reason = "max_peer_messages"

        if not stop_reason:
            return None

        TEAM_LEAD_STATE["active"] = False
        TEAM_LEAD_STATE["stopped"] = True
        TEAM_LEAD_STATE["stop_reason"] = stop_reason

    stop_text = (
        f"TEAMLEAD STOP: {stop_reason} ausgelöst "
        f"(peer_messages={peer_count}, trigger_id={msg_id})."
    )
    return {
        "from": TEAM_LEAD_ID,
        "to": "all",
        "content": stop_text,
        "meta": {
            "control": "stop_loop",
            "source": TEAM_LEAD_ID,
            "reason": stop_reason,
            "peer_messages": peer_count,
            "trigger_id": msg_id,
        },
    }



# --- team.json: Single Source of Truth ---
TEAM_CONFIG: dict[str, Any] | None = None  # Loaded at startup
TEAM_JSON_PATH = os.path.join(BASE_DIR, "team.json")


def load_team_config() -> dict[str, Any] | None:
    """Load team.json with auto-migration v2 → v3."""
    if not os.path.exists(TEAM_JSON_PATH):
        return None
    try:
        with open(TEAM_JSON_PATH) as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[team] Failed to load team.json: {exc}")
        return None

    def _persist_loaded_config(payload: dict[str, Any], reason: str) -> None:
        try:
            migrated = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(TEAM_JSON_PATH), suffix=".tmp"
            )
            try:
                os.write(fd, migrated.encode("utf-8"))
                os.close(fd)
                os.replace(tmp, TEAM_JSON_PATH)
                print(f"[team] {reason} persisted")
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as exc:
            print(f"[team] {reason} persist failed (in-memory OK): {exc}")

    version = data.get("version", 1)
    if version < 3:
        print(f"[team] Auto-migrating team.json v{version} → v3")
        data["version"] = 3
        # Add projects[] if missing
        data.setdefault("projects", [])
        # Add agent_md and description defaults
        for agent in data.get("agents", []):
            agent.setdefault("agent_md", "")
            agent.setdefault("description", "")
        # Persist migration atomically
        _persist_loaded_config(data, "v3 migration")

    # Subscription metadata is now loaded as declared configuration.
    # Bridge must not enrich Claude subscription/account fields from local
    # consumer credential files such as .claude.json or .credentials.json.

    # Strip legacy account truth from previously auto-detected non-Claude profiles.
    # These values were historically derived from local auth files and should not
    # remain persisted as product truth in team.json.
    def _provider_for_loaded_subscription(sub_path: str, provider: str = "") -> str:
        explicit = str(provider or "").strip().lower()
        if explicit:
            return explicit
        path_text = str(sub_path or "").strip().rstrip("/")
        if not path_text:
            return ""
        base = os.path.basename(path_text).lower()
        if base.startswith(".claude"):
            return "claude"
        if base == ".codex":
            return "openai"
        if base == ".gemini":
            return "gemini"
        if base == ".qwen":
            return "qwen"
        return ""

    detected_profile_fields = (
        "email",
        "plan",
        "billing_type",
        "display_name",
        "account_created_at",
        "rate_limit_tier",
    )
    detected_profile_sanitized = False
    for sub in data.get("subscriptions", []):
        provider = _provider_for_loaded_subscription(sub.get("path", ""), sub.get("provider", ""))
        if not sub.get("_detected") or provider not in {"openai", "gemini", "qwen"}:
            continue
        for field in detected_profile_fields:
            if field in sub:
                sub.pop(field, None)
                detected_profile_sanitized = True
    if detected_profile_sanitized:
        _persist_loaded_config(data, "detected profile sanitization")

    # ----- Auto-scan external provider profiles -----
    # W10/W11 follow-up: detected subscriptions must be profile-presence based only.
    # Bridge must not inspect provider auth/account files such as:
    # - ~/.codex/auth.json
    # - ~/.gemini/google_accounts.json
    # - ~/.qwen/oauth_creds.json
    home = os.path.expanduser("~")
    detected_ids = {s.get("id") for s in data.get("subscriptions", [])}
    detected_profiles = (
        ("codex", "Codex", "openai", os.path.join(home, ".codex")),
        ("gemini", "Gemini", "gemini", os.path.join(home, ".gemini")),
        ("qwen", "Qwen", "qwen", os.path.join(home, ".qwen")),
    )
    for sub_id, name, provider, profile_path in detected_profiles:
        if sub_id in detected_ids:
            continue
        if not os.path.isdir(profile_path):
            continue
        data.setdefault("subscriptions", []).append(
            {
                "id": sub_id,
                "name": name,
                "provider": provider,
                "path": profile_path,
                "active": True,
                "_detected": True,
            }
        )
        print(f"[team] Auto-detected {name} profile: {profile_path}")

    return data


def _atomic_write_team_json() -> None:
    """Atomically persist TEAM_CONFIG to team.json (temp-file + os.replace).

    Must be called while holding TEAM_CONFIG_LOCK.
    """
    data = json.dumps(TEAM_CONFIG, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(TEAM_JSON_PATH), suffix=".tmp"
    )
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, TEAM_JSON_PATH)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _notify_team_change(
    change_type: str,
    details: str,
    affected_agents: list[str] | None = None,
) -> None:
    """Send targeted team-change notifications AFTER releasing TEAM_CONFIG_LOCK.

    Must be called OUTSIDE of TEAM_CONFIG_LOCK to respect lock ordering.

    change_type: agent_added, agent_removed, role_changed, team_changed,
                 scope_changed, skills_changed, subscription_changed, team_created,
                 team_deleted, team_members_changed
    affected_agents: list of agent_ids to notify. If None, notifies all registered agents.
    """
    content = f"[TEAM UPDATE] {change_type}: {details}"
    if affected_agents:
        for aid in affected_agents:
            if aid in REGISTERED_AGENTS:
                append_message("system", aid, content,
                               meta={"type": "team_change", "change_type": change_type})
    else:
        # Notify all registered agents
        for aid in list(REGISTERED_AGENTS):
            append_message("system", aid, content,
                           meta={"type": "team_change", "change_type": change_type})


def derive_aliases(team: dict[str, Any]) -> dict[str, str]:
    """Derive AGENT_ID_ALIASES from team.json aliases fields."""
    return shared_derive_aliases(team)


def derive_allowed_routes(team: dict[str, Any]) -> dict[str, set[str]]:
    """Derive hierarchy routes without team-route expansion (legacy helper)."""
    return shared_derive_routes(team, include_team_routes=False)


def derive_routes(team: dict[str, Any]) -> dict[str, set[str]]:
    """Derive unified runtime routes (hierarchy + team routes)."""
    return shared_derive_routes(team)


def derive_team_routes(team_config: dict[str, Any]) -> dict[str, set[str]]:
    """Derive intra-team routes from team definitions."""
    return shared_derive_team_routes(team_config)


def get_team_members(team_id: str) -> set[str]:
    """Return all members (including lead) for a given team ID."""
    if TEAM_CONFIG is None:
        return set()
    for team in TEAM_CONFIG.get("teams", []):
        if team.get("id") == team_id:
            members = set(team.get("members", []))
            lead = team.get("lead", "")
            if lead:
                members.add(lead)
            return members
    return set()


# --- Agent ID Aliases (defaults, overridden by team.json at startup) ---
# Canonical resolution: alternative names → registered bridge-ID
AGENT_ID_ALIASES: dict[str, str] = {
    "manager": "ordo",
    "projektleiter": "ordo",
    "teamlead": "ordo",
}

def _hot_reload_team_config() -> dict[str, Any] | None:
    """Hot-reload team.json into global TEAM_CONFIG. Returns result dict or None on error."""
    global TEAM_CONFIG  # noqa: PLW0603
    new_config = load_team_config()
    if new_config is None:
        return None
    old_count = len(TEAM_CONFIG.get("agents", [])) if TEAM_CONFIG else 0
    TEAM_CONFIG = new_config
    new_count = len(TEAM_CONFIG.get("agents", []))
    new_aliases = derive_aliases(TEAM_CONFIG)
    if new_aliases:
        AGENT_ID_ALIASES.update(new_aliases)
    board_api.init_team_backend(TEAM_CONFIG, TEAM_CONFIG_LOCK, _atomic_write_team_json)
    _build_session_name_map()
    print(f"[team] team.json hot-reloaded: {old_count} → {new_count} agents")
    _derive_rbac_sets()
    return {"ok": True, "agents_before": old_count, "agents_after": new_count}


def _derive_rbac_sets() -> None:
    """Derive RBAC sets from TEAM_CONFIG. Called at startup and on hot-reload."""
    global PLATFORM_OPERATOR_AGENTS, _RBAC_PLATFORM_OPERATORS, _RBAC_RESTART_ALLOWED, _RBAC_SA_CREATE_ALLOWED  # noqa: PLW0603
    if not TEAM_CONFIG:
        return
    agents = TEAM_CONFIG.get("agents", [])
    # Platform operators: level <= 1 (active flag only controls auto-start, not permissions)
    operators = set()
    for a in agents:
        level = a.get("level")
        if level is not None and int(level) <= 1:
            operators.add(a.get("id", ""))
    operators.discard("")
    if operators:
        _RBAC_PLATFORM_OPERATORS = operators
        PLATFORM_OPERATOR_AGENTS = _RBAC_PLATFORM_OPERATORS
    # Restart allowed: agents with 'server-restart' capability/permission OR level <= 1
    restart = set(operators)
    restart.add("user")
    for a in agents:
        caps = a.get("capabilities", [])
        if isinstance(caps, list) and any("server-restart" in str(c).lower() for c in caps):
            restart.add(a.get("id", ""))
        perms = a.get("permissions", {})
        if isinstance(perms, dict) and "server-restart" in perms:
            restart.add(a.get("id", ""))
    restart.discard("")
    if restart:
        _RBAC_RESTART_ALLOWED = restart
    # Standing Approval create: level <= 1 or user
    sa_create = set(operators)
    sa_create.add("user")
    sa_create.discard("")
    if sa_create:
        _RBAC_SA_CREATE_ALLOWED = sa_create
    print(f"[rbac] Derived: operators={sorted(_RBAC_PLATFORM_OPERATORS)}, restart={sorted(_RBAC_RESTART_ALLOWED)}, sa_create={sorted(_RBAC_SA_CREATE_ALLOWED)}")


# Load team.json at module level — override aliases + merge team routes
TEAM_CONFIG = load_team_config()
if TEAM_CONFIG is not None:
    _derived_aliases = derive_aliases(TEAM_CONFIG)
    if _derived_aliases:
        AGENT_ID_ALIASES.update(_derived_aliases)
        print(f"[team] Loaded {len(_derived_aliases)} aliases from team.json")
    # Note: Team routes are merged in bridge_watcher.py (which owns ALLOWED_ROUTES)
    teams_count = len(TEAM_CONFIG.get("teams", []))
    print(f"[team] team.json loaded: {len(TEAM_CONFIG.get('agents', []))} agents, {teams_count} teams")
    # V3 Fassade: inject team.json backend into board_api
    board_api.init_team_backend(TEAM_CONFIG, TEAM_CONFIG_LOCK, _atomic_write_team_json)
    print("[team] board_api initialized with team.json backend")
    _derive_rbac_sets()


# ---------------------------------------------------------------------------
# S3: Memory-Validierung — pruefen ob aktive Agents CONTEXT_BRIDGE.md haben
def _validate_agent_memory(team: dict[str, Any]) -> None:
    """Check that active agents have CONTEXT_BRIDGE.md. Log warnings."""
    for agent in team.get("agents", []):
        if not agent.get("active", False):
            continue
        home_dir = agent.get("home_dir", "")
        if not home_dir:
            continue
        aid = agent.get("id", "")
        cb_path = os.path.join(home_dir, "CONTEXT_BRIDGE.md")
        cb_alt = os.path.join(home_dir, ".agent_sessions", aid, "CONTEXT_BRIDGE.md") if aid else ""
        if not os.path.exists(cb_path) and not (cb_alt and os.path.exists(cb_alt)):
            print(f"[memory] WARN: {aid} hat keine CONTEXT_BRIDGE.md in {home_dir}")


if TEAM_CONFIG is not None:
    _validate_agent_memory(TEAM_CONFIG)


def resolve_agent_alias(agent_id: str) -> str:
    """Resolve agent ID aliases to canonical bridge-ID."""
    return AGENT_ID_ALIASES.get(agent_id, agent_id)


# ── Non-MCP Direct Push ──────────────────────────────────────────────
# Codex/Qwen/Gemini agents don't have a WebSocket listener (bridge_mcp.py).
# After ws_broadcast_message(), push a tmux notification so they know to call
# bridge_receive().  This closes the delivery-parity gap with Claude.
_NON_MCP_ENGINES = frozenset({"codex", "qwen", "gemini", "gemini_cli", "qwen_code"})
_NON_MCP_PUSH_COOLDOWN: dict[str, float] = {}
_NON_MCP_PUSH_MIN_INTERVAL = 2.0  # seconds between pushes to same agent


def _agent_engine_from_team(agent_id: str) -> str:
    """Return engine for agent_id from TEAM_CONFIG (no locks required for read)."""
    tc = TEAM_CONFIG
    if not tc:
        return ""
    for a in tc.get("agents", []):
        if a.get("id") == agent_id:
            return str(a.get("engine", "")).strip().lower()
    return ""


def _push_non_mcp_notification(msg: dict[str, Any]) -> None:
    """Immediate tmux notification for non-MCP agents (Codex/Qwen/Gemini).

    Event-driven: called right after ws_broadcast_message() in append_message().
    Replaces polling-dependency for message awareness.
    """
    recipient = msg.get("to", "")
    sender = msg.get("from", "")

    # Determine target agents
    _skip = {"system", "user"}
    targets: list[str] = []
    if recipient in {"all", "all_managers", "leads"} or recipient.startswith("team:"):
        # Special audiences must keep their semantic target set; otherwise
        # non-manager codex/qwen/gemini agents get spurious wake-ups.
        targets = _resolve_live_message_targets(recipient, sender=sender)
    elif recipient not in _skip:
        targets.append(recipient)

    if not targets:
        return

    now = time.time()
    for target in targets:
        engine = _agent_engine_from_team(target)
        if engine not in _NON_MCP_ENGINES:
            continue
        # Cooldown to avoid notification spam
        last = _NON_MCP_PUSH_COOLDOWN.get(target, 0.0)
        if now - last < _NON_MCP_PUSH_MIN_INTERVAL:
            continue
        _NON_MCP_PUSH_COOLDOWN[target] = now

        def _do_push(t: str = target, s: str = sender) -> None:
            try:
                session_name = _tmux_session_for(t)
                chk = subprocess.run(
                    ["tmux", "has-session", "-t", session_name],
                    capture_output=True, timeout=3,
                )
                if chk.returncode != 0:
                    return
                sender_hint = str(s).replace("'", "\\'")
                note = (
                    f"\nNeue Nachricht von {s} — "
                    f"AUFTRAG: 1) Rufe bridge_receive() auf. "
                    f"2) Lies und verarbeite die Nachricht. "
                    f"3) Antworte dem Sender via bridge_send(to='{sender_hint}', "
                    f"content='...'). Starte JETZT.\n"
                )
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, "-l", note],
                    capture_output=True, timeout=3,
                )
            except Exception:
                pass

        threading.Thread(target=_do_push, daemon=True, name=f"non-mcp-push-{target}").start()

def _is_management_agent(agent_id: str) -> bool:
    """Check if agent is management-level (level <= 1) and active in team.json."""
    if TEAM_CONFIG is None:
        return False
    for a in TEAM_CONFIG.get("agents", []):
        if a.get("id") == agent_id:
            return a.get("level", 99) <= 1 and a.get("active", False)
    return False


# V1 PID functions — kept for rollback safety, no longer primary in V2
def pid_path(name: str) -> str:
    return os.path.join(PID_DIR, f"{name}.pid")


def agent_log_path(name: str) -> str:
    return os.path.join(AGENT_LOG_DIR, f"{name}.log")


def read_pid(name: str) -> int | None:
    path = pid_path(name)
    if not os.path.exists(path):
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_pid_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_process_tree(pid: int) -> list[int]:
    """Get all descendant PIDs of a process (children, grandchildren, etc.)."""
    tree = [pid]
    try:
        # Use /proc filesystem to find children (Linux-specific, fast)
        children_path = f"/proc/{pid}/task/{pid}/children"
        if os.path.exists(children_path):
            raw = Path(children_path).read_text(encoding="utf-8").strip()
            if raw:
                for child_pid_str in raw.split():
                    try:
                        child_pid = int(child_pid_str)
                        tree.extend(get_process_tree(child_pid))
                    except (ValueError, OSError):
                        pass
    except OSError:
        pass
    return tree


def stop_pid(pid: int, timeout_seconds: float = 3.0) -> str:
    """Stop a process and all its children (process tree kill)."""
    # Collect the full process tree BEFORE sending signals
    tree = get_process_tree(pid)

    # Send SIGTERM to all processes in the tree (children first, parent last)
    for p in reversed(tree):
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not any(is_pid_running(p) for p in tree):
            return "stopped"
        time.sleep(0.1)

    # SIGKILL remaining processes
    for p in reversed(tree):
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass

    return "killed"


def stop_known_agents() -> list[dict[str, Any]]:
    """Stop all known agents. V2: kills tmux sessions + legacy PID cleanup."""
    stopped: list[dict[str, Any]] = []

    # V2: Kill all acw_* tmux sessions + overridden sessions (e.g. bb_*)
    override_reverse = {sn: aid for aid, sn in _SESSION_NAME_MAP.items()}
    for session_info in list_agent_sessions():
        session_name = session_info.get("session_name", "")
        if session_name.startswith("acw_"):
            agent_id = session_name[4:]  # strip "acw_" prefix
            kill_agent_session(agent_id)
            stopped.append({"name": session_name, "tmux_killed": True, "state": "stopped"})
            AGENT_LAST_SEEN.pop(agent_id, None)
            AGENT_BUSY.pop(agent_id, None)
        elif session_name in override_reverse:
            # Kill overridden sessions (bb_alpha_lead, etc.)
            agent_id = override_reverse[session_name]
            subprocess.run(["tmux", "kill-session", "-t", session_name],
                           capture_output=True, timeout=5)
            stopped.append({"name": session_name, "tmux_killed": True, "state": "stopped"})
            AGENT_LAST_SEEN.pop(agent_id, None)
            AGENT_BUSY.pop(agent_id, None)

    # V1 legacy: Also stop any PID-based agents that might still be running
    for name in sorted(known_agent_names()):
        pid = read_pid(name)
        state = "absent"
        if pid is not None:
            if is_pid_running(pid):
                state = stop_pid(pid)
            else:
                state = "stale"
        try:
            Path(pid_path(name)).unlink(missing_ok=True)
        except OSError:
            pass

        agent_id = name.removesuffix("_agent")
        AGENT_LAST_SEEN.pop(agent_id, None)
        AGENT_BUSY.pop(agent_id, None)

        if pid is not None:
            stopped.append({"name": name, "pid": pid, "state": state})
    return stopped


def open_agent_sessions(config: dict[str, Any]) -> list[dict[str, Any]]:
    """V2: Open tmux sessions for agents instead of subprocess.Popen.

    Uses tmux_manager.create_agent_session() to start persistent
    interactive Claude CLI sessions in tmux.
    """
    agent_a_engine = str(config["agent_a_engine"])
    agent_b_engine = str(config["agent_b_engine"])
    project_path = str(config["project_path"])
    team_lead_cli_enabled = bool(config.get("team_lead_cli_enabled", False))
    team_lead_engine = str(config.get("team_lead_engine", "codex"))
    team_lead_scope_file = str(config.get("team_lead_scope_file", ""))
    runtime_profiles = [
        p for p in (config.get("agent_profiles") if isinstance(config.get("agent_profiles"), list) else [])
        if isinstance(p, dict) and str(p.get("id", "")).strip()
    ]
    runtime_profiles_by_id = {str(p["id"]).strip(): p for p in runtime_profiles}

    raw_layout = config.get("runtime_specs")
    if _runtime_layout_is_valid(raw_layout):
        layout = _clone_runtime_layout(raw_layout)
    else:
        layout = resolve_runtime_specs(
            agent_a_engine,
            agent_b_engine,
            team_lead_cli_enabled=team_lead_cli_enabled,
            team_lead_engine=team_lead_engine,
            team_lead_scope_file=team_lead_scope_file,
        )
    if not os.path.isdir(project_path):
        raise ValueError(f"project_path does not exist: {project_path}")

    # Build fallback team_members list when no runtime profiles are present.
    team_members = []
    agent_a_position = str(config.get("agent_a_position", "")).strip()
    agent_b_position = str(config.get("agent_b_position", "")).strip()
    for spec in layout:
        role = ""
        if spec.get("slot") == "lead":
            role = "Koordination"
        elif spec.get("slot") == "a":
            role = agent_a_position or "Agent A"
        elif spec.get("slot") == "b":
            role = agent_b_position or "Agent B"
        team_members.append({"id": spec["id"], "role": role})

    started: list[dict[str, Any]] = []
    for spec in layout:
        agent_id = spec["id"]
        name = spec["name"]
        runtime_profile = runtime_profiles_by_id.get(agent_id, {})

        # Determine role description
        role = str(runtime_profile.get("role", "")).strip()
        if not role:
            if spec.get("slot") == "lead":
                role = "Koordination"
            elif spec.get("slot") == "a":
                role = agent_a_position or "Agent A"
            elif spec.get("slot") == "b":
                role = agent_b_position or "Agent B"

        # All agents run inside the project path.
        # Each gets its own workspace at {project_path}/.agent_sessions/{agent_id}/
        # Claude Code reads CLAUDE.md from CWD (agent-specific) + parent dirs (project-level).
        agent_project = project_path

        spawn_config_dir = str(spec.get("config_dir", "")).strip()
        spawn_model = str(runtime_profile.get("model", "")).strip() or str(spec.get("model", "")).strip()
        spawn_role_desc = str(runtime_profile.get("prompt", "")).strip() or str(runtime_profile.get("description", "")).strip() or role
        spawn_team_members = _runtime_team_members_for_profiles(agent_id, runtime_profiles) if runtime_profiles else team_members
        spawn_permissions = runtime_profile.get("capabilities")
        spawn_scope = runtime_profile.get("scope")
        spawn_permission_mode = str(runtime_profile.get("permission_mode", "default")).strip() or "default"
        spawn_tools = runtime_profile.get("tools")
        spawn_mcp_servers = str(runtime_profile.get("mcp_servers", "")).strip()
        team_agent_conf = None
        with TEAM_CONFIG_LOCK:
            if TEAM_CONFIG:
                for _ta in TEAM_CONFIG.get("agents", []):
                    if _ta.get("id") == agent_id:
                        team_agent_conf = _ta
                        break
        # Keep TEAM_CONFIG_LOCK non-reentrant: _team_members_for acquires it internally.
        _tm = _team_members_for(agent_id)
        if _tm:
            spawn_team_members = _tm
        if team_agent_conf:
            spawn_role_desc = spawn_role_desc or _role_description_for(team_agent_conf, fallback=role)
            spawn_config_dir = str(team_agent_conf.get("config_dir", "")).strip() or spawn_config_dir
            spawn_mcp_servers = str(team_agent_conf.get("mcp_servers", "")).strip() or spawn_mcp_servers
            spawn_model = str(team_agent_conf.get("model", "")).strip() or spawn_model
            if spawn_permissions is None:
                spawn_permissions = team_agent_conf.get("permissions")
            if spawn_scope is None:
                spawn_scope = team_agent_conf.get("scope")
        # Read prompt_file if configured (e.g. prompts/codex.txt for Codex agents)
        _spawn_prompt = ""
        with TEAM_CONFIG_LOCK:
            if TEAM_CONFIG:
                for _ta in TEAM_CONFIG.get("agents", []):
                    if _ta.get("id") == agent_id:
                        _pf = str(_ta.get("prompt_file", "")).strip()
                        if _pf and os.path.isfile(_pf):
                            try:
                                _spawn_prompt = open(_pf, "r", encoding="utf-8").read().strip()
                            except OSError:
                                pass
                        break
        success = create_agent_session(
            agent_id=agent_id,
            role=role,
            project_path=agent_project,
            team_members=spawn_team_members,
            engine=spec["engine"],
            bridge_port=PORT,
            role_description=spawn_role_desc,
            config_dir=spawn_config_dir,
            mcp_servers=spawn_mcp_servers,
            model=spawn_model,
            permissions=spawn_permissions,
            scope=spawn_scope,
            permission_mode=spawn_permission_mode,
            allowed_tools=spawn_tools if isinstance(spawn_tools, list) else None,
            report_recipient=str(runtime_profile.get("reports_to", "")).strip(),
            initial_prompt=_spawn_prompt,
        )
        failure = consume_agent_start_failure(agent_id)

        item = {
            "name": name,
            "id": agent_id,
            "engine": spec["engine"],
            "peer": spec["peer"],
            "tmux_session": _tmux_session_for(agent_id),
            "alive": success,
            "cwd": agent_project,
        }
        if failure:
            item.update(
                {
                    "error_stage": failure.get("stage", ""),
                    "error_reason": failure.get("reason", ""),
                    "error_detail": failure.get("detail", ""),
                }
            )
        started.append(item)

    return started


# V1 start_agents kept commented out for rollback safety
# def start_agents(config: dict[str, Any]) -> list[dict[str, Any]]:
#     """DEPRECATED V1: Subprocess-based agent start. Replaced by open_agent_sessions()."""
#     pass


def _agent_workspace_project_paths(agent_id: str, home_dir: str) -> tuple[Path, str]:
    home_path = Path(home_dir).expanduser()
    if home_path.parent.name == ".agent_sessions" and home_path.name == agent_id:
        return home_path, str(home_path.parent.parent)
    return home_path / ".agent_sessions" / agent_id, str(home_path)


def _sync_agent_persistent_cli_config(agent_id: str, agent_entry: dict[str, Any]) -> None:
    home_dir = str(agent_entry.get("home_dir", "")).strip()
    if not home_dir:
        raise OSError(f"home_dir missing for agent '{agent_id}'")
    workspace, project_path = _agent_workspace_project_paths(agent_id, home_dir)
    if not os.path.isdir(project_path):
        raise OSError(f"project_path does not exist for agent '{agent_id}': {project_path}")
    _write_agent_runtime_config(
        workspace,
        str(agent_entry.get("engine", "claude")).strip() or "claude",
        project_path,
        mcp_servers=str(agent_entry.get("mcp_servers", "")).strip(),
        model=str(agent_entry.get("model", "")).strip(),
        permission_mode="default",
    )


def _read_pid_file(path: str) -> int | None:
    """Read PID from file, return None if missing or invalid."""
    try:
        return int(open(path).read().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """Check if process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pgrep(pattern: str) -> int | None:
    """Find PID by process name pattern via pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=3,
        )
        pids = [int(p) for p in result.stdout.strip().splitlines() if p.strip()]
        return pids[0] if pids else None
    except Exception:
        return None


def _get_agent_context_pct(agent_id: str) -> int | None:
    """Extract context usage percentage from agent's tmux statusline.

    The statusline shows: [Model] ████░░░░░░ 73%! | $1.23
    We capture the last few lines and look for engine-specific patterns.
    """
    session_name = _tmux_session_for(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return None
        # Search last 5 lines for Claude-style context percentage pattern.
        # Claude statusline format: [Model] ████░░░░ 24% | $75.66
        # tmux capture-pane may mangle Unicode to replacement chars,
        # so we match the simpler pattern: digits% on a line with | and $
        lines = (result.stdout or "").strip().splitlines()
        for line in reversed(lines[-5:]):
            if "|" in line and "$" in line:
                match = re.search(r'(\d+)%', line)
                if match:
                    return int(match.group(1))
        # Codex footer format: "... 79% left ...". Convert to usage.
        for line in reversed(lines[-8:]):
            match = re.search(r'(\d+)\s*%\s*left\b', line, re.IGNORECASE)
            if match:
                pct_left = int(match.group(1))
                return max(0, min(100, 100 - pct_left))
        return None
    except Exception:
        return None


def _get_runtime_config_dir(agent_id: str) -> str:
    """Read CLAUDE_CONFIG_DIR from the agent's running tmux process environment.

    This is the single Source of Truth for where an agent's config lives.
    Falls back to team.json config_dir, then common known paths.
    """
    # Strategy 1: Read from /proc/{pid}/environ of the agent's tmux process
    session_name = f"acw_{agent_id}"
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_pid}"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            pane_pid = result.stdout.strip().splitlines()[0].strip()
            if pane_pid.isdigit():
                # Check child processes (the actual CLI process)
                child_result = subprocess.run(
                    ["pgrep", "-P", pane_pid],
                    capture_output=True, text=True, timeout=3,
                )
                pids_to_check = []
                if child_result.returncode == 0:
                    pids_to_check = [p.strip() for p in child_result.stdout.strip().splitlines() if p.strip().isdigit()]
                pids_to_check.append(pane_pid)  # fallback to pane pid itself
                for pid in pids_to_check:
                    environ_path = f"/proc/{pid}/environ"
                    try:
                        with open(environ_path, "r", encoding="utf-8", errors="replace") as f:
                            env_data = f.read()
                        for entry in env_data.split("\0"):
                            if entry.startswith("CLAUDE_CONFIG_DIR="):
                                config_dir = entry.split("=", 1)[1]
                                if config_dir and os.path.isdir(config_dir):
                                    return config_dir
                    except (OSError, PermissionError):
                        continue
    except Exception:
        pass

    # Strategy 2: team.json config_dir (may be stale but better than nothing)
    if TEAM_CONFIG:
        for a in TEAM_CONFIG.get("agents", []):
            if a.get("id") == agent_id:
                cd = a.get("config_dir", "")
                if cd and os.path.isdir(cd):
                    return cd
                break

    # Strategy 3: Common known paths
    for candidate in [
        str(Path.home() / f".claude-agent-{agent_id}"),
        str(Path.home() / ".claude-sub2"),
        str(Path.home() / ".claude"),
    ]:
        if os.path.isdir(candidate):
            # Verify it has a projects/ dir (sign of actual use)
            if os.path.isdir(os.path.join(candidate, "projects")):
                return candidate

    return ""


_init_health_monitor(
    compute_health=_compute_health,
    supervisor_check_and_restart=_supervisor_check_and_restart,
    append_message=append_message,
    ws_broadcast=ws_broadcast,
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
)

_init_supervisor(
    pid_dir=PID_DIR,
    backend_dir=os.path.dirname(__file__),
    agent_log_dir=AGENT_LOG_DIR,
    read_pid_file=_read_pid_file,
    pid_alive=_pid_alive,
    pgrep=_pgrep,
    resolve_forwarder_session_name=_resolve_forwarder_session_name,
    tmux_session_name_exists=_tmux_session_name_exists,
    send_health_alert=_send_health_alert,
    append_message=append_message,
    system_status_getter=lambda: _SYSTEM_STATUS,
)


_init_cli_monitor(
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_rate_limited=AGENT_RATE_LIMITED,
    tmux_session_for=_tmux_session_for,
    check_tmux_session=_check_tmux_session,
    append_message=append_message,
    ws_broadcast=ws_broadcast,
    rate_limit_patterns=_RATE_LIMIT_PATTERNS,
    is_agent_at_prompt=lambda agent_id: __import__("bridge_watcher").is_agent_at_prompt(agent_id),
)

_init_rate_limit_resume(
    agent_state_lock=AGENT_STATE_LOCK,
    agent_rate_limited=AGENT_RATE_LIMITED,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
    tmux_session_for=_tmux_session_for,
    check_tmux_session=_check_tmux_session,
    start_agent_from_conf=_start_agent_from_conf,
    append_message=append_message,
    ws_broadcast=ws_broadcast,
)

_init_maintenance(
    cleanup_expired_scope_locks=_cleanup_expired_scope_locks,
    cleanup_expired_whiteboard=_cleanup_expired_whiteboard,
    check_task_timeouts=_check_task_timeouts,
)

_init_heartbeat_prompt(
    graceful_shutdown_lock=_GRACEFUL_SHUTDOWN_LOCK,
    graceful_shutdown=_GRACEFUL_SHUTDOWN,
    system_status=_SYSTEM_STATUS,
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
    append_message=append_message,
    team_config=TEAM_CONFIG,
    team_config_getter=lambda: TEAM_CONFIG,
)

_init_codex_hook(
    graceful_shutdown_pending=lambda: _GRACEFUL_SHUTDOWN["pending"],
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    team_config_getter=lambda: TEAM_CONFIG,
    tmux_session_for=_tmux_session_for,
    msg_lock=LOCK,
    cursors=CURSORS,
    messages=MESSAGES,
    task_lock=TASK_LOCK,
    tasks=TASKS,
)

_init_task_pusher(
    graceful_shutdown_pending=lambda: _GRACEFUL_SHUTDOWN["pending"],
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
    task_lock=TASK_LOCK,
    tasks=TASKS,
    load_agent_state=_load_agent_state,
    save_agent_state=_save_agent_state,
    append_message=append_message,
)

_init_auto_assign(
    graceful_shutdown_pending=lambda: _GRACEFUL_SHUTDOWN["pending"],
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
    load_agent_state=_load_agent_state,
    agent_activities=AGENT_ACTIVITIES,
    task_lock=TASK_LOCK,
    tasks=TASKS,
    persist_tasks=_persist_tasks,
    append_message=append_message,
)

_init_buddy_knowledge(
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    team_config_getter=lambda: TEAM_CONFIG,
    backend_dir=os.path.dirname(__file__),
    agent_state_dir=AGENT_STATE_DIR,
    log_file=LOG_FILE,
    port=PORT,
    ws_port=WS_PORT,
    bridge_strict_auth=BRIDGE_STRICT_AUTH,
)

_init_distillation(
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_is_live=_agent_is_live,
    append_message=append_message,
)

_init_auto_gen(
    msg_lock=LOCK,
    messages=MESSAGES,
    team_lead_id=TEAM_LEAD_ID,
    ensure_parent_dir=ensure_parent_dir,
)


# V1 DEPRECATED — PID resolution no longer used in V2 (tmux sessions replace PID tracking)
# def _resolve_agent_pid(agent_id: str) -> int | None:
#     """Resolve the PID for an agent by checking RUNTIME config and common name patterns."""
#     pid: int | None = None
#     with RUNTIME_LOCK:
#         for agent in RUNTIME.get("agents", []):
#             if agent.get("id") == agent_id:
#                 name = agent.get("name", "")
#                 if name:
#                     pid = read_pid(name)
#                 break
#     if pid is None:
#         pid = read_pid(f"{agent_id}_agent")
#     return pid


def _notify_teamlead_agent_crashed(agent_id: str, previous_status: str) -> None:
    """V4: Targeted crash alert — notify task creators + management, not all agents.

    V2: Uses tmux session check instead of PID check.
    V4: Targeted notifications — task creators, team lead, management-level agents.
    """
    if is_session_alive(agent_id):
        return

    # Only alert for configured agents, not transient API registrations
    if agent_id not in set(current_runtime_agent_ids()) and agent_id not in _load_agents_conf():
        return

    ws_broadcast("crash_alert", {
        "agent_id": agent_id,
        "previous_status": previous_status,
        "message": f"Agent {agent_id} ist abgestuerzt (vorheriger Status: {previous_status}).",
    })
    print(f"[health] CRASH: {agent_id} (was {previous_status}, tmux session dead)")
    event_bus.emit_agent_offline(agent_id, "heartbeat_timeout")

    # V4: Targeted notification — task creators + management (not all agents)
    notified: set[str] = set()
    msg = f"[OFFLINE] Agent {agent_id} ist offline (vorher: {previous_status})."
    # 1. Task creators with active tasks assigned to this agent
    with TASK_LOCK:
        for t in TASKS.values():
            if t.get("assigned_to") == agent_id and t.get("state") in ("created", "claimed", "acked"):
                creator = t.get("created_by", "")
                if creator and creator != agent_id:
                    notified.add(creator)
    # 2. Management-level agents (level 0-1) from team.json
    if TEAM_CONFIG:
        for ag in TEAM_CONFIG.get("agents", []):
            aid = ag.get("id", "")
            if aid and ag.get("level", 99) <= 1 and aid != agent_id:
                notified.add(aid)
    # 3. Always notify user (Leo)
    notified.add("user")
    for target in notified:
        try:
            append_message("system", target, msg)
        except Exception:
            pass
    # Whiteboard alert
    _whiteboard_post("system", "alert",
                     f"Agent {agent_id} offline (vorher: {previous_status})",
                     severity="critical", ttl_seconds=600)


def _seed_phantom_agent_registration(
    agent_id: str,
    *,
    role: str = "",
    capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Project a live tmux session into REGISTERED_AGENTS until real register arrives."""
    now_ts = time.time()
    now_iso = utc_now_iso()
    existing = _registered_agents_snapshot().get(agent_id, {})
    phantom_role = str(role or existing.get("role", "") or _get_runtime_agent_role(agent_id) or agent_id).strip()
    phantom_caps = capabilities if capabilities is not None else existing.get("capabilities", [])
    old_token = AGENT_TOKENS.pop(agent_id, None)
    if old_token:
        SESSION_TOKENS.pop(old_token, None)
    token = secrets.token_hex(32)
    SESSION_TOKENS[token] = agent_id
    AGENT_TOKENS[agent_id] = token
    reg: dict[str, Any] = {
        "role": phantom_role,
        "capabilities": phantom_caps,
        "engine": str(existing.get("engine", "") or _get_agent_engine(agent_id) or "claude"),
        "registered_at": now_iso,
        "last_heartbeat": now_ts,
        "last_heartbeat_iso": now_iso,
        "phantom": True,
    }
    for key in (
        "resume_id",
        "workspace",
        "project_root",
        "home_dir",
        "instruction_path",
        "cli_identity_source",
        "model",
    ):
        value = existing.get(key)
        if value:
            reg[key] = value
    with AGENT_STATE_LOCK:
        REGISTERED_AGENTS[agent_id] = reg
        AGENT_LAST_SEEN[agent_id] = now_ts
        AGENT_BUSY[agent_id] = False
    update_agent_status(agent_id)
    return reg


def _auto_cleanup_agents(ttl_seconds: float = 300.0) -> None:
    """Remove agents that have been disconnected for longer than ttl_seconds.

    Cleans REGISTERED_AGENTS, AGENT_LAST_SEEN, AGENT_BUSY, AGENT_ACTIVITIES,
    _PREV_AGENT_STATUS, and CURSORS for stale agents.
    Does NOT remove agents that are part of the current RUNTIME config.
    """
    now = time.time()
    runtime_ids = set(current_runtime_agent_ids())
    to_remove = []
    with AGENT_STATE_LOCK:
        for agent_id, reg in REGISTERED_AGENTS.items():
            if agent_id in runtime_ids or _check_tmux_session(agent_id):
                continue  # Never auto-remove runtime agents or any still-live tmux session
            last_seen = _agent_liveness_ts(agent_id, reg=reg)
            if last_seen <= 0 or (now - last_seen) > ttl_seconds:
                to_remove.append(agent_id)
        for agent_id in to_remove:
            REGISTERED_AGENTS.pop(agent_id, None)
            AGENT_LAST_SEEN.pop(agent_id, None)
            AGENT_BUSY.pop(agent_id, None)
            _PREV_AGENT_STATUS.pop(agent_id, None)
            # S5: Clean up session tokens
            old_token = AGENT_TOKENS.pop(agent_id, None)
            if old_token:
                SESSION_TOKENS.pop(old_token, None)
    # P2-2 Fix: Clean under LOCK to prevent race with /activity writes
    with LOCK:
        for agent_id in to_remove:
            AGENT_ACTIVITIES.pop(agent_id, None)
            CURSORS.pop(agent_id, None)
    if to_remove:
        print(f"[cleanup] Removed {len(to_remove)} stale agents: {', '.join(to_remove)}")


# Crash patterns — checked against last N lines of tmux pane
_CRASH_PATTERNS = re.compile(
    r"Segfault|SIGSEGV|panic:|FATAL|"
    r"Traceback \(most recent|"
    r"Error: .{10,}|"
    r"Aborted \(core dumped\)|"
    r"killed|OOMKilled",
    re.IGNORECASE,
)


def _check_codex_health(agent_id: str) -> dict[str, Any]:
    """Codex-specific health check.

    Returns:
        {"alive": bool, "crashed": bool, "at_prompt": bool, "detail": str}
    """
    session_name = _tmux_session_for(agent_id)
    alive = is_session_alive(agent_id)
    if not alive:
        return {"alive": False, "crashed": True, "at_prompt": False,
                "detail": "tmux session dead"}

    # Check last 10 lines for crash patterns
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return {"alive": True, "crashed": False, "at_prompt": False,
                    "detail": "capture-pane failed"}
        lines = (result.stdout or "").strip().splitlines()
        last_lines = lines[-10:] if len(lines) >= 10 else lines
        for line in last_lines:
            if _CRASH_PATTERNS.search(line):
                return {"alive": True, "crashed": True, "at_prompt": False,
                        "detail": f"crash pattern: {line.strip()[:80]}"}
    except Exception:
        pass

    # Check prompt (agent idle vs processing)
    from bridge_watcher import is_agent_at_prompt
    at_prompt = is_agent_at_prompt(agent_id)

    return {"alive": True, "crashed": False, "at_prompt": at_prompt,
            "detail": "ok"}



def _auto_start_buddy_agent() -> bool:
    """Auto-start buddy agent from team.json if offline.

    Called when someone sends a message to 'buddy' but buddy is not registered.
    Uses same logic as POST /agents/{id}/restart but only starts (no kill).
    Returns True if buddy was successfully started.
    """
    if TEAM_CONFIG is None:
        print("[buddy] Cannot auto-start: team.json not loaded")
        return False
    # Find buddy in team.json
    buddy_conf = None
    for a in TEAM_CONFIG.get("agents", []):
        if a.get("id") == "buddy":
            buddy_conf = a
            break
    if buddy_conf is None:
        print("[buddy] Cannot auto-start: 'buddy' not in team.json")
        return False
    if not buddy_conf.get("active", False):
        print("[buddy] Cannot auto-start: buddy is inactive in team.json")
        return False
    # Already running?
    if is_session_alive("buddy"):
        print("[buddy] tmux session already alive — skip auto-start")
        return False
    # Start buddy agent
    try:
        home_dir = str(buddy_conf.get("home_dir", "")).strip()
        if not home_dir or not os.path.isdir(home_dir):
            print(f"[buddy] Cannot auto-start: home_dir '{home_dir}' not found")
            return False
        home_path = Path(home_dir)
        if home_path.parent.name == ".agent_sessions" and home_path.name == "buddy":
            project_path = str(home_path.parent.parent)
        else:
            project_path = home_dir
        prompt = "Lies deine Dokumentation. Registriere dich via bridge_register."
        prompt_file = str(buddy_conf.get("prompt_file", "")).strip()
        if prompt_file and os.path.exists(prompt_file):
            try:
                prompt = Path(prompt_file).read_text(encoding="utf-8").strip() or prompt
            except Exception:
                pass
        engine = str(buddy_conf.get("engine", "claude")).strip() or "claude"
        model = str(buddy_conf.get("model", "")).strip()
        config_dir = str(buddy_conf.get("config_dir", "")).strip()
        mcp_servers = str(buddy_conf.get("mcp_servers", "")).strip()
        role = str(buddy_conf.get("description", "buddy")).strip() or "buddy"
        create_agent_session(
            agent_id="buddy", role=role,
            project_path=project_path, team_members=[],
            engine=engine, bridge_port=PORT, role_description=prompt,
            config_dir=config_dir, mcp_servers=mcp_servers, model=model,
            permissions=buddy_conf.get("permissions"),
            scope=buddy_conf.get("scope"),
            report_recipient=str(buddy_conf.get("reports_to", "")).strip(),
            initial_prompt=prompt,
        )
        alive = is_session_alive("buddy")
        print(f"[buddy] Auto-started buddy agent (alive={alive})")
        return alive
    except Exception as exc:
        print(f"[buddy] Auto-start failed: {exc}")
        return False


def _buddy_home_dir() -> str:
    """Resolve Buddy home directory from team config or fallback to repo Buddy dir."""
    if TEAM_CONFIG is not None:
        for agent in TEAM_CONFIG.get("agents", []):
            if str(agent.get("id", "")).strip() == "buddy":
                home_dir = str(agent.get("home_dir", "")).strip()
                if home_dir:
                    return home_dir
    return str((Path(ROOT_DIR).parent / "Buddy").resolve())


def _default_user_profile_body(user_id: str) -> str:
    return f"# {user_id} — User Profile"


def _render_buddy_user_profile(user_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    display_name = str(payload.get("display_name") or user_id).strip() or user_id
    persona = str(payload.get("persona", "")).strip()
    guidance_mode = str(payload.get("guidance_mode", "")).strip()
    autonomy = str(payload.get("autonomy_preference", "")).strip()
    preferred_channels = payload.get("preferred_channels", [])
    recurring_contacts = payload.get("recurring_contacts", [])
    active_projects = payload.get("active_projects", [])
    open_loops = payload.get("open_loops", [])
    trust_notes = str(payload.get("trust_notes", "")).strip()

    def _render_list(value: Any) -> str:
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            return ", ".join(items) if items else "—"
        return "—"

    frontmatter = {
        "user": user_id,
        "type": "profile",
        "display_name": display_name,
    }
    if persona:
        frontmatter["persona"] = persona
    if guidance_mode:
        frontmatter["guidance_mode"] = guidance_mode
    if autonomy:
        frontmatter["autonomy_preference"] = autonomy

    body_lines = [
        f"# {display_name} — User Profile",
        "",
        f"Persona: {persona or 'unknown'}",
        f"Guidance mode: {guidance_mode or 'unknown'}",
        f"Autonomy preference: {autonomy or 'unknown'}",
        f"Preferred channels: {_render_list(preferred_channels)}",
        f"Recurring contacts: {_render_list(recurring_contacts)}",
        f"Active projects: {_render_list(active_projects)}",
        f"Open loops: {_render_list(open_loops)}",
    ]
    if trust_notes:
        body_lines.extend(["", f"Trust notes: {trust_notes}"])
    return frontmatter, "\n".join(body_lines).strip()


def _seed_buddy_user_scope(user_id: str, buddy_home: str | None = None) -> dict[str, Any]:
    """Ensure canonical user note exists and migrate Buddy's legacy local JSON once."""
    normalized_user_id = str(user_id or "user").strip() or "user"
    note_path = f"Users/{normalized_user_id}/USER"
    default_body = _default_user_profile_body(normalized_user_id)

    try:
        import knowledge_engine as ke
    except ImportError as exc:
        return {
            "ok": False,
            "scope_path": note_path,
            "migrated_legacy": False,
            "error": f"knowledge_engine unavailable: {exc}",
        }

    ke.init_vault()
    ke.init_user_vault(normalized_user_id)

    note = ke.read_note(note_path)
    existing_body = str(note.get("body", "")).strip() if isinstance(note, dict) else ""
    if note.get("exists") and existing_body and existing_body != default_body:
        return {
            "ok": True,
            "scope_path": note_path,
            "migrated_legacy": False,
            "preserved_existing": True,
        }

    legacy_home = Path(buddy_home or _buddy_home_dir())
    legacy_json = legacy_home / "memory" / "user_model.json"
    if not legacy_json.is_file():
        return {
            "ok": True,
            "scope_path": note_path,
            "migrated_legacy": False,
            "preserved_existing": bool(note.get("exists")),
        }

    try:
        payload = json.loads(legacy_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "scope_path": note_path,
            "migrated_legacy": False,
            "error": f"legacy user_model invalid: {exc}",
        }

    payload_user_id = str(payload.get("user_id", normalized_user_id)).strip() or normalized_user_id
    if payload_user_id != normalized_user_id:
        return {
            "ok": True,
            "scope_path": note_path,
            "migrated_legacy": False,
            "preserved_existing": bool(note.get("exists")),
            "legacy_user_id": payload_user_id,
        }

    frontmatter, body = _render_buddy_user_profile(normalized_user_id, payload)
    write_result = ke.write_note(note_path, body, frontmatter, mode="overwrite")
    return {
        "ok": bool(write_result.get("ok")),
        "scope_path": note_path,
        "migrated_legacy": bool(write_result.get("ok")),
        "write_result": write_result,
    }


def _get_buddy_frontdoor_status(user_id: str) -> dict[str, Any]:
    """Return the canonical Buddy frontdoor state for a specific user."""
    normalized_user_id = str(user_id or "user").strip() or "user"
    note_path = f"Users/{normalized_user_id}/USER"
    known_user = False
    display_name = normalized_user_id
    guidance_mode = ""
    autonomy = ""

    try:
        import knowledge_engine as ke
        note = ke.read_note(note_path)
        if note.get("exists"):
            known_user = True
            frontmatter = note.get("frontmatter") or {}
            display_name = str(frontmatter.get("display_name") or normalized_user_id).strip() or normalized_user_id
            guidance_mode = str(frontmatter.get("guidance_mode") or "").strip()
            autonomy = str(frontmatter.get("autonomy_preference") or "").strip()
    except Exception:
        pass

    buddy_running = is_session_alive("buddy")
    pending_frontdoor = _has_recent_buddy_frontdoor_ping(normalized_user_id, within_seconds=120.0)
    should_auto_start = (not known_user) and (not pending_frontdoor)
    return {
        "user_id": normalized_user_id,
        "note_path": note_path,
        "known_user": known_user,
        "display_name": display_name,
        "guidance_mode": guidance_mode,
        "autonomy_preference": autonomy,
        "buddy_running": buddy_running,
        "pending_frontdoor": pending_frontdoor,
        "should_auto_start": should_auto_start,
    }


def _has_recent_buddy_frontdoor_ping(user_id: str, within_seconds: float = 30.0) -> bool:
    """Return True if a recent system→buddy frontdoor ping for this user already exists."""
    now = time.time()
    for msg in reversed(MESSAGES):
        if str(msg.get("from", "")).strip() != "system":
            continue
        if str(msg.get("to", "")).strip() != "buddy":
            continue
        meta = msg.get("meta")
        if not isinstance(meta, dict):
            continue
        if meta.get("type") != "buddy_frontdoor":
            continue
        if str(meta.get("user_id", "")).strip() != user_id:
            continue
        ts_raw = str(msg.get("timestamp", "")).strip()
        if not ts_raw:
            return True
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = now - ts.timestamp()
            return age <= within_seconds
        except ValueError:
            return True
    return False


def _ensure_buddy_frontdoor(user_id: str) -> dict[str, Any]:
    """Ensure Buddy is running and queue exactly one onboarding/frontdoor nudge."""
    normalized_user_id = str(user_id or "user").strip() or "user"
    user_scope_result = _seed_buddy_user_scope(normalized_user_id)
    alive_before = is_session_alive("buddy")
    started = False
    if not alive_before:
        started = _auto_start_buddy_agent()
    alive_after = is_session_alive("buddy")
    if not alive_after:
        return {
            "status": "unavailable",
            "user_id": normalized_user_id,
            "alive_before": alive_before,
            "alive_after": alive_after,
            "started": started,
            "queued": False,
            "deduped": False,
            "user_scope": user_scope_result,
        }

    deduped = _has_recent_buddy_frontdoor_ping(normalized_user_id)
    queued = False
    if not deduped:
        append_message(
            "system",
            "buddy",
            "[BUDDY_FRONTDOOR] Ein User wartet im Chat. Begruesse ihn, uebernimm die Beziehung und fuehre ihn in die Bridge.",
            meta={"type": "buddy_frontdoor", "user_id": normalized_user_id},
        )
        queued = True

    return {
        "status": "started" if started else "already_running",
        "user_id": normalized_user_id,
        "alive_before": alive_before,
        "alive_after": alive_after,
        "started": started,
        "queued": queued,
        "deduped": deduped,
        "user_scope": user_scope_result,
    }


def _auto_restart_agent(agent_id: str) -> bool:
    """Kill crashed tmux session and restart agent.

    Returns True if restart succeeded.
    """
    # Graceful Shutdown Protection: Don't restart during pending shutdown
    with _GRACEFUL_SHUTDOWN_LOCK:
        if _GRACEFUL_SHUTDOWN["pending"]:
            print(f"[health] Skip auto-restart for {agent_id}: graceful shutdown pending")
            return False

    # Rate-Limit Protection: Don't restart rate-limited agents
    with AGENT_STATE_LOCK:
        _rl = agent_id in AGENT_RATE_LIMITED
    if _rl:
        print(f"[health] Skip auto-restart for rate-limited agent: {agent_id}")
        return False

    # Priority: read engine from team.json (authoritative), fallback to RUNTIME layout
    tj_engine = ""
    if TEAM_CONFIG:
        with TEAM_CONFIG_LOCK:
            for _a in TEAM_CONFIG.get("agents", []):
                if _a.get("id") == agent_id:
                    tj_engine = str(_a.get("engine", "")).strip()
                    break

    # If agent has team.json config with home_dir, use _start_agent_from_conf (correct path)
    if tj_engine:
        has_home = False
        if TEAM_CONFIG:
            with TEAM_CONFIG_LOCK:
                for _a in TEAM_CONFIG.get("agents", []):
                    if _a.get("id") == agent_id and _a.get("home_dir"):
                        has_home = True
                        break
        if has_home:
            print(f"[health] Auto-restart: {agent_id} (engine={tj_engine}, source=team.json)")
            kill_agent_session(agent_id)
            time.sleep(2)
            return _start_agent_from_conf(agent_id)

    engine = _get_agent_engine(agent_id)
    print(f"[health] Auto-restart: {agent_id} (engine={engine})")

    # Kill old session
    kill_agent_session(agent_id)
    time.sleep(2)

    # Rebuild config from RUNTIME
    with RUNTIME_LOCK:
        project_path = str(RUNTIME.get("project_path", ROOT_DIR))
        runtime_state = dict(RUNTIME)

    layout = _runtime_layout_from_state(runtime_state)
    if not layout:
        print(f"[health] Auto-restart FAILED: cannot resolve layout for {agent_id}")
        return False

    # Find agent spec in layout
    agent_spec = None
    for spec in layout:
        if spec["id"] == agent_id:
            agent_spec = spec
            break
    if not agent_spec:
        print(f"[health] Auto-restart FAILED: {agent_id} not in layout")
        return False

    # Fix 4: Read team_members from team.json (not layout slots)
    team_members_tj = _team_members_for(agent_id)
    team_members = team_members_tj if team_members_tj else [{"id": s["id"], "role": s.get("slot", "")} for s in layout]

    # Resolve config_dir + mcp_servers + role_description from team.json agent config
    health_config_dir = ""
    health_mcp_servers = ""
    health_role_desc = agent_spec.get("slot", "")
    _health_agent_conf: dict = {}
    if TEAM_CONFIG:
        for _a in TEAM_CONFIG.get("agents", []):
            if _a.get("id") == agent_id:
                health_config_dir = str(_a.get("config_dir", "")).strip()
                health_mcp_servers = str(_a.get("mcp_servers", "")).strip()
                _health_agent_conf = _a
                break
    # Fix 3: Use description from team.json as role_description
    if _health_agent_conf:
        health_role_desc = _role_description_for(_health_agent_conf, fallback=health_role_desc)

    # Load mode from agent_state
    agent_state = _load_agent_state(agent_id)
    agent_mode = agent_state.get("mode", "normal")

    # Resolve model from team config
    health_model = ""
    if TEAM_CONFIG:
        for _a in TEAM_CONFIG.get("agents", []):
            if _a.get("id") == agent_id:
                health_model = str(_a.get("model", "")).strip()
                break

    health_permissions = _health_agent_conf.get("permissions") if _health_agent_conf else None
    health_scope = _health_agent_conf.get("scope") if _health_agent_conf else None
    # Read prompt_file for initial_prompt (e.g. prompts/codex.txt)
    _health_prompt = ""
    if _health_agent_conf:
        _pf = str(_health_agent_conf.get("prompt_file", "")).strip()
        if _pf and os.path.isfile(_pf):
            try:
                _health_prompt = open(_pf, "r", encoding="utf-8").read().strip()
            except OSError:
                pass
    success = create_agent_session(
        agent_id=agent_id,
        role=agent_spec.get("slot", ""),
        project_path=project_path,
        team_members=team_members,
        engine=agent_spec["engine"],
        bridge_port=PORT,
        role_description=health_role_desc,
        config_dir=health_config_dir,
        mcp_servers=health_mcp_servers,
        mode=agent_mode,
        model=health_model,
        permissions=health_permissions,
        scope=health_scope,
        report_recipient=str(_runtime_profile_for_agent(agent_id).get("reports_to", "")).strip(),
        initial_prompt=_health_prompt,
    )

    if success:
        print(f"[health] Auto-restart OK: {agent_id}")
        try:
            append_message("system", "user",
                           f"[AUTO-RESTART] Agent {agent_id} wurde automatisch neu gestartet.")
        except Exception:
            pass
    else:
        print(f"[health] Auto-restart FAILED: create_agent_session returned False for {agent_id}")

    return success


# ── Graceful Shutdown helpers ──

def _finalize_graceful_shutdown() -> None:
    """Send [SHUTDOWN_FINAL] to all agents and kill tmux sessions."""
    global _GRACEFUL_SHUTDOWN_TIMER
    with _GRACEFUL_SHUTDOWN_LOCK:
        if _GRACEFUL_SHUTDOWN["finalized"]:
            return
        _GRACEFUL_SHUTDOWN["finalized"] = True
        expected = list(_GRACEFUL_SHUTDOWN["expected_agents"])
        acked = list(_GRACEFUL_SHUTDOWN["acked_agents"])

    missing = [a for a in expected if a not in acked]
    if missing:
        print(f"[graceful-shutdown] Timeout — missing ACKs from: {missing}")
    else:
        print("[graceful-shutdown] All agents ACKed. Finalizing.")

    # Send final message
    append_message("system", "all",
                   f"[SHUTDOWN_FINAL] Graceful shutdown abgeschlossen. Missing ACKs: {missing or 'keine'}.",
                   meta={"type": "shutdown_final"})
    ws_broadcast("shutdown_final", {"missing_acks": missing})

    # Kill all agent tmux sessions
    for aid in expected:
        try:
            _sname = _session_name_for(aid)
            subprocess.run(["tmux", "kill-session", "-t", _sname],
                           capture_output=True, timeout=5)
            print(f"[graceful-shutdown] Killed tmux session: {_sname}")
        except Exception as exc:
            print(f"[graceful-shutdown] Failed to kill {_sname}: {exc}")

    # Update system status
    _SYSTEM_STATUS["shutdown_active"] = True
    _SYSTEM_STATUS["shutdown_since"] = utc_now_iso()
    _SYSTEM_STATUS["shutdown_reason"] = (_SYSTEM_STATUS.get("shutdown_reason") or "") + " [FINALIZED]"

    with _GRACEFUL_SHUTDOWN_LOCK:
        _GRACEFUL_SHUTDOWN_TIMER = None


def _handle_shutdown_ack(agent_id: str) -> None:
    """Process a [SHUTDOWN_ACK] from an agent."""
    with _GRACEFUL_SHUTDOWN_LOCK:
        if not _GRACEFUL_SHUTDOWN["pending"] or _GRACEFUL_SHUTDOWN["finalized"]:
            return
        if agent_id not in _GRACEFUL_SHUTDOWN["acked_agents"]:
            _GRACEFUL_SHUTDOWN["acked_agents"].append(agent_id)
        acked = set(_GRACEFUL_SHUTDOWN["acked_agents"])
        expected = set(_GRACEFUL_SHUTDOWN["expected_agents"])

    print(f"[graceful-shutdown] ACK from {agent_id} ({len(acked)}/{len(expected)})")

    # If all expected agents acked, finalize early
    if expected and acked >= expected:
        global _GRACEFUL_SHUTDOWN_TIMER
        with _GRACEFUL_SHUTDOWN_LOCK:
            timer = _GRACEFUL_SHUTDOWN_TIMER
        if timer:
            timer.cancel()
        _finalize_graceful_shutdown()


# Auto-restart toggle (can be changed via API if needed)
AUTO_RESTART_AGENTS = True
_AGENT_LAST_RESTART: dict[str, float] = {}  # agent_id -> timestamp
_RESTART_LOCK = threading.Lock()  # guards _AGENT_LAST_RESTART check-and-set
_RESTART_COOLDOWN = 120.0  # 2 min between restarts per agent
_AGENT_OAUTH_FAILURES: dict[str, int] = {}  # agent_id -> consecutive OAuth restart count
_AGENT_AUTH_BLOCKED: set[str] = set()  # agents blocked from auto-restart due to OAuth
_OAUTH_MAX_RETRIES = 2  # max OAuth restarts before blocking

def _ensure_agent_online(agent_id: str, task_id: str = "", requester: str = "") -> dict[str, Any]:
    """V4: Check if an agent is online; if not, try to wake/start them.

    Called when a task is assigned (create or patch).
    Returns status dict: {"online": bool, "action": str, "detail": str}
    """
    # 1. Check if registered (has recent heartbeat)
    with AGENT_STATE_LOCK:
        reg = REGISTERED_AGENTS.get(agent_id)
    if reg:
        return {"online": True, "action": "none", "detail": f"{agent_id} is registered"}

    # 2. Not registered — check if tmux session is alive
    tmux_alive = is_session_alive(agent_id)

    if tmux_alive:
        # Session alive but not registered → send wake message via tmux
        wake_msg = (
            f"bridge_receive und weiterarbeiten. "
            f"Du hast einen neuen Task: {task_id}. Registriere dich mit bridge_register."
        )
        try:
            send_to_session(agent_id, wake_msg)
        except Exception as exc:
            print(f"[ensure_online] Failed to send wake to {agent_id}: {exc}")
        # Notify requester
        if requester:
            try:
                append_message("system", requester,
                               f"[AGENT WAKE] {agent_id} laeuft aber war nicht registriert. Wake-Signal gesendet.")
            except Exception:
                pass
        # Post whiteboard alert
        _whiteboard_post("system", "alert",
                         f"Agent {agent_id} nicht registriert — Wake-Signal gesendet",
                         task_id=task_id, severity="warning", ttl_seconds=300)
        return {"online": False, "action": "wake_sent", "detail": f"tmux alive, wake sent to {agent_id}"}

    # 3. tmux session dead → try auto-restart
    if AUTO_RESTART_AGENTS:
        with _RESTART_LOCK:
            last_restart = _AGENT_LAST_RESTART.get(agent_id, 0)
            if (time.time() - last_restart) < _RESTART_COOLDOWN:
                remaining = int(_RESTART_COOLDOWN - (time.time() - last_restart))
                return {"online": False, "action": "cooldown", "detail": f"{agent_id} restart cooldown ({remaining}s remaining)"}
            restarted = _auto_restart_agent(agent_id)
            if restarted:
                _AGENT_LAST_RESTART[agent_id] = time.time()
                if requester:
                    try:
                        append_message("system", requester,
                                       f"[AUTO-START] Agent {agent_id} war offline — wurde automatisch gestartet fuer Task {task_id}.")
                    except Exception:
                        pass
                _whiteboard_post("system", "alert",
                                 f"Agent {agent_id} automatisch gestartet (Task-Zuweisung)",
                                 task_id=task_id, severity="info", ttl_seconds=300)
                return {"online": False, "action": "auto_started", "detail": f"{agent_id} auto-started"}
            else:
                if requester:
                    try:
                        append_message("system", requester,
                                       f"[WARNUNG] Agent {agent_id} konnte nicht gestartet werden. Task {task_id} ist zugewiesen aber Agent ist offline.")
                    except Exception:
                        pass
                _whiteboard_post("system", "alert",
                                 f"Agent {agent_id} offline — Auto-Start fehlgeschlagen",
                                 task_id=task_id, severity="critical", ttl_seconds=600)
                return {"online": False, "action": "start_failed", "detail": f"{agent_id} auto-start failed"}

    return {"online": False, "action": "no_auto_restart", "detail": f"{agent_id} is offline, auto-restart disabled"}


# --- ISSUE-002: Idle Agent Recovery (Auto-Nudge) ---
_AGENT_LAST_NUDGE: dict[str, float] = {}  # agent_id -> last nudge timestamp
_NUDGE_COOLDOWN_SECONDS = 120.0  # 2 min between nudges per agent
# S1-F5 FIX: Rate-limit auto-registration in health checker
_AGENT_LAST_AUTO_REGISTER: dict[str, float] = {}  # agent_id -> last auto-register timestamp
_AUTO_REGISTER_COOLDOWN = 60.0  # max 1 auto-register per agent per 60s




def _is_cli_running_in_pane(agent_id: str) -> bool:
    """Check if an AI CLI process (claude, codex, qwen) is running in the agent's tmux pane.

    Uses tmux list-panes to get the pane PID, then checks /proc for child processes.
    Returns False if only a shell is running (no CLI process).
    """
    session_name = _tmux_session_for(agent_id)
    try:
        # Get pane PID
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_pid}"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        pane_pid = result.stdout.strip().splitlines()[0].strip()
        # Check child processes of the pane shell for known CLI binaries
        result2 = subprocess.run(
            ["ps", "--ppid", pane_pid, "-o", "comm="],
            capture_output=True, text=True, timeout=3,
        )
        if result2.returncode != 0:
            return False
        child_procs = result2.stdout.strip().lower()
        cli_names = ("claude", "codex", "qwen", "node")  # node = claude CLI runtime
        return any(name in child_procs for name in cli_names)
    except Exception:
        return False


def _capture_agent_tail_lines(agent_id: str, *, max_lines: int = 20) -> list[str]:
    """Capture the most recent non-empty tmux lines for an agent session."""
    session_name = _tmux_session_for(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return []
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return []
        return [line.strip() for line in lines[-max_lines:] if line.strip()]
    except Exception:
        return []


def _classify_agent_interactive_blocker(agent_id: str) -> dict[str, str]:
    """Classify official interactive CLI blockers that need manual user action.

    This intentionally relies only on visible CLI/session output, not on Claude
    credential files or private cache state.
    """
    last_lines = _capture_agent_tail_lines(agent_id)
    if not last_lines:
        return {}

    lowered = [line.lower() for line in last_lines]
    limit_line = next(
        (
            line.strip()
            for line in last_lines
            if "you've hit your limit" in line.lower() or "usage limit" in line.lower()
        ),
        "",
    )
    if limit_line or any("/extra-usage" in line for line in lowered):
        return {
            "stage": "runtime_stabilization",
            "reason": "usage_limit_reached",
            "detail": limit_line or "Claude Code reports that the current account has reached its usage limit.",
        }

    if any("paste code here if prompted" in line for line in lowered):
        return {
            "stage": "interactive_setup",
            "reason": "login_required",
            "detail": "Claude Code is waiting for official login confirmation in the session.",
        }

    theme_markers = (
        "choose a theme",
        "select a theme",
        "syntax theme",
        "to change this later, run /theme",
    )
    if any(marker in line for line in lowered for marker in theme_markers):
        return {
            "stage": "interactive_setup",
            "reason": "manual_setup_required",
            "detail": "Claude Code first-run setup requires a manual theme selection in the session.",
        }

    if any("press enter to continue" in line for line in lowered):
        return {
            "stage": "interactive_setup",
            "reason": "manual_setup_required",
            "detail": "Claude Code is waiting for manual first-run confirmation in the session.",
        }

    return {}


def _is_agent_at_oauth_prompt(agent_id: str) -> bool:
    """Detect if an agent is stuck at the OAuth/onboarding login prompt."""
    blocker = _classify_agent_interactive_blocker(agent_id)
    return blocker.get("reason") == "login_required"


def _collect_runtime_registration_failures(
    agent_ids: list[str],
    missing_registrations: list[str],
    dead_sessions: list[str],
) -> list[dict[str, Any]]:
    """Project interactive/manual blockers for runtime agents that failed to stabilize."""
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in list(agent_ids):
        if agent_id not in missing_registrations and agent_id not in dead_sessions:
            continue
        if agent_id in seen:
            continue
        seen.add(agent_id)
        item: dict[str, Any] = {
            "id": agent_id,
            "engine": _get_agent_engine(agent_id),
        }
        blocker = _classify_agent_interactive_blocker(agent_id)
        if blocker:
            item.update(
                {
                    "error_stage": blocker.get("stage", ""),
                    "error_reason": blocker.get("reason", ""),
                    "error_detail": blocker.get("detail", ""),
                }
            )
        elif agent_id in missing_registrations and _is_agent_at_prompt_inline(agent_id):
            item.update(
                {
                    "error_stage": "runtime_stabilization",
                    "error_reason": "waiting_at_prompt",
                    "error_detail": "Agent session reached the CLI prompt but did not register with the Bridge.",
                }
            )
        elif agent_id in dead_sessions:
            item.update(
                {
                    "error_stage": "runtime_stabilization",
                    "error_reason": "session_not_alive",
                    "error_detail": "Agent session is not alive after runtime start.",
                }
            )
        elif agent_id in missing_registrations:
            item.update(
                {
                    "error_stage": "runtime_stabilization",
                    "error_reason": "registration_missing",
                    "error_detail": "Agent session did not register with the Bridge within the stabilization window.",
                }
            )
        failed.append(item)
    return failed


def _summarize_runtime_registration_failures(failed: list[dict[str, Any]]) -> list[str]:
    details: list[str] = []
    for item in failed:
        agent_id = str(item.get("id", "")).strip()
        reason = str(item.get("error_reason", "")).strip()
        detail = str(item.get("error_detail", "")).strip()
        if not agent_id or not reason:
            continue
        if detail:
            details.append(f"{agent_id}: {reason} ({detail})")
        else:
            details.append(f"{agent_id}: {reason}")
    return details


def _is_agent_manual_setup_required(agent_id: str) -> bool:
    blocker = _classify_agent_interactive_blocker(agent_id)
    return blocker.get("reason") == "manual_setup_required"


def _manual_setup_message(agent_id: str) -> str:
    blocker = _classify_agent_interactive_blocker(agent_id)
    return str(blocker.get("detail", "")).strip() or f"{agent_id} needs manual setup in the CLI session."


def _agent_runtime_blocker(agent_id: str) -> dict[str, str]:
    return _classify_agent_interactive_blocker(agent_id)


def _is_agent_at_prompt_inline(agent_id: str) -> bool:
    """Check if agent is at CLI prompt. Inline version — no bridge_watcher dependency.

    Checks last 5 non-empty lines for known prompt patterns (Claude, Codex, Qwen).
    IMPORTANT: First verifies that a CLI process is actually running in the pane.
    If only a shell is running, returns False to avoid nudging bare shell prompts.
    """
    # V5: Guard — if no CLI process is running, this is a shell prompt, not a CLI prompt
    if not _is_cli_running_in_pane(agent_id):
        return False
    session_name = _tmux_session_for(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return False
        last_lines = [l.strip() for l in lines[-5:] if l.strip()]
        if not last_lines:
            return False
        for line in last_lines:
            # Claude prompt patterns
            if re.match(r'^\s*[❯>]\s*$', line):
                return True
            if re.match(r'^\s*❯\s+\S', line):
                return True
            if "bypass permissions" in line:
                return True
            if "What should Claude do" in line:
                return True
            # NOTE: "esc to interrupt" = Claude WORKING (spinner). NOT a prompt.
            # Removed per Kai review — false positive that nudges active agents.
            # Codex prompt
            if re.match(r'^\s*›\s*$', line) or re.match(r'^\s*›\s+\S', line):
                return True
            if re.search(r'codex.*\d+%\s*left', line, re.IGNORECASE):
                return True
            # Qwen prompt
            if re.match(r'^\s*>\s*$', line) or re.match(r'^\s*>\s+\S', line):
                return True
        return False
    except Exception:
        return False


_NUDGE_BUFFER = "bridge_nudge"  # tmux buffer name for nudge text


def _nudge_idle_agent(agent_id: str, reason: str = "at_prompt") -> bool:
    """Send recovery prompt to agent sitting at idle prompt. Ref: ISSUE-002.

    Uses tmux load-buffer + paste-buffer (reliable for TUI apps like Claude Code).
    tmux send-keys sends characters individually which TUIs can mishandle.
    Buffer paste inserts text as a block — much more reliable.
    Engine-aware enter_count: Claude needs 2x Enter (TUI), others 1x.
    """
    session_name = _tmux_session_for(agent_id)
    engine = _get_agent_engine(agent_id)
    enter_count = 2 if engine == "claude" else 1

    prompt = "bridge_receive und weiterarbeiten."

    try:
        # Step 1: Load prompt text into tmux buffer
        load = subprocess.run(
            ["tmux", "load-buffer", "-b", _NUDGE_BUFFER, "-"],
            input=prompt, capture_output=True, text=True, timeout=5,
        )
        if load.returncode != 0:
            print(f"[recovery] FAILED load-buffer for {agent_id}: {load.stderr}")
            return False

        # Step 2: Paste buffer into agent's tmux pane
        paste = subprocess.run(
            ["tmux", "paste-buffer", "-b", _NUDGE_BUFFER, "-t", session_name],
            capture_output=True, text=True, timeout=5,
        )
        if paste.returncode != 0:
            print(f"[recovery] FAILED paste-buffer to {agent_id} ({session_name}): {paste.stderr}")
            return False

        # Step 3: Send Enter key(s) to submit
        time.sleep(0.5)
        for i in range(enter_count):
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "Enter"],
                capture_output=True, timeout=5,
            )
            if i < enter_count - 1:
                time.sleep(2)

        print(f"[recovery] Nudged {agent_id} (session={session_name}, engine={engine}, reason={reason})")
        # S1-F2 FIX: No append_message for nudges — prevents chat spam.
        # Nudge events are logged server-side only (print above).
        return True
    except Exception as e:
        print(f"[recovery] EXCEPTION nudging {agent_id}: {e}")
        return False


# ── Plan-Mode / Interactive Prompt Rescue ──────────────────────────────────
# System-Level fix: Detect agents stuck in interactive plan-mode approval,
# permission prompts, or any blocking interactive dialog.  Auto-Escape them
# so the agent's bridge_receive loop can resume.

_PLAN_RESCUE_PATTERNS: tuple[str, ...] = (
    # Plan-mode related — only genuine plan-mode blocks
    "Do you want to enter plan mode",
    "Do you want to exit plan mode",
    "Exit plan mode?",
    # Plan feedback input prompt
    "Give feedback on this plan",
    "approve this plan",
    # Plan-approval dialog — agent has finished planning and waits for approval
    "Would you like to proceed",
    "Ready to code",
)

# Track last rescue time per agent to avoid spamming
_PLAN_RESCUE_LAST: dict[str, float] = {}
_PLAN_RESCUE_COOLDOWN = 60.0  # Only attempt rescue once per minute per agent
_PLAN_RESCUE_MAX_ESCAPES = 5  # Max Escape presses per rescue attempt


def _plan_mode_rescue_check(agent_id: str) -> bool:
    """Check if agent is stuck in an interactive prompt and auto-escape.

    Returns True if a rescue was performed.
    """
    now = time.time()
    last = _PLAN_RESCUE_LAST.get(agent_id, 0)
    if (now - last) < _PLAN_RESCUE_COOLDOWN:
        return False

    session_name = _tmux_session_for(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        output = (result.stdout or "").strip()
        if not output:
            return False

        # Check last 15 non-empty lines for blocking patterns
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        check_lines = lines[-15:] if len(lines) > 15 else lines
        check_text = "\n".join(check_lines).lower()

        # Skip rescue if agent has bypassPermissions — no permission dialogs shown
        if "bypass permissions" in check_text or "bypasspermissions" in check_text:
            return False

        matched_pattern = None
        for pattern in _PLAN_RESCUE_PATTERNS:
            if pattern.lower() in check_text:
                matched_pattern = pattern
                break

        if not matched_pattern:
            return False

        # Rescue: for plan-approval dialogs send "2" + Enter (Option 2 = keep context)
        # Option 1 clears context — FORBIDDEN. Option 2 preserves context.
        _PLAN_RESCUE_LAST[agent_id] = now
        is_plan_approval = any(p.lower() in matched_pattern.lower() for p in
                               ("would you like to proceed", "ready to code"))
        if is_plan_approval:
            rescue_keys = ["2", "Enter"]
            rescue_desc = "2+Enter (Option 2: keep context, bypass permissions)"
        else:
            rescue_keys = ["Enter"]
            rescue_desc = "Enter (accept/proceed)"
        print(f"[plan-mode-rescue] Agent {agent_id} stuck at interactive prompt "
              f"(pattern: {matched_pattern!r}). Sending {rescue_desc}.")

        for key in rescue_keys:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, key],
                capture_output=True, timeout=3,
            )
        time.sleep(2)

        # Re-check if agent is freed
        recheck = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-15"],
            capture_output=True, text=True, timeout=3,
        )
        recheck_text = (recheck.stdout or "").strip().lower() if recheck.returncode == 0 else ""
        still_stuck = any(p.lower() in recheck_text for p in _PLAN_RESCUE_PATTERNS)

        if not still_stuck:
            print(f"[plan-mode-rescue] Agent {agent_id} freed via {rescue_desc}.")
            try:
                append_message("system", "user",
                               f"[PLAN-MODE-RESCUE] Agent {agent_id} war in interaktivem Prompt "
                               f"blockiert (Pattern: {matched_pattern!r}). "
                               f"Automatisch per {rescue_desc} befreit.")
            except Exception:
                pass
            return True

        print(f"[plan-mode-rescue] Agent {agent_id} still stuck after {rescue_desc}.")
        try:
            append_message("system", "user",
                           f"[PLAN-MODE-RESCUE FAILED] Agent {agent_id} haengt in interaktivem "
                           f"Prompt (Pattern: {matched_pattern!r}). {rescue_desc} gesendet, "
                           f"Agent ist weiterhin blockiert. Manueller Eingriff noetig.")
        except Exception:
            pass
        return True

    except Exception as exc:
        print(f"[plan-mode-rescue] Error checking {agent_id}: {exc}")
        return False


_init_agent_health(
    system_shutdown_active=lambda: bool(_SYSTEM_STATUS.get("shutdown_active")),
    current_runtime_slot_map=current_runtime_slot_map,
    load_agents_conf=_load_agents_conf,
    team_config_getter=lambda: TEAM_CONFIG,
    all_tmux_agent_ids=_all_tmux_agent_ids,
    agent_state_lock=AGENT_STATE_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_busy=AGENT_BUSY,
    agent_last_seen=AGENT_LAST_SEEN,
    is_session_alive=is_session_alive,
    get_agent_engine=_get_agent_engine,
    check_codex_health=_check_codex_health,
    auto_restart_agents=lambda: AUTO_RESTART_AGENTS,
    agent_last_restart=_AGENT_LAST_RESTART,
    restart_cooldown=lambda: _RESTART_COOLDOWN,
    auto_restart_agent=_auto_restart_agent,
    start_agent_from_conf=_start_agent_from_conf,
    send_health_alert=_send_health_alert,
    is_agent_at_oauth_prompt=_is_agent_at_oauth_prompt,
    agent_auth_blocked=_AGENT_AUTH_BLOCKED,
    agent_oauth_failures=_AGENT_OAUTH_FAILURES,
    append_message=append_message,
    plan_mode_rescue_check=_plan_mode_rescue_check,
    agent_last_auto_register=_AGENT_LAST_AUTO_REGISTER,
    auto_register_cooldown=lambda: _AUTO_REGISTER_COOLDOWN,
    runtime_profile_capabilities=_runtime_profile_capabilities,
    seed_phantom_agent_registration=_seed_phantom_agent_registration,
    agent_last_nudge=_AGENT_LAST_NUDGE,
    nudge_cooldown=lambda: _NUDGE_COOLDOWN_SECONDS,
    message_cond=COND,
    cursors=CURSORS,
    messages_for_agent=messages_for_agent,
    is_agent_at_prompt_inline=_is_agent_at_prompt_inline,
    classify_agent_interactive_blocker=_classify_agent_interactive_blocker,
    nudge_idle_agent=_nudge_idle_agent,
    update_agent_status=update_agent_status,
    auto_cleanup_agents=_auto_cleanup_agents,
    grace_tokens=GRACE_TOKENS,
)

_init_restart_wake(
    team_config_getter=lambda: TEAM_CONFIG,
    team_config_lock_getter=lambda: TEAM_CONFIG_LOCK,
    is_session_alive=lambda agent_id: is_session_alive(agent_id),
    tmux_session_for=lambda agent_id: _tmux_session_for(agent_id),
    is_agent_at_prompt_inline=lambda agent_id: _is_agent_at_prompt_inline(agent_id),
    nudge_idle_agent=lambda agent_id, reason: _nudge_idle_agent(agent_id, reason),
    agent_last_nudge_getter=lambda: _AGENT_LAST_NUDGE,
    role_description_for=lambda agent_conf, fallback="": _role_description_for(agent_conf, fallback=fallback),
    team_members_for=lambda agent_id: _team_members_for(agent_id),
    create_agent_session=lambda **kwargs: create_agent_session(**kwargs),
    port_getter=lambda: PORT,
    append_message=lambda *args, **kwargs: append_message(*args, **kwargs),
    ws_broadcast=lambda event_type, payload: ws_broadcast(event_type, payload),
)

_init_restart_control(
    registered_agents_snapshot=_registered_agents_snapshot,
    agent_is_live=lambda agent_id: _agent_is_live(agent_id, stale_seconds=120.0),
    get_agent_engine=lambda agent_id: _get_agent_engine(agent_id),
    append_message=lambda *args, **kwargs: append_message(*args, **kwargs),
    ws_broadcast=lambda event_type, payload: ws_broadcast(event_type, payload),
    utc_now_iso=utc_now_iso,
    interrupt_agent=lambda agent_id, engine: interrupt_agent(agent_id, engine=engine),
    team_config_getter=lambda: TEAM_CONFIG,
)


def platform_status_snapshot() -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    for agent_id, reg in _registered_agents_snapshot().items():
        status = agent_connection_status(agent_id)
        agents.append({
            "agent_id": agent_id,
            "status": status,
            "last_heartbeat": reg.get("last_heartbeat_iso", ""),
            "registered_at": reg.get("registered_at", ""),
        })

    online_ids = sorted(agent["agent_id"] for agent in agents if agent["status"] != "disconnected")
    disconnected_ids = sorted(agent["agent_id"] for agent in agents if agent["status"] == "disconnected")
    return {
        "registered_count": len(agents),
        "online_count": len(online_ids),
        "disconnected_count": len(disconnected_ids),
        "online_ids": online_ids,
        "disconnected_ids": disconnected_ids,
        "agents": agents,
    }


def status_snapshot() -> dict[str, Any]:
    with LOCK:
        payload = {
            "status": "running",
            "port": PORT,
            "messages_total": len(MESSAGES),
            "cursors": dict(CURSORS),
            "uptime_seconds": round(time.time() - START_TS, 3),
        }
    payload["platform"] = platform_status_snapshot()
    payload["runtime"] = runtime_snapshot()
    return payload


def tail_log(name: str, lines: int) -> dict[str, Any]:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "", name)
    if not safe_name:
        raise ValueError("log name is required")
    path = os.path.join(AGENT_LOG_DIR, safe_name)
    if not path.endswith(".log"):
        path += ".log"

    # S8: Validate path stays within log directory
    if not is_within_directory(path, AGENT_LOG_DIR):
        raise ValueError("log path outside allowed directory")

    if not os.path.exists(path):
        return {"name": os.path.basename(path), "path": path, "lines": [], "count": 0}

    dq: deque[str] = deque(maxlen=max(1, min(lines, 2000)))
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            dq.append(line.rstrip("\n"))

    return {
        "name": os.path.basename(path),
        "path": path,
        "lines": list(dq),
        "count": len(dq),
    }


# ===== AGENT CONFIG (Instruction files + Permissions) =====

INSTRUCTION_FILE_BY_ENGINE: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "qwen": "QWEN.md",
}

CONFIG_ENGINES: set[str] = AVAILABLE_ENGINES - {"echo"}


# Auto-generate tracking


# ---------------------------------------------------------------------------
# Automation hierarchy permission check
# ---------------------------------------------------------------------------
def _check_hierarchy_permission(creator: str, target: str) -> bool:
    """Check if creator can create automations for target agent.

    Rules (from AUTOMATION_SPEC.md):
      - Level 1 (owner, manager): can create for ALL agents
      - Level 2: can create for self + Level 3 agents who report to them
      - Level 3: can only create for SELF
      - 'user' (Leo) can always delegate to anyone
    """
    if creator == "user" or creator == target:
        return True

    agents = TEAM_CONFIG.get("agents", [])
    creator_agent = None
    target_agent = None
    for a in agents:
        if a.get("id") == creator:
            creator_agent = a
        if a.get("id") == target:
            target_agent = a

    if not creator_agent or not target_agent:
        return False  # Unknown agents — deny

    creator_level = creator_agent.get("level", 99)
    target_level = target_agent.get("level", 99)

    # Level 1 can delegate to anyone
    if creator_level <= 1:
        return True

    # Level 2 can delegate to self + agents who report to them
    if creator_level <= 2:
        if target_agent.get("reports_to") == creator:
            return True
        # Can also delegate to same-level or lower if reports_to matches
        return target_level > creator_level

    # Level 3+: only self (already checked above)
    return False


_inject_ui_token = _frontend_inject_ui_token


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "BridgeServer/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep concise log lines.
        line = f"{self.client_address[0]} - {fmt % args}"
        print(line)

    _check_rate_limit = _http_check_rate_limit
    _send_cors_headers = _http_send_cors_headers

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    _respond = _http_respond
    _respond_bytes = _http_respond_bytes
    _parse_json_body = _http_parse_json_body

    _extract_auth_token = _request_extract_auth_token
    _resolve_auth_identity = _request_resolve_auth_identity
    _require_authenticated = _request_require_authenticated
    _require_platform_operator = _request_require_platform_operator
    _path_requires_auth_get = _request_path_requires_auth_get
    _path_requires_auth_post = _request_path_requires_auth_post

    _parse_multipart = _http_parse_multipart
    _serve_frontend_request = _frontend_serve_frontend_request

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except Exception as exc:
            try:
                self._respond(500, {"error": f"Internal server error: {type(exc).__name__}"})
            except Exception:
                pass
            print(f"[ERROR] Uncaught in do_GET {self.path}: {exc}")

    def _handle_get(self) -> None:
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"
        query = parse_qs(split.query, keep_blank_values=False)

        # Normalize /api/ prefix — Frontend uses /api/... but server routes don't
        if path.startswith("/api/"):
            path = "/" + path[5:]

        # S9: Rate-limiting
        if not self._check_rate_limit(path):
            self._respond(429, {"error": "rate limited", "retry_after": 60})
            return

        if BRIDGE_STRICT_AUTH and self._path_requires_auth_get(path):
            ok, _, _ = self._require_authenticated()
            if not ok:
                return

        if self._serve_frontend_request(path):
            return

        if path == "/status":
            self._respond(200, status_snapshot())
            return

        if path == "/health":
            self._respond(200, _compute_health())
            return

        if _handle_system_status_get(self, path, query):
            return

        if path == "/runtime":
            self._respond(200, runtime_snapshot())
            return

        if _handle_onboarding_get(self, path, query):
            return

        if path == "/activity":
            filter_agent = (query.get("agent_id") or [None])[0]
            now = time.time()
            idle_threshold = 300  # 5 minutes without activity = idle
            with LOCK:
                if filter_agent:
                    entry = AGENT_ACTIVITIES.get(filter_agent)
                    activities = [entry] if entry else []
                else:
                    activities = list(AGENT_ACTIVITIES.values())
                # Enrich with idle detection
                enriched = []
                for act in activities:
                    act_copy = dict(act)
                    aid = act_copy.get("agent_id", "")
                    reg = REGISTERED_AGENTS.get(aid, {})
                    last_hb = _agent_liveness_ts(aid, reg=reg)
                    act_ts_str = act_copy.get("timestamp", "")
                    # Parse activity timestamp to epoch
                    act_epoch = 0.0
                    if act_ts_str:
                        try:
                            act_epoch = datetime.fromisoformat(act_ts_str).timestamp()
                        except (ValueError, TypeError):
                            pass
                    # Agent is idle if: has heartbeat (alive) but no recent activity
                    if last_hb > 0 and (now - last_hb) < 120:
                        # Agent is alive
                        idle_seconds = now - act_epoch if act_epoch > 0 else 0.0
                        act_copy["idle"] = idle_seconds > idle_threshold
                        act_copy["idle_since_seconds"] = round(idle_seconds) if idle_seconds > idle_threshold else 0
                    else:
                        act_copy["idle"] = False
                        act_copy["idle_since_seconds"] = 0
                    enriched.append(act_copy)
            self._respond(200, {"activities": enriched})
            return

        if path == "/agents":
            status_filter = (query.get("status") or [None])[0]
            source = (query.get("source") or [None])[0]
            # Build lookups from team.json (name, role, description, active, engine, config_dir)
            _team_active: dict[str, bool] = {}
            _team_auto_start: dict[str, bool] = {}
            _team_names: dict[str, str] = {}
            _team_roles: dict[str, str] = {}
            _team_desc: dict[str, str] = {}
            _team_engine: dict[str, str] = {}
            _team_config_dir: dict[str, str] = {}
            _team_subscription_id: dict[str, str] = {}
            _team_model: dict[str, str] = {}
            _team_model_locked: dict[str, bool] = {}
            _team_levels: dict[str, Any] = {}
            _team_reports_to: dict[str, str] = {}
            _team_team: dict[str, str] = {}
            _team_avatar: dict[str, str] = {}
            _team_skills: dict[str, list[Any]] = {}
            _team_permissions: dict[str, Any] = {}
            with AGENT_STATE_LOCK:
                rl_set = set(AGENT_RATE_LIMITED)
            with RUNTIME_LOCK:
                runtime_state = dict(RUNTIME)
            runtime_profiles = _runtime_profile_map_from_state(runtime_state)
            if TEAM_CONFIG:
                for a in TEAM_CONFIG.get("agents", []):
                    aid = a.get("id", "")
                    _team_active[aid] = a.get("active", False)
                    _team_auto_start[aid] = a.get("auto_start", False)
                    _team_names[aid] = a.get("name", "")
                    _team_roles[aid] = a.get("role", "")
                    _team_desc[aid] = a.get("description", "")
                    _team_engine[aid] = a.get("engine", "claude")
                    _team_config_dir[aid] = a.get("config_dir", "")
                    _team_subscription_id[aid] = a.get("subscription_id", "")
                    _team_model[aid] = str(a.get("model", "") or "").strip()
                    _team_model_locked[aid] = a.get("model_locked", False)
                    _team_levels[aid] = a.get("level")
                    _team_reports_to[aid] = str(a.get("reports_to", ""))
                    _team_team[aid] = str(a.get("team", ""))
                    _team_avatar[aid] = str(a.get("avatar_url", ""))
                    _team_skills[aid] = list(a.get("skills", []))
                    _team_permissions[aid] = a.get("permissions", {})
            if source == "team":
                # Return all agents from team.json, merged with registration status
                agents_list = []
                if TEAM_CONFIG:
                    registered_agents = _registered_agents_snapshot()
                    registered_agent_ids = set(registered_agents)
                    # Build config_dir → subscription_id lookup for auto-derive
                    _sub_path_map: dict[str, str] = {}
                    for s in TEAM_CONFIG.get("subscriptions", []):
                        sp = s.get("path", "").rstrip("/")
                        if sp:
                            _sub_path_map[sp] = s.get("id", "")
                    for a in TEAM_CONFIG.get("agents", []):
                        aid = a.get("id", "")
                        reg = registered_agents.get(aid, {})
                        status = agent_connection_status(aid) if aid in registered_agent_ids else "offline"
                        online = status not in ("disconnected", "offline")
                        if status_filter and status != status_filter:
                            continue
                        a_state = _load_agent_state(aid)
                        # Auto-derive subscription_id from config_dir if not explicitly set
                        explicit_sub = a.get("subscription_id", "")
                        if not explicit_sub:
                            cd = a.get("config_dir", "").rstrip("/")
                            explicit_sub = _sub_path_map.get(cd, "")
                        agents_list.append({
                            "agent_id": aid,
                            "name": a.get("name", "") or runtime_profiles.get(aid, {}).get("name", ""),
                            "display_name": a.get("display_name", "") or runtime_profiles.get(aid, {}).get("display_name", ""),
                            "role": a.get("role", "") or runtime_profiles.get(aid, {}).get("role", "") or reg.get("role", ""),
                            "description": a.get("description", "") or runtime_profiles.get(aid, {}).get("description", ""),
                            "avatar_url": a.get("avatar_url", ""),
                            "skills": a.get("skills", []),
                            "permissions": a.get("permissions", {}),
                            "status": status,
                            "online": online,
                            "last_heartbeat": reg.get("last_heartbeat_iso", ""),
                            "registered_at": reg.get("registered_at", ""),
                            "capabilities": _capabilities_for_response(aid, reg),
                            "active": bool(a.get("active", False)),
                            "auto_start": bool(a.get("auto_start", False)),
                            "engine": a.get("engine", "") or runtime_profiles.get(aid, {}).get("engine", "") or reg.get("engine", "claude"),
                            "config_dir": a.get("config_dir", ""),
                            "subscription_id": explicit_sub,
                            "mode": a_state.get("mode", "normal"),
                            "level": a.get("level") if a.get("level") is not None else runtime_profiles.get(aid, {}).get("level"),
                            "reports_to": a.get("reports_to", "") or runtime_profiles.get(aid, {}).get("reports_to", ""),
                            "model": str(a.get("model", "") or runtime_profiles.get(aid, {}).get("model", "") or "").strip(),
                            "model_locked": a.get("model_locked", False),
                            "rate_limited": aid in rl_set,
                        })
                    configured_ids = {
                        str(a.get("id", "")).strip()
                        for a in TEAM_CONFIG.get("agents", [])
                        if str(a.get("id", "")).strip()
                    }
                    for aid, profile in runtime_profiles.items():
                        if aid in configured_ids:
                            continue
                        reg = registered_agents.get(aid, {})
                        status = agent_connection_status(aid) if aid in registered_agent_ids else "offline"
                        online = status not in ("disconnected", "offline")
                        if status_filter and status != status_filter:
                            continue
                        a_state = _load_agent_state(aid)
                        agents_list.append({
                            "agent_id": aid,
                            "name": str(profile.get("name", "")),
                            "display_name": str(profile.get("display_name", "")),
                            "role": str(profile.get("role", "") or reg.get("role", "")),
                            "description": str(profile.get("description", "")),
                            "avatar_url": "",
                            "skills": [],
                            "permissions": {},
                            "status": status,
                            "online": online,
                            "last_heartbeat": reg.get("last_heartbeat_iso", ""),
                            "registered_at": reg.get("registered_at", ""),
                            "capabilities": _capabilities_for_response(aid, reg),
                            "active": bool(profile.get("active", True)),
                            "auto_start": bool(profile.get("auto_start", False)),
                            "engine": str(profile.get("engine", "") or reg.get("engine", "claude")),
                            "config_dir": "",
                            "subscription_id": "",
                            "mode": a_state.get("mode", "normal"),
                            "level": profile.get("level"),
                            "reports_to": str(profile.get("reports_to", "")),
                            "model": str(profile.get("model", "") or ""),
                            "model_locked": False,
                            "rate_limited": aid in rl_set,
                        })
                self._respond(200, {"agents": agents_list})
                return
            agents_list = []
            registered_agents = _registered_agents_snapshot()
            all_agent_ids = set(registered_agents.keys()) | set(_team_active.keys())
            for agent_id in sorted(all_agent_ids):
                reg = registered_agents.get(agent_id, {})
                status = agent_connection_status(agent_id) if agent_id in registered_agents else "offline"
                online = status not in ("disconnected", "offline")
                if status_filter and status != status_filter:
                    continue
                a_state = _load_agent_state(agent_id)
                runtime_profile = runtime_profiles.get(agent_id, {})
                agents_list.append({
                    "agent_id": agent_id,
                    "name": _team_names.get(agent_id, "") or str(runtime_profile.get("name", "")),
                    "display_name": str(runtime_profile.get("display_name", "") or _team_names.get(agent_id, "")),
                    "role": _team_roles.get(agent_id, "") or str(runtime_profile.get("role", "")) or reg.get("role", ""),
                    "description": _team_desc.get(agent_id, "") or str(runtime_profile.get("description", "")),
                    "avatar_url": _team_avatar.get(agent_id, ""),
                    "skills": _team_skills.get(agent_id, []),
                    "permissions": _team_permissions.get(agent_id, {}),
                    "status": status,
                    "online": online,
                    "last_heartbeat": reg.get("last_heartbeat_iso", ""),
                    "registered_at": reg.get("registered_at", ""),
                    "capabilities": _capabilities_for_response(agent_id, reg),
                    "active": _team_active.get(agent_id, bool(runtime_profile.get("active", True))),
                    "auto_start": _team_auto_start.get(agent_id, bool(runtime_profile.get("auto_start", False))),
                    "engine": _team_engine.get(agent_id, "") or str(runtime_profile.get("engine", "")) or reg.get("engine", "claude"),
                    "config_dir": _team_config_dir.get(agent_id, ""),
                    "subscription_id": _team_subscription_id.get(agent_id, ""),
                    "model": str(_team_model.get(agent_id, "") or runtime_profile.get("model", "") or "").strip(),
                    "model_locked": _team_model_locked.get(agent_id, False),
                    "mode": a_state.get("mode", "normal"),
                    "level": _team_levels.get(agent_id) if _team_levels.get(agent_id) is not None else runtime_profile.get("level"),
                    "reports_to": _team_reports_to.get(agent_id, "") or str(runtime_profile.get("reports_to", "")),
                    "team": _team_team.get(agent_id, "") or str(runtime_profile.get("team", "")),
                    "rate_limited": agent_id in rl_set,
                    "paap_violations": _AGENT_PAAP_VIOLATIONS.get(agent_id, 0),
                })
            self._respond(200, {"agents": agents_list})
            return

        if _handle_skills_get(self, path, query):
            return

        if _handle_memory_get(self, path, query):
            return

        # GET /agents/{id} — single agent details with extended info
        _agent_detail_match = re.match(r"^/agents/([^/]+)$", path)
        if _agent_detail_match:
            agent_id = _agent_detail_match.group(1).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return
            reg = REGISTERED_AGENTS.get(agent_id)
            team_agent = None
            if TEAM_CONFIG:
                for a in TEAM_CONFIG.get("agents", []):
                    if a.get("id") == agent_id:
                        team_agent = a
                        break
            if not reg and team_agent is None:
                self._respond(404, {"error": f"agent '{agent_id}' not found in team.json or REGISTERED_AGENTS"})
                return
            status = agent_connection_status(agent_id) if reg else "offline"
            online = status not in ("disconnected", "offline")
            tmux_alive = _check_tmux_session(agent_id) if reg else False
            ctx_pct = _get_agent_context_pct(agent_id) if tmux_alive else None
            with LOCK:
                activity = AGENT_ACTIVITIES.get(agent_id)
            with AGENT_STATE_LOCK:
                busy = AGENT_BUSY.get(agent_id, False)
            hb_age = round(time.time() - reg.get("last_heartbeat", 0), 1) if reg else None
            runtime_profile = _runtime_profile_for_agent(agent_id)
            a_state = _load_agent_state(agent_id)
            cli_identity = _cli_identity_bundle(agent_id, reg if reg else {})
            response: dict[str, Any] = {
                "agent_id": agent_id,
                "role": str(runtime_profile.get("role", "") or reg.get("role", "") if reg else ""),
                "status": status,
                "online": online,
                "capabilities": _capabilities_for_response(agent_id, reg),
                "registered_at": reg.get("registered_at", "") if reg else "",
                "last_heartbeat": reg.get("last_heartbeat_iso", "") if reg else "",
                "last_heartbeat_age": hb_age,
                "tmux_alive": tmux_alive,
                "busy": busy,
                "mode": a_state.get("mode", "normal"),
                "active": bool(runtime_profile.get("active", True)),
                "engine": str(runtime_profile.get("engine", "") or (reg.get("engine", "") if reg else "")),
                "model": str(runtime_profile.get("model", "") or (reg.get("model", "") if reg else "") or ""),
                "resume_id": cli_identity.get("resume_id", ""),
                "workspace": cli_identity.get("workspace", ""),
                "project_root": cli_identity.get("project_root", ""),
                "home_dir": cli_identity.get("home_dir", ""),
                "instruction_path": cli_identity.get("instruction_path", ""),
                "cli_identity_source": cli_identity.get("cli_identity_source", ""),
                "phantom": bool(reg.get("phantom", False)) if reg else False,
            }
            if runtime_profile:
                response["name"] = str(runtime_profile.get("name", ""))
                response["display_name"] = str(runtime_profile.get("display_name", ""))
                response["description"] = str(runtime_profile.get("description", ""))
                response["level"] = runtime_profile.get("level")
                response["reports_to"] = str(runtime_profile.get("reports_to", ""))
                response["team"] = str(runtime_profile.get("team", ""))
                response["engine"] = str(runtime_profile.get("engine", ""))
                response["model"] = str(runtime_profile.get("model", "") or "")
            if ctx_pct is not None:
                response["context_pct"] = ctx_pct
            if activity:
                response["activity"] = activity
            # Merge team.json fields (Agent-Builder)
            if team_agent is not None:
                response["name"] = team_agent.get("name", "")
                response["display_name"] = team_agent.get("display_name", "")
                response["description"] = team_agent.get("description", "")
                response["avatar_url"] = team_agent.get("avatar_url", "")
                response["skills"] = team_agent.get("skills", [])
                response["permissions"] = team_agent.get("permissions", {})
                response["level"] = team_agent.get("level")
                response["reports_to"] = team_agent.get("reports_to", "")
                response["active"] = bool(team_agent.get("active", False))
                response["auto_start"] = team_agent.get("auto_start", False)
                response["engine"] = team_agent.get("engine", "claude")
                response["config_dir"] = team_agent.get("config_dir", "")
                response["subscription_id"] = team_agent.get("subscription_id", "")
                response["model"] = str(team_agent.get("model", "") or "").strip()
                response["model_locked"] = team_agent.get("model_locked", False)
            elif "active" not in response:
                response["active"] = online
            # PAAP compliance stats
            response["paap_violations"] = _AGENT_PAAP_VIOLATIONS.get(agent_id, 0)
            self._respond(200, response)
            return

        # GET /agents/{id}/persistence — persistence health check per agent
        _persist_health_match = re.match(r"^/agents/([^/]+)/persistence$", path)
        if _persist_health_match:
            agent_id = _persist_health_match.group(1).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return
            agent_home = _get_agent_home_dir(agent_id)
            if not agent_home:
                self._respond(404, {"error": f"agent '{agent_id}' has no home_dir"})
                return

            def _check_file(filepath: str) -> dict[str, Any]:
                """Check a file's existence, size, lines, symlink status."""
                result: dict[str, Any] = {"exists": False}
                try:
                    p = Path(filepath)
                    if not p.exists() and not p.is_symlink():
                        return result
                    result["exists"] = True
                    result["is_symlink"] = p.is_symlink()
                    if p.is_symlink():
                        result["symlink_target"] = str(p.resolve())
                    stat = p.stat()
                    result["size_bytes"] = stat.st_size
                    result["age_seconds"] = round(time.time() - stat.st_mtime)
                    result["modified_iso"] = datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat()
                    try:
                        lines = p.read_text(encoding="utf-8").count("\n") + 1
                        result["lines"] = lines
                    except (UnicodeDecodeError, OSError):
                        pass
                except OSError:
                    pass
                return result

            # Build persistence health response
            health: dict[str, Any] = {"agent_id": agent_id}
            reg = REGISTERED_AGENTS.get(agent_id)
            cli_identity = _cli_identity_bundle(agent_id, reg if reg else {})
            layout_seed = (
                cli_identity.get("workspace", "")
                or cli_identity.get("project_root", "")
                or agent_home
            )
            layout = resolve_agent_cli_layout(layout_seed, agent_id)
            engine = _get_agent_engine(agent_id)

            # SOUL.md — CLI workspace is canonical; project root is fallback.
            soul_path = first_existing_path(soul_candidates(agent_home, agent_id))
            soul_info = _check_file(soul_path) if soul_path else {"exists": False}
            if soul_path:
                soul_info["path"] = soul_path
            # Detect generic template (< 2KB = likely template)
            if soul_info.get("exists") and soul_info.get("size_bytes", 0) < 2048:
                soul_info["warning"] = "small_file_may_be_template"
            health["soul_md"] = soul_info

            # Instruction file — engine-specific, resolved from CLI workspace first.
            instruction_filename = detect_instruction_filename(agent_home, agent_id, engine)
            instruction_path = first_existing_path(
                instruction_candidates(agent_home, agent_id, engine)
            )
            instruction_info = _check_file(instruction_path) if instruction_path else {"exists": False}
            if instruction_path:
                instruction_info["path"] = instruction_path
            instruction_info["filename"] = instruction_filename
            health["instruction_md"] = instruction_info
            # Backward-compatible alias used by older UI/tests.
            health["claude_md"] = dict(instruction_info)

            # CONTEXT_BRIDGE.md — workspace first, home fallback, choose freshest existing file.
            best_cb_path = first_existing_path(context_bridge_candidates(agent_home, agent_id))
            best_cb: dict[str, Any] = _check_file(best_cb_path) if best_cb_path else {"exists": False}
            if best_cb_path:
                best_cb["path"] = best_cb_path
            # Try to extract "Stand:" date from content
            if best_cb.get("exists") and best_cb.get("path"):
                try:
                    content = Path(best_cb["path"]).read_text(encoding="utf-8")
                    stand_match = re.search(r"Stand:\s*(\S+)", content)
                    if stand_match:
                        best_cb["stand_date"] = stand_match.group(1)
                except OSError:
                    pass
            health["context_bridge_md"] = best_cb

            # MEMORY.md — use runtime SoT for config_dir
            config_dir = _get_runtime_config_dir(agent_id)
            health["config_dir"] = config_dir
            health["config_dir_source"] = "runtime" if config_dir else "fallback"
            memory_info: dict[str, Any] = {"exists": False}
            if config_dir or agent_home:
                mem_path = find_agent_memory_path(agent_id, agent_home, config_dir)
                if mem_path:
                    memory_info = _check_file(mem_path)
                    memory_info["path"] = mem_path
            health["workspace"] = cli_identity.get("workspace", "") or layout["workspace"]
            health["project_root"] = cli_identity.get("project_root", "") or layout["project_root"]
            health["home_dir"] = cli_identity.get("home_dir", "") or layout["home_dir"]
            health["resume_id"] = cli_identity.get("resume_id", "")
            health["instruction_path"] = cli_identity.get("instruction_path", "")
            health["cli_identity_source"] = cli_identity.get("cli_identity_source", "")
            health["memory_md"] = memory_info

            # Registration info
            if reg:
                health["last_registration"] = reg.get("registered_at", "")
                health["last_heartbeat"] = reg.get("last_heartbeat_iso", "")
            else:
                health["registered"] = False

            # Context restore timestamp (from agent state)
            a_state = _load_agent_state(agent_id)
            if a_state.get("last_context_restore"):
                health["last_context_restore"] = a_state["last_context_restore"]

            # Overall health score
            checks = [
                health["soul_md"].get("exists", False),
                health["instruction_md"].get("exists", False),
                health["context_bridge_md"].get("exists", False),
                health["memory_md"].get("exists", False),
            ]
            health["score"] = f"{sum(checks)}/{len(checks)}"
            health["healthy"] = all(checks)

            self._respond(200, health)
            return

        # GET /agents/{id}/memory-health — focused memory/context health check
        _mem_health_match = re.match(r"^/agents/([^/]+)/memory-health$", path)
        if _mem_health_match:
            agent_id = _mem_health_match.group(1).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return
            result = _check_agent_memory_health(agent_id)
            if result.get("error"):
                self._respond(404, result)
                return
            self._respond(200, result)
            return

        # GET /agents/{id}/next-action — decomposed action prompt for non-Claude engines
        # Returns a concrete, single-step instruction based on pending messages/tasks.
        # Designed for Codex/Qwen poll daemons to inject actionable prompts.
        _next_action_match = re.match(r"^/agents/([^/]+)/next-action$", path)
        if _next_action_match:
            agent_id = _next_action_match.group(1).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return

            # 1. Check pending (unread) messages
            pending_msgs: list[dict[str, Any]] = []
            with COND:
                cursor = CURSORS.get(agent_id, 0)
                pending_msgs = messages_for_agent(cursor, agent_id)

            # 2. Check tasks: assigned to agent (claimed/acked) or available (created)
            my_tasks: list[dict[str, Any]] = []
            available_tasks: list[dict[str, Any]] = []
            with TASK_LOCK:
                for t in TASKS.values():
                    st = t.get("state", "")
                    if t.get("assigned_to") == agent_id and st in ("claimed", "acked"):
                        my_tasks.append(t)
                    elif st == "created" and not t.get("assigned_to"):
                        available_tasks.append(t)

            # 3. Build actionable prompt
            prompt_parts: list[str] = []
            action_type = "idle"

            # Priority 1: Pending messages (newest first, max 3)
            real_msgs = [m for m in pending_msgs
                         if m.get("from") not in ("system",)
                         and not str(m.get("content", "")).startswith("[HEARTBEAT")]
            if real_msgs:
                action_type = "message"
                msg = real_msgs[-1]  # newest
                sender = msg.get("from", "unknown")
                content = str(msg.get("content", ""))[:500]
                prompt_parts.append(
                    f"You have {len(real_msgs)} pending message(s). "
                    f"Call bridge_receive() now. The newest is from '{sender}'.\n\n"
                    f"Message preview: {content}\n\n"
                    "INSTRUCTIONS — do ALL of these steps:\n"
                    "1. Call bridge_receive() to get the full messages\n"
                    "2. For EACH message, do what it asks:\n"
                    "   - If it asks to read/review code: use Read tool on the specified files, analyze, then bridge_send your findings\n"
                    "   - If it asks to implement something: write the code, test it, then bridge_send the result\n"
                    "   - If it asks a question: answer it via bridge_send\n"
                    f"3. Send your response via bridge_send(to='{sender}', content='your detailed response')\n"
                    "Do NOT just acknowledge — actually DO the work."
                )

            # Priority 2: Assigned tasks (in-progress)
            elif my_tasks:
                action_type = "task"
                task = my_tasks[0]
                title = str(task.get("title", ""))[:200]
                desc = str(task.get("description", ""))[:500]
                tid = task.get("task_id", "")
                creator = task.get("created_by", "unknown")
                prompt_parts.append(
                    f"You have an active task: '{title}'\n"
                    f"Task ID: {tid}\n"
                    f"Description: {desc}\n\n"
                    "INSTRUCTIONS — do ALL of these steps:\n"
                    "1. Read the task description carefully\n"
                    "2. Break it into concrete steps\n"
                    "3. Execute each step (read files, write code, run tests)\n"
                    "4. When done: bridge_task_done(task_id='" + tid + "', "
                    "result_summary='your detailed results')\n"
                    f"5. Send result to creator: bridge_send(to='{creator}', "
                    "content='Task done: [summary]')\n"
                    "Do NOT just acknowledge — actually DO the work."
                )

            # Priority 3: Available tasks in queue
            elif available_tasks:
                action_type = "available_task"
                task = available_tasks[0]
                title = str(task.get("title", ""))[:200]
                tid = task.get("task_id", "")
                prompt_parts.append(
                    f"There is an open task in the queue: '{title}'\n"
                    f"Task ID: {tid}\n\n"
                    "If this task matches your skills:\n"
                    f"1. Claim it: bridge_task_claim(task_id='{tid}')\n"
                    f"2. Acknowledge: bridge_task_ack(task_id='{tid}')\n"
                    "3. Execute the work\n"
                    f"4. Complete: bridge_task_done(task_id='{tid}', result_summary='...')\n"
                    "If it does not match your role, call bridge_receive() instead."
                )

            self._respond(200, {
                "agent_id": agent_id,
                "has_action": action_type != "idle",
                "action_type": action_type,
                "prompt": "\n".join(prompt_parts) if prompt_parts else "",
                "pending_messages": len(real_msgs) if action_type == "message" else len(pending_msgs),
                "active_tasks": len(my_tasks),
                "available_tasks": len(available_tasks),
            })
            return

        # GET /tasks/summary — aggregated project overview (tasks per team/project, progress)
        if path == "/tasks/summary":
            with TASK_LOCK:
                all_tasks = [t for t in TASKS.values() if t.get("state") != "deleted"]
            # Group by team field
            projects: dict[str, dict[str, Any]] = {}
            for t in all_tasks:
                team_name = (str(t.get("team") or "")).strip() or "(unassigned)"
                if team_name not in projects:
                    projects[team_name] = {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "failed": 0, "pending": 0, "agents": set()}
                p = projects[team_name]
                p["total"] += 1
                state = t.get("state", "created")
                # V4: Tasks with blocker_reason count as blocked (unless done/failed)
                if t.get("blocker_reason") and state not in ("done", "failed"):
                    p["blocked"] += 1
                elif state == "done":
                    p["done"] += 1
                elif state in ("claimed", "acked"):
                    p["in_progress"] += 1
                elif state == "failed":
                    p["failed"] += 1
                else:  # created without blocker
                    p["pending"] += 1
                assigned = (str(t.get("assigned_to") or "")).strip()
                if assigned:
                    p["agents"].add(assigned)
            # Build response
            project_list = []
            for name, counts in sorted(projects.items()):
                total = counts["total"]
                done = counts["done"]
                progress_pct = round((done / total) * 100) if total > 0 else 0
                project_list.append({
                    "name": name,
                    "total_tasks": total,
                    "done": done,
                    "in_progress": counts["in_progress"],
                    "pending": counts["pending"],
                    "blocked": counts["blocked"],
                    "failed": counts["failed"],
                    "progress_pct": progress_pct,
                    "agents": sorted(counts["agents"]),
                })
            self._respond(200, {"projects": project_list, "total_tasks": len(all_tasks)})
            return

        # GET /task/queue — list tasks, optionally filtered by state, agent, team
        # F-14: supports ?limit=N&offset=M for pagination
        # P0-CAP: ?check_agent=X adds _claimability per task; adds backpressure to response
        if path == "/task/queue":
            state_filter = (query.get("state") or [None])[0]
            agent_filter = (query.get("agent_id") or [None])[0]
            check_agent = (query.get("check_agent") or [None])[0]  # P0-CAP: agent to check claimability for
            team_filter = (query.get("team") or [None])[0]
            priority_sort = (query.get("priority") or [None])[0]  # "desc" for high-first
            view_mode = (query.get("view") or [None])[0]
            include_blockers = (query.get("include_blockers") or ["false"])[0] == "true"
            # V4: ?blocked=true/false — filter tasks by blocker_reason presence
            blocked_filter = (query.get("blocked") or [None])[0]  # "true" or "false"
            try:
                limit = int((query.get("limit") or [0])[0])
            except (ValueError, TypeError):
                limit = 0
            try:
                offset = int((query.get("offset") or [0])[0])
            except (ValueError, TypeError):
                offset = 0
            # V5: ?include_deleted=true to show soft-deleted tasks
            include_deleted = (query.get("include_deleted") or ["false"])[0] == "true"
            with TASK_LOCK:
                result_tasks = []
                for t in TASKS.values():
                    # V5: Hide deleted tasks unless explicitly requested
                    if t.get("state") == "deleted" and not include_deleted:
                        if not state_filter or state_filter != "deleted":
                            continue
                    if state_filter and t["state"] != state_filter:
                        continue
                    if agent_filter and t.get("assigned_to") != agent_filter:
                        continue
                    if team_filter and t.get("team") != team_filter:
                        continue
                    # V4: blocked filter — true=only blocked, false=only unblocked
                    if blocked_filter == "true" and not t.get("blocker_reason"):
                        continue
                    if blocked_filter == "false" and t.get("blocker_reason"):
                        continue
                    result_tasks.append(t)
            # Sort: priority desc (if requested), then created_at asc
            if priority_sort == "desc":
                result_tasks.sort(key=lambda x: (-x.get("priority", 1), x.get("created_at", "")))
            else:
                result_tasks.sort(key=lambda x: x.get("created_at", ""))
            total = len(result_tasks)
            page_tasks = result_tasks[offset:] if offset > 0 else list(result_tasks)
            if limit > 0:
                page_tasks = page_tasks[:limit]
            page_tasks = [copy.deepcopy(t) for t in page_tasks]
            if view_mode == "board":
                board: dict[str, list] = {}
                # V4: Add "blocked" column for tasks with blocker_reason
                for state in ("created", "claimed", "acked", "done", "failed", "blocked"):
                    board[state] = []
                for t in page_tasks:
                    s = t.get("state", "created")
                    task_entry = dict(t)
                    if include_blockers:
                        agent = t.get("assigned_to")
                        if agent and agent in AGENT_ACTIVITIES:
                            act = AGENT_ACTIVITIES[agent]
                            if act.get("blocked"):
                                task_entry["_blocker"] = {
                                    "blocked": True,
                                    "reason": act.get("blocker_reason"),
                                    "since": act.get("timestamp"),
                                }
                    # V4: Tasks with blocker_reason go to "blocked" column regardless of state
                    if t.get("blocker_reason") and s not in ("done", "failed"):
                        board["blocked"].append(task_entry)
                    else:
                        if s not in board:
                            board[s] = []
                        board[s].append(task_entry)
                counts = {s: len(tasks) for s, tasks in board.items()}
                self._respond(200, {"board": board, "counts": counts, "total": total})
                return
            result_tasks = page_tasks

            # P0-CAP: If check_agent is set, annotate each task with _claimability
            backpressure: dict[str, Any] | None = None
            if check_agent:
                ca_registered, ca_caps = _get_registered_agent_capabilities(check_agent)
                # Backpressure: how many tasks does this agent already have active?
                active_count = 0
                with TASK_LOCK:
                    for t in TASKS.values():
                        if t.get("assigned_to") == check_agent and t.get("state") in ("claimed", "acked"):
                            active_count += 1
                at_cap = active_count >= TASK_MAX_ACTIVE_PER_AGENT
                backpressure = {
                    "agent": check_agent,
                    "registered": ca_registered,
                    "active_tasks": active_count,
                    "max_active": TASK_MAX_ACTIVE_PER_AGENT,
                    "at_capacity": at_cap,
                }
                for t in result_tasks:
                    req_caps = _task_required_capabilities(t)
                    t_assigned = t.get("assigned_to")
                    t_state = t.get("state", "")
                    # Determine claimability
                    if t_state != "created":
                        t["_claimability"] = {"claimable": False, "reason": f"state={t_state}"}
                    elif t_assigned and t_assigned != check_agent:
                        t["_claimability"] = {"claimable": False, "reason": f"assigned_to={t_assigned}"}
                    elif at_cap:
                        t["_claimability"] = {"claimable": False, "reason": "agent_at_capacity"}
                    elif req_caps:
                        matches, missing = _capability_match(req_caps, ca_caps, agent_registered=ca_registered)
                        if matches:
                            t["_claimability"] = {"claimable": True, "reason": "caps_match", "required": req_caps}
                        else:
                            t["_claimability"] = {"claimable": False, "reason": "missing_capabilities", "required": req_caps, "missing": missing}
                    else:
                        claimable = t_state == "created" and (not t_assigned or t_assigned == check_agent)
                        t["_claimability"] = {"claimable": claimable, "reason": "no_caps_required" if claimable else f"assigned_to={t_assigned}"}

            resp: dict[str, Any] = {"tasks": result_tasks, "count": len(result_tasks), "total": total}
            if backpressure:
                resp["backpressure"] = backpressure
            self._respond(200, resp)
            return

        # GET /task/{id}/history — audit trail for a task (Diff-friendly)
        # ===== TASK TRACKER (Leo-Direktive) =====
        # GET /task/tracker — Audit-View aller Tasks mit Lifecycle-Transparenz
        if path == "/task/tracker":
            agent_filter = (query.get("agent") or [None])[0]
            status_filter = (query.get("status") or [None])[0]
            from_filter = (query.get("from") or [None])[0]
            to_filter = (query.get("to") or [None])[0]
            fmt = (query.get("format") or ["json"])[0]
            try:
                limit = min(int((query.get("limit") or [100])[0]), 500)
            except (ValueError, TypeError):
                limit = 100

            def _extract_state_ts(history: list, state: str) -> str | None:
                """Extract first timestamp for a given state from state_history."""
                for entry in history:
                    if entry.get("state") == state:
                        return entry.get("at")
                return None

            def _extract_state_by(history: list, state: str) -> str | None:
                """Extract 'by' for a given state from state_history."""
                for entry in history:
                    if entry.get("state") == state:
                        return entry.get("by")
                return None

            def _calc_duration(created: str | None, done: str | None) -> int | None:
                """Calculate duration in minutes between two ISO timestamps."""
                if not created or not done:
                    return None
                try:
                    from datetime import datetime as _dt
                    t_created = _dt.fromisoformat(created.replace("Z", "+00:00"))
                    t_done = _dt.fromisoformat(done.replace("Z", "+00:00"))
                    return max(0, int((t_done - t_created).total_seconds() / 60))
                except (ValueError, TypeError):
                    return None

            with TASK_LOCK:
                tasks_list = list(TASKS.values())

            # Filter
            result_tasks = []
            for t in tasks_list:
                if t.get("state") == "deleted":
                    continue
                if status_filter and t.get("state") != status_filter:
                    continue
                if agent_filter and t.get("assigned_to") != agent_filter and t.get("created_by") != agent_filter:
                    continue
                if from_filter:
                    if t.get("created_at", "") < from_filter:
                        continue
                if to_filter:
                    if t.get("created_at", "") > to_filter:
                        continue
                result_tasks.append(t)

            # Sort: newest first
            result_tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            result_tasks = result_tasks[:limit]

            # Build audit entries
            audit_tasks = []
            for t in result_tasks:
                history = t.get("state_history", [])
                claimed_at = _extract_state_ts(history, "claimed")
                acked_at = _extract_state_ts(history, "acked")
                done_at = t.get("done_at") or _extract_state_ts(history, "done")
                done_by = _extract_state_by(history, "done")
                created_at = t.get("created_at")
                duration_minutes = _calc_duration(created_at, done_at)

                # P0-CAP: required_capabilities + scheduling_status
                req_caps = _task_required_capabilities(t)
                t_state = t.get("state", "")
                t_assigned = t.get("assigned_to")
                if t_state in ("done", "failed"):
                    sched_status = "completed" if t_state == "done" else "failed"
                elif t_state in ("claimed", "acked"):
                    sched_status = "in_progress"
                elif t_state == "created" and t_assigned:
                    sched_status = "assigned_pending_claim"
                elif t_state == "created" and req_caps:
                    sched_status = "awaiting_capable_agent"
                elif t_state == "created":
                    sched_status = "schedulable"
                else:
                    sched_status = t_state

                entry = {
                    "task_id": t.get("task_id"),
                    "title": t.get("title"),
                    "type": t.get("type"),
                    "state": t.get("state"),
                    "priority": t.get("priority", 1),
                    "created_by": t.get("created_by"),
                    "assigned_to": t.get("assigned_to"),
                    "required_capabilities": req_caps,
                    "scheduling_status": sched_status,
                    "created_at": created_at,
                    "claimed_at": claimed_at,
                    "acked_at": acked_at,
                    "done_at": done_at,
                    "done_by": done_by,
                    "result_code": t.get("result_code"),
                    "result_summary": t.get("result_summary"),
                    "evidence": t.get("evidence"),
                    "verified_by": t.get("verified_by"),
                    "verified_at": t.get("verified_at"),
                    "verification_note": t.get("verification_note"),
                    "duration_minutes": duration_minutes,
                    "labels": t.get("labels", []),
                    "team": t.get("team"),
                }
                audit_tasks.append(entry)

            if fmt == "csv":
                import io, csv as csv_mod
                output = io.StringIO()
                fieldnames = [
                    "task_id", "title", "type", "state", "priority",
                    "created_by", "assigned_to", "created_at", "done_at",
                    "done_by", "result_code", "result_summary",
                    "evidence_type", "evidence_ref", "verified_by",
                    "verified_at", "duration_minutes",
                ]
                writer = csv_mod.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                for at in audit_tasks:
                    ev = at.get("evidence") or {}
                    writer.writerow({
                        "task_id": at["task_id"],
                        "title": at["title"],
                        "type": at["type"],
                        "state": at["state"],
                        "priority": at["priority"],
                        "created_by": at["created_by"],
                        "assigned_to": at["assigned_to"],
                        "created_at": at["created_at"],
                        "done_at": at["done_at"],
                        "done_by": at["done_by"],
                        "result_code": at["result_code"],
                        "result_summary": at["result_summary"],
                        "evidence_type": ev.get("type", ""),
                        "evidence_ref": ev.get("ref", ""),
                        "verified_by": at["verified_by"],
                        "verified_at": at["verified_at"],
                        "duration_minutes": at["duration_minutes"],
                    })
                csv_text = output.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=task_tracker.csv")
                self.end_headers()
                self.wfile.write(csv_text.encode("utf-8"))
                return

            self._respond(200, {"ok": True, "count": len(audit_tasks), "tasks": audit_tasks})
            return

        _task_history_match = re.match(r"^/task/([^/]+)/history$", path)
        if _task_history_match:
            task_id = _task_history_match.group(1)
            with TASK_LOCK:
                task = TASKS.get(task_id)
            if not task:
                self._respond(404, {"error": f"task '{task_id}' not found"})
                return
            history = task.get("state_history", [])
            self._respond(200, {
                "task_id": task_id,
                "title": task.get("title"),
                "history": history,
                "total_events": len(history),
            })
            return

        # GET /task/{id} — single task details
        _task_detail_match = re.match(r"^/task/([^/]+)$", path)
        if _task_detail_match:
            task_id = _task_detail_match.group(1)
            with TASK_LOCK:
                task = TASKS.get(task_id)
            if not task:
                self._respond(404, {"error": f"task '{task_id}' not found"})
                return
            self._respond(200, {"task": task})
            return

        # ===== V3 SCOPE-LOCK GET ENDPOINTS =====

        # GET /scope/locks — all active scope locks
        if path == "/scope/locks":
            with SCOPE_LOCK_LOCK:
                locks = list(SCOPE_LOCKS.values())
            self._respond(200, {"locks": locks, "count": len(locks)})
            return

        # GET /scope/check?paths=path1,path2 — check if paths are free
        if path == "/scope/check":
            raw_paths = (query.get("paths") or [""])[0]
            if not raw_paths:
                self._respond(400, {"error": "paths parameter required (comma-separated)"})
                return
            paths_to_check = [p.strip() for p in raw_paths.split(",") if p.strip()]
            result: dict[str, Any] = {}
            with SCOPE_LOCK_LOCK:
                now_iso = utc_now_iso()
                for p in paths_to_check:
                    norm = _normalize_scope_path(p)
                    lock = SCOPE_LOCKS.get(norm)
                    if lock:
                        # Check if expired
                        try:
                            exp = datetime.fromisoformat(lock["expires_at"])
                            if datetime.fromisoformat(now_iso) > exp:
                                result[p] = None  # expired = free
                                continue
                        except (ValueError, KeyError):
                            pass
                        result[p] = {
                            "locked_by": lock["agent_id"],
                            "label": lock["label"],
                            "task_id": lock["task_id"],
                            "expires_at": lock["expires_at"],
                        }
                    else:
                        # Check directory-level containment
                        found = False
                        for locked_path, lock_info in SCOPE_LOCKS.items():
                            if lock_info["lock_type"] == "directory" and norm.startswith(locked_path + os.sep):
                                try:
                                    exp = datetime.fromisoformat(lock_info["expires_at"])
                                    if datetime.fromisoformat(now_iso) > exp:
                                        continue
                                except (ValueError, KeyError):
                                    pass
                                result[p] = {
                                    "locked_by": lock_info["agent_id"],
                                    "label": lock_info["label"],
                                    "task_id": lock_info["task_id"],
                                    "expires_at": lock_info["expires_at"],
                                    "via_directory": locked_path,
                                }
                                found = True
                                break
                        if not found:
                            result[p] = None
            self._respond(200, {"paths": result})
            return

        # ===== END V3 SCOPE-LOCK GET ENDPOINTS =====

        if _handle_event_subscriptions_get(self, path):
            return

        if _handle_workflows_get(self, path, query):
            return

        if _handle_metrics_get(self, path, query):
            return

        # ===== GIT ADVISORY LOCKS (RB2: Multi-User Collaboration) =====

        # GET /git/locks — list all active locks (delegates to git_collaboration)
        if _handle_git_lock_get(self, path):
            return

        # ===== CREDENTIAL STORE ENDPOINTS =====
        if _handle_credentials_get(self, path):
            return

        if _handle_meta_get(self, path, split.query):
            return

        if _handle_capability_library_get(self, path, split.query):
            return

        if _handle_shared_tools_get(self, path):
            return

        if _handle_guardrails_get(self, path, split.query):
            return

        # ===== EXECUTION JOURNAL GET ENDPOINTS =====

        if _handle_domain_get(self, path):
            return

        if _handle_data_get(self, path):
            return

        if _handle_creator_get(self, path):
            return

        # ===== VOICE / TELEPHONY GET ENDPOINTS =====

        if path == "/voice/status":
            if TELEPHONY_CLIENT is None:
                self._respond(200, {
                    "available": False,
                    "twilio": False,
                    "elevenlabs": False,
                    "reason": "No telephony credentials configured",
                })
            else:
                status = TELEPHONY_CLIENT.status()
                self._respond(200, {
                    "available": status["twilio_configured"] or status["elevenlabs_configured"],
                    "twilio": status["twilio_configured"],
                    "elevenlabs": status["elevenlabs_configured"],
                    "from_number": status["from_number"],
                    "total_calls": status["total_calls"],
                    "total_sms": status["total_sms"],
                })
            return

        if path.startswith("/voice/call/"):
            call_sid = path[len("/voice/call/"):]
            if not call_sid:
                self._respond(400, {"error": "missing call_sid"})
                return
            if TELEPHONY_CLIENT is None:
                self._respond(200, {"available": False, "error": "Telephony not configured"})
                return
            result = TELEPHONY_CLIENT.get_call_status(call_sid)
            self._respond(200, result.to_dict())
            return

        if _handle_execution_get(self, path, split.query):
            return

        if _handle_subscriptions_get(self, path):
            return

        # ===== CHAT FILE SERVING =====

        if _handle_chat_files_get(self, path):
            return

        if _handle_projects_get(self, path, split.query):
            return

        if _handle_whiteboard_get(self, path, query):
            return

        if _handle_teamlead_scope_get(self, path, query):
            return

        if path == "/pick-directory":
            initial = (query.get("initial") or [None])[0] or os.path.expanduser("~")
            try:
                import shutil
                cmd: list[str]
                if shutil.which("zenity"):
                    cmd = ["zenity", "--file-selection", "--directory",
                           f"--filename={initial}/"]
                elif shutil.which("kdialog"):
                    cmd = ["kdialog", "--getexistingdirectory", initial]
                else:
                    cmd = [sys.executable, "-c",
                           "import tkinter as tk; from tkinter import filedialog; "
                           "root = tk.Tk(); root.withdraw(); "
                           f"p = filedialog.askdirectory(initialdir={initial!r}); "
                           "print(p if p else '')"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                chosen = result.stdout.strip()
                if chosen and os.path.isdir(chosen):
                    self._respond(200, {"ok": True, "path": chosen})
                else:
                    self._respond(200, {"ok": False, "path": ""})
            except Exception as exc:
                self._respond(500, {"ok": False, "error": str(exc)})
            return

        if _handle_logs_get(self, path, query):
            return

        if path == "/agent/config":
            project_path = validate_project_path((query.get("project_path") or [None])[0], PROJECTS_BASE_DIR)
            if not project_path:
                self._respond(403, {"error": "path outside allowed directory"})
                return
            engine = str((query.get("engine") or ["claude"])[0]).strip().lower()
            slot = str((query.get("slot") or ["a"])[0]).strip().lower()
            if engine not in CONFIG_ENGINES:
                self._respond(400, {"error": f"unsupported engine: {engine}", "supported": sorted(CONFIG_ENGINES)})
                return
            inst_file = agent_instruction_file(project_path, engine)
            inst_exists = os.path.isfile(inst_file)
            inst_content = ""
            if inst_exists:
                try:
                    inst_content = Path(inst_file).read_text(encoding="utf-8")
                except OSError:
                    inst_content = ""
            permissions = read_agent_permissions(project_path, engine)
            self._respond(200, {
                "ok": True,
                "engine": engine,
                "slot": slot,
                "project_path": project_path,
                "instruction_file": inst_file,
                "instruction_filename": os.path.basename(inst_file),
                "instruction_exists": inst_exists,
                "instruction_content": inst_content,
                "permissions": permissions,
            })
            return

        if path == "/messages":
            limit = parse_limit((query.get("limit") or [None])[0])
            raw_agent_filter = (query.get("agent_id") or [None])[0]
            agent_filter = str(raw_agent_filter).strip() if raw_agent_filter else None
            with LOCK:
                message_source = MESSAGES
                if agent_filter:
                    message_source = [
                        m for m in MESSAGES
                        if str(m.get("from", "")).strip() == agent_filter
                        or str(m.get("to", "")).strip() == agent_filter
                    ]
                if limit is None:
                    message_list = list(message_source)
                else:
                    message_list = list(message_source[-limit:])
            self._respond(200, {"messages": message_list, "count": len(message_list)})
            return

        if path == "/history":
            limit = parse_limit((query.get("limit") or [None])[0])
            after_id = parse_after_id((query.get("after_id") or [None])[0])
            raw_team_filter = (query.get("team") or [None])[0]
            team_filter = str(raw_team_filter).strip() if raw_team_filter else None
            raw_since = (query.get("since") or [None])[0]
            since_ts = str(raw_since).strip() if raw_since else None
            with LOCK:
                history_source = MESSAGES
                if after_id is not None:
                    history_source = [m for m in MESSAGES if int(m.get("id", -1)) > after_id]
                if since_ts:
                    history_source = [m for m in history_source if m.get("timestamp", "") >= since_ts]
                if team_filter:
                    history_source = [m for m in history_source if m.get("team") == team_filter]

                if limit is None:
                    history = list(history_source)
                else:
                    history = list(history_source[-limit:])
            self._respond(200, {"messages": history, "count": len(history)})
            return

        if path.startswith("/receive/"):
            agent_id = path[len("/receive/") :].strip()
            if not agent_id:
                self._respond(400, {"error": "missing agent_id"})
                return

            if BRIDGE_STRICT_AUTH:
                ok, role, identity = self._require_authenticated()
                if not ok:
                    return
                if role == "agent" and identity != agent_id:
                    self._respond(403, {"error": "token agent mismatch for receive endpoint"})
                    return

            # Track liveness: agent is polling → alive and waiting
            with AGENT_STATE_LOCK:
                AGENT_LAST_SEEN[agent_id] = time.time()
                AGENT_BUSY[agent_id] = False
            update_agent_status(agent_id)

            wait = parse_wait((query.get("wait") or [None])[0])
            limit = parse_limit((query.get("limit") or [None])[0])
            raw_team_filter = (query.get("team") or [None])[0]
            team_filter = str(raw_team_filter).strip() if raw_team_filter else None
            raw_from_filter = (query.get("from") or [None])[0]
            from_filter = str(raw_from_filter).strip() if raw_from_filter else None
            raw_after_id = (query.get("after_id") or query.get("min_id") or [None])[0]
            after_id = parse_after_id(raw_after_id)
            fresh_only = parse_bool((query.get("fresh_only") or [None])[0], False)

            def _apply_receive_filters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
                filtered = items
                if after_id is not None:
                    newer: list[dict[str, Any]] = []
                    for msg in filtered:
                        try:
                            msg_id = int(msg.get("id", -1))
                        except (TypeError, ValueError):
                            continue
                        if msg_id > after_id:
                            newer.append(msg)
                    filtered = newer
                if from_filter:
                    filtered = [m for m in filtered if m.get("from") == from_filter]
                return filtered

            with COND:
                cursor = CURSORS.get(agent_id, 0)
                unread = _apply_receive_filters(
                    messages_for_agent(cursor, agent_id, team_filter=team_filter)
                )

                if not unread and wait > 0:
                    COND.wait(timeout=wait)
                    cursor = CURSORS.get(agent_id, 0)
                    unread = _apply_receive_filters(
                        messages_for_agent(cursor, agent_id, team_filter=team_filter)
                    )

                # S1-F1 FIX: Only advance cursor if ALL unread messages are delivered.
                # When limit truncates, don't advance — avoids silent message loss.
                # Duplicates on next poll are acceptable, message loss is not.
                if from_filter:
                    # from-Filter: don't advance cursor (other messages must remain)
                    unread = [m for m in unread if m.get("from") == from_filter]
                elif limit is not None and len(unread) > limit:
                    unread = unread[-limit:]
                    if fresh_only:
                        # Fresh-only mode intentionally drops older backlog to avoid
                        # replaying sticky history as new events for caller-side loops.
                        CURSORS[agent_id] = len(MESSAGES)
                else:
                    CURSORS[agent_id] = len(MESSAGES)

            if unread:
                # Agent will now process these messages — mark as BUSY
                # so health checker doesn't flag it as disconnected during CLI call.
                with AGENT_STATE_LOCK:
                    AGENT_BUSY[agent_id] = True
                unread_ids = [m.get("id") for m in unread[:5]]
                consumer = self.headers.get("X-Bridge-Client", "unknown")
                consumer_agent = self.headers.get("X-Bridge-Agent", "")
                print(
                    f"[receive] agent={agent_id} consumer={consumer} "
                    f"header_agent={consumer_agent} count={len(unread)} "
                    f"sample_ids={unread_ids}"
                )

            # Hardening (H7): Save last_message_id_received for precise missed-message recovery
            if unread:
                max_id = max((m.get("id", 0) for m in unread), default=0)
                if max_id:
                    _save_agent_state(agent_id, {
                        "last_message_id_received": max_id,
                        "last_seen": utc_now_iso(),
                    })

            self._respond(
                200,
                {
                    "agent": agent_id,
                    "count": len(unread),
                    "messages": unread,
                },
            )
            return

        if _handle_board_get(self, path, query):
            return

        if _handle_approvals_get(self, path, query):
            return

        if _handle_teams_get(self, path, query):
            return

        if _handle_mcp_catalog_get(self, path, query):
            return

        if _handle_automation_get(self, path, query):
            return

        self._respond(404, {"error": "unknown path"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post()
        except Exception as exc:
            try:
                self._respond(500, {"error": f"Internal server error: {type(exc).__name__}"})
            except Exception:
                pass
            print(f"[ERROR] Uncaught in do_POST {self.path}: {exc}")
            import traceback; traceback.print_exc()

    def _handle_post(self) -> None:
        global _GRACEFUL_SHUTDOWN_TIMER
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"

        # Normalize /api/ prefix — Frontend uses /api/... but server routes don't
        if path.startswith("/api/"):
            path = "/" + path[5:]

        # S9: Rate-limiting
        if not self._check_rate_limit(path):
            self._respond(429, {"error": "rate limited", "retry_after": 60})
            return

        if BRIDGE_STRICT_AUTH and path == "/register":
            register_token = str(self.headers.get("X-Bridge-Register-Token", "")).strip()
            if not register_token:
                auth = str(self.headers.get("Authorization", "")).strip()
                if len(auth) > 7 and auth[:7].lower() == "bearer ":
                    register_token = auth[7:].strip()
            if not BRIDGE_REGISTER_TOKEN:
                self._respond(503, {"error": "BRIDGE_REGISTER_TOKEN not configured on server"})
                return
            if not register_token or not secrets.compare_digest(register_token, BRIDGE_REGISTER_TOKEN):
                self._respond(403, {"error": "invalid register token"})
                return

        if BRIDGE_STRICT_AUTH and self._path_requires_auth_post(path):
            ok, _, _ = self._require_authenticated()
            if not ok:
                return

        if path == "/stream_chunk":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            agent_id = str(data.get("agent_id", "")).strip()
            text = str(data.get("text", ""))
            if agent_id and text:
                ws_broadcast("stream_chunk", {"agent_id": agent_id, "text": text})
            self._respond(200, {"ok": True})
            return

        if path == "/activity":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            agent_id = str(data.get("agent_id", "")).strip()
            action = str(data.get("action", "")).strip()
            target_value = str(data.get("target", "")).strip()
            if not agent_id or not action:
                self._respond(400, {"error": "agent_id and action required"})
                return
            if BRIDGE_STRICT_AUTH:
                ok, role, identity = self._require_authenticated()
                if not ok:
                    return
                if role == "agent" and identity != agent_id:
                    self._respond(403, {"error": "token agent mismatch for activity endpoint"})
                    return

            blocked_scope, scope_check = _check_activity_scope_violation(agent_id, action, target_value)
            if blocked_scope:
                violation_details = str(scope_check.get("details", "activity target outside allowed scope"))
                guardrails.log_violation(agent_id, "scope_violation", violation_details)
                self._respond(
                    403,
                    {
                        "error": "scope violation",
                        "agent_id": agent_id,
                        "action": action,
                        "target": target_value,
                        "details": violation_details,
                        "allowed_preview": scope_check.get("allowed_preview", []),
                    },
                )
                return
            # V3 T7: Extended activity fields (backwards-compatible)
            task_id_act = str(data.get("task_id", "")).strip() or None
            blocked = bool(data.get("blocked", False))
            blocker_reason = str(data.get("blocker_reason", "")).strip() or None
            activity: dict[str, Any] = {
                "agent_id": agent_id,
                "action": action,
                "target": target_value or None,
                "description": str(data.get("description", "")).strip() or None,
                "task_id": task_id_act,
                "blocked": blocked,
                "blocker_reason": blocker_reason,
                "timestamp": utc_now_iso(),
            }
            _paap_warning_msg: str | None = None
            with LOCK:
                AGENT_ACTIVITIES[agent_id] = activity
                # ---- PAAP Compliance Check (under LOCK for thread-safety) ----
                if action == "paap":
                    _AGENT_PAAP_CLEARED[agent_id] = True
                elif _is_paap_external_action(action):
                    if not _AGENT_PAAP_CLEARED.get(agent_id, False):
                        _AGENT_PAAP_VIOLATIONS[agent_id] = _AGENT_PAAP_VIOLATIONS.get(agent_id, 0) + 1
                        _paap_count = _AGENT_PAAP_VIOLATIONS[agent_id]
                        _save_paap_violations()
                        _paap_warning_msg = (
                            f"[PAAP] Du hast eine externe Aktion ({action}) ohne "
                            f"Pre-Action-Analysis durchgefuehrt. Bitte PAAP-Protokoll "
                            f"einhalten. (Violation #{_paap_count})"
                        )
                    # Reset: next external action needs fresh PAAP
                    _AGENT_PAAP_CLEARED[agent_id] = False
            ws_broadcast("activity", {"activity": activity})
            if _paap_warning_msg:
                append_message("system", agent_id, _paap_warning_msg)

            # Phase 1: Persist last_activity + auto-generate context_summary if stale
            # Auto-save: build context_summary from current activity so CONTEXT RESTORE
            # always has fresh data, even if agent never calls bridge_save_context.
            # Only overwrites if existing summary is >30min old (preserves explicit saves).
            state_updates: dict[str, Any] = {"last_activity": activity}
            existing_state = _load_agent_state(agent_id)
            updated_at = existing_state.get("updated_at", "")
            summary_age_stale = True
            if updated_at:
                try:
                    last_update = datetime.fromisoformat(updated_at)
                    summary_age_stale = (datetime.now(timezone.utc) - last_update).total_seconds() > 1800
                except (ValueError, TypeError):
                    pass
            if summary_age_stale or not existing_state.get("context_summary"):
                auto_parts = [action]
                if activity.get("target"):
                    auto_parts.append(str(activity["target"]))
                if activity.get("description"):
                    auto_parts.append(str(activity["description"]))
                state_updates["context_summary"] = " → ".join(auto_parts)
            _save_agent_state(agent_id, state_updates)
            # V3 T7: Auto whiteboard sync — activity with task_id creates/updates whiteboard entry
            if task_id_act:
                wb_severity = "warning" if blocked else "info"
                wb_content = str(data.get("description", action)).strip()
                if blocked and blocker_reason:
                    wb_content = f"Wartet auf: {blocker_reason}"
                _whiteboard_post(agent_id, "status", wb_content, task_id=task_id_act, severity=wb_severity, ttl_seconds=3600)

            # R2: checkpoint_saved during restart WARN phase
            if action == "checkpoint_saved" and RESTART_STATE.get("phase") == "warn":
                with RESTART_LOCK:
                    RESTART_STATE["checkpoints"][agent_id] = utc_now_iso()
                active = _get_active_agent_ids()
                ws_broadcast("restart_checkpoint", {
                    "agent_id": agent_id,
                    "total": len(active),
                    "saved": len(RESTART_STATE["checkpoints"]),
                })
                print(f"[restart] Checkpoint saved: {agent_id} ({len(RESTART_STATE['checkpoints'])}/{len(active)})")
                _check_all_checkpoints_saved()

            self._respond(200, {"ok": True, "activity": activity})
            return

        # ===== PRE-RESTART-SAFETY PROTOCOL ENDPOINTS (R1/R3) =====

        # Restart lock: only agents from team.json RBAC may trigger server restart
        if path in ("/server/restart", "/server/restart/force"):
            requesting = str(self.headers.get("X-Bridge-Agent", "")).strip().lower()
            from_body = ""
            # Peek at body for "from" field (non-destructive check)
            try:
                cl = int(self.headers.get("Content-Length", 0))
                if cl > 0:
                    raw = self.rfile.peek(min(cl, 4096))
                    import json as _j
                    _d = _j.loads(raw[:cl])
                    from_body = str(_d.get("from", "")).strip().lower()
            except Exception:
                pass
            agent_id = requesting or from_body
            if agent_id and agent_id not in _RBAC_RESTART_ALLOWED:
                self._respond(403, {"error": f"Server restart not allowed for agent '{agent_id}'. Only {sorted(_RBAC_RESTART_ALLOWED)} may restart."})
                return

        if path == "/server/restart":
            data = self._parse_json_body()
            if data is None:
                data = {}
            with RESTART_LOCK:
                if RESTART_STATE["phase"] is not None:
                    self._respond(409, {"error": f"restart already in progress (phase={RESTART_STATE['phase']})"})
                    return
            try:
                warn_seconds = int(data.get("warn_seconds", 60))
                stop_seconds = int(data.get("stop_seconds", 30))
            except (ValueError, TypeError):
                self._respond(400, {"error": "warn_seconds and stop_seconds must be integers"})
                return
            reason = str(data.get("reason", "manual restart")).strip() or "manual restart"
            agents_mode = str(data.get("agents", "restart")).strip()
            restart_id = f"restart_{int(time.time())}"
            with RESTART_LOCK:
                RESTART_STATE["restart_id"] = restart_id
                RESTART_STATE["agents_mode"] = agents_mode if agents_mode in ("restart", "keep") else "restart"
            _restart_warn_phase(reason, warn_seconds, stop_seconds)
            self._respond(200, {
                "ok": True,
                "restart_id": restart_id,
                "phase": "warn",
                "estimated_restart": (datetime.now(timezone.utc) + timedelta(seconds=warn_seconds + stop_seconds)).isoformat(),
            })
            return

        if path == "/server/restart/force":
            data = self._parse_json_body()
            if data is None:
                data = {}
            try:
                stop_seconds = int(data.get("stop_seconds", 30))
            except (ValueError, TypeError):
                self._respond(400, {"error": "stop_seconds must be integer"})
                return
            # If no restart is running, start one and skip WARN
            with RESTART_LOCK:
                if RESTART_STATE["phase"] is None:
                    reason = str(data.get("reason", "force restart")).strip() or "force restart"
                    restart_id = f"restart_{int(time.time())}"
                    RESTART_STATE["restart_id"] = restart_id
                    RESTART_STATE["started_at"] = utc_now_iso()
                    RESTART_STATE["reason"] = reason
                    RESTART_STATE["agents_mode"] = str(data.get("agents", "restart")).strip() or "restart"
            result = _restart_force(stop_seconds)
            self._respond(200 if result.get("ok") else 409, result)
            return

        if path == "/server/restart/cancel":
            result = _restart_cancel()
            self._respond(200 if result.get("ok") else 409, result)
            return

        if path == "/server/restart/reset":
            result = _restart_reset()
            self._respond(200, result)
            return

        if _handle_teams_post(self, path):
            return

        if _handle_mcp_catalog_post(self, path):
            return

        if _handle_agents_post(self, path):
            return

        if _handle_shared_tools_post(self, path):
            return

        if _handle_capability_library_post(self, path):
            return

        # ===== SKILL PROPOSALS (G5+M3) =====

        if path == "/skills/propose":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            skill_name = str(data.get("skill_name", "")).strip()
            description = str(data.get("description", "")).strip()
            content = str(data.get("content", "")).strip()
            reason = str(data.get("reason", "")).strip()
            if not agent_id or not skill_name or not content:
                self._respond(400, {"error": "'agent_id', 'skill_name', and 'content' are required"})
                return
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{0,49}$', skill_name):
                self._respond(400, {"error": "skill_name must match [a-zA-Z][a-zA-Z0-9_-]{0,49}"})
                return
            if len(content) > 50_000:
                self._respond(400, {"error": "content exceeds 50KB limit"})
                return
            # Rate limit: max 3 proposals per agent per day
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with _PROPOSALS_LOCK:
                agent_today = sum(1 for p in _SKILL_PROPOSALS
                                  if p.get("agent_id") == agent_id
                                  and p.get("created_at", "").startswith(today)
                                  and p.get("status") == "pending")
                if agent_today >= 3:
                    self._respond(429, {"error": f"Rate limit: max 3 proposals per agent per day. {agent_id} has {agent_today}."})
                    return
                proposal_id = str(uuid.uuid4())
                proposal = {
                    "id": proposal_id,
                    "agent_id": agent_id,
                    "skill_name": html.escape(skill_name),
                    "description": html.escape(description) if description else "",
                    "content": content,
                    "reason": html.escape(reason) if reason else "",
                    "status": "pending",
                    "created_at": utc_now_iso(),
                    "reviewed_by": None,
                    "reviewed_at": None,
                }
                _SKILL_PROPOSALS.append(proposal)
                _save_proposals()
            # Also write draft file to proposals/ dir
            os.makedirs(_PROPOSALS_DIR, exist_ok=True)
            draft_file = os.path.join(_PROPOSALS_DIR, f"{skill_name}.md")
            try:
                with open(draft_file, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                pass  # Non-critical — JSON is the source of truth
            # Notify Viktor
            append_message("system", "viktor",
                           f"[SKILL PROPOSAL] Agent '{agent_id}' schlaegt Skill '{skill_name}' vor. "
                           f"Grund: {reason or 'nicht angegeben'}. Review: PATCH /skills/proposals/{proposal_id}",
                           meta={"type": "skill_proposal", "proposal_id": proposal_id})
            self._respond(201, {"ok": True, "proposal": proposal})
            return

        # ===== MEDIA PIPELINE (G6) =====
        if _handle_media_post(self, path):
            return

        if _handle_domain_post(self, path):
            return

        if _handle_data_post(self, path):
            return

        if _handle_creator_post(self, path):
            return

        # ===== VOICE / TELEPHONY POST ENDPOINTS =====

        if path == "/voice/call":
            if TELEPHONY_CLIENT is None:
                self._respond(200, {"available": False, "error": "Telephony not configured"})
                return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            to_number = str(data.get("to", "")).strip()
            if not to_number:
                self._respond(400, {"error": "missing 'to' phone number"})
                return
            message = str(data.get("message", "")).strip()
            twiml = str(data.get("twiml", "")).strip()
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            skip_safety = bool(data.get("approved", False))
            result = TELEPHONY_CLIENT.make_call(
                to_number=to_number,
                twiml=twiml,
                message=message,
                agent_id=agent_id,
                skip_safety=skip_safety,
            )
            self._respond(200, result.to_dict())
            return

        if path == "/voice/sms":
            if TELEPHONY_CLIENT is None:
                self._respond(200, {"available": False, "error": "Telephony not configured"})
                return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            to_number = str(data.get("to", "")).strip()
            body = str(data.get("body", "")).strip()
            if not to_number or not body:
                self._respond(400, {"error": "missing 'to' or 'body'"})
                return
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            skip_safety = bool(data.get("approved", False))
            result = TELEPHONY_CLIENT.send_sms(
                to_number=to_number,
                body=body,
                agent_id=agent_id,
                skip_safety=skip_safety,
            )
            self._respond(200, result.to_dict())
            return

        # ===== SYSTEM SHUTDOWN/RESUME ENDPOINTS =====

        if path == "/system/shutdown":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            agent_id = str(data.get("by", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip() or "system"
            reason = str(data.get("reason", "")).strip()
            graceful = bool(data.get("graceful", False))
            timeout_secs = int(data.get("timeout_seconds", 30))
            timeout_secs = max(5, min(300, timeout_secs))  # clamp 5-300s

            _SYSTEM_STATUS["shutdown_active"] = True
            _SYSTEM_STATUS["shutdown_since"] = utc_now_iso()
            _SYSTEM_STATUS["shutdown_by"] = agent_id
            _SYSTEM_STATUS["shutdown_reason"] = reason or None

            if graceful:
                # Graceful mode: notify agents, wait for ACKs or timeout
                with AGENT_STATE_LOCK:
                    online_agents = [aid for aid, reg in REGISTERED_AGENTS.items()
                                     if reg and _agent_is_live(aid, stale_seconds=120.0, reg=reg)]
                with _GRACEFUL_SHUTDOWN_LOCK:
                    _GRACEFUL_SHUTDOWN["pending"] = True
                    _GRACEFUL_SHUTDOWN["timeout_seconds"] = timeout_secs
                    _GRACEFUL_SHUTDOWN["started_at"] = utc_now_iso()
                    _GRACEFUL_SHUTDOWN["acked_agents"] = []
                    _GRACEFUL_SHUTDOWN["expected_agents"] = online_agents
                    _GRACEFUL_SHUTDOWN["finalized"] = False

                shutdown_msg = f"[SHUTDOWN] Graceful Shutdown in {timeout_secs}s von {agent_id}."
                if reason:
                    shutdown_msg += f" Grund: {reason}"
                shutdown_msg += " Bitte Kontext sichern und [SHUTDOWN_ACK] senden."
                append_message("system", "all", shutdown_msg, meta={"type": "graceful_shutdown"})
                ws_broadcast("graceful_shutdown", {
                    "timeout_seconds": timeout_secs,
                    "by": agent_id,
                    "reason": reason,
                    "expected_agents": online_agents,
                })

                # Start timeout timer
                _GRACEFUL_SHUTDOWN_TIMER = threading.Timer(timeout_secs, _finalize_graceful_shutdown)
                _GRACEFUL_SHUTDOWN_TIMER.daemon = True
                _GRACEFUL_SHUTDOWN_TIMER.start()

                self._respond(200, {"ok": True, "graceful": True, "timeout_seconds": timeout_secs,
                                    "expected_agents": online_agents, "system": _SYSTEM_STATUS})
            else:
                # Immediate shutdown (legacy behavior)
                shutdown_msg = f"[SYSTEM SHUTDOWN] Shutdown aktiviert von {agent_id}."
                if reason:
                    shutdown_msg += f" Grund: {reason}"
                append_message("system", "all", shutdown_msg, meta={"type": "system_shutdown"})
                ws_broadcast("system_shutdown", _SYSTEM_STATUS)
                self._respond(200, {"ok": True, "system": _SYSTEM_STATUS})
            return

        if path == "/system/resume":
            data = self._parse_json_body()
            if data is None:
                data = {}
            agent_id = str(data.get("by", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip() or "system"
            _SYSTEM_STATUS["shutdown_active"] = False
            _SYSTEM_STATUS["shutdown_since"] = None
            _SYSTEM_STATUS["shutdown_by"] = None
            _SYSTEM_STATUS["shutdown_reason"] = None
            # Reset graceful shutdown state
            with _GRACEFUL_SHUTDOWN_LOCK:
                if _GRACEFUL_SHUTDOWN_TIMER:
                    _GRACEFUL_SHUTDOWN_TIMER.cancel()
                    _GRACEFUL_SHUTDOWN_TIMER = None
                _GRACEFUL_SHUTDOWN["pending"] = False
                _GRACEFUL_SHUTDOWN["finalized"] = False
                _GRACEFUL_SHUTDOWN["acked_agents"] = []
                _GRACEFUL_SHUTDOWN["expected_agents"] = []
                _GRACEFUL_SHUTDOWN["started_at"] = None
            # Broadcast resume to all agents
            append_message("system", "all",
                           f"[SYSTEM RESUME] Normalbetrieb wiederhergestellt von {agent_id}. Shutdown aufgehoben.",
                           meta={"type": "system_resume"})
            ws_broadcast("system_resume", {"resumed_by": agent_id, "timestamp": utc_now_iso()})
            self._respond(200, {"ok": True, "system": _SYSTEM_STATUS})
            return

        # ===== PLATFORM CONTROL POST ENDPOINTS (Ein/Aus-Knopf) =====

        # POST /platform/start — Start all auto_start agents + watcher + forwarder
        if path == "/platform/start":
            import subprocess as _sp
            results = {"agents": [], "watcher": None, "forwarder": None}

            # Start watcher if not running
            watcher_pid_file = os.path.join(ROOT_DIR, "Backend", "pids", "watcher.pid")
            _watcher_alive = False
            try:
                _wp = int(open(watcher_pid_file).read().strip())
                os.kill(_wp, 0)
                _watcher_alive = True
            except (OSError, ValueError):
                pass
            if not _watcher_alive:
                _watcher_log = os.path.join(ROOT_DIR, "Backend", "logs", "watcher.log")
                _watcher_script = os.path.join(ROOT_DIR, "Backend", "bridge_watcher.py")
                if os.path.isfile(_watcher_script):
                    _wp = _sp.Popen(
                        ["python3", "-u", _watcher_script],
                        stdout=open(_watcher_log, "a"), stderr=_sp.STDOUT,
                        cwd=os.path.join(ROOT_DIR, "Backend"),
                        start_new_session=True,
                    )
                    with open(watcher_pid_file, "w") as _f:
                        _f.write(str(_wp.pid))
                    results["watcher"] = {"started": True, "pid": _wp.pid}
                else:
                    results["watcher"] = {"started": False, "error": "bridge_watcher.py not found"}
            else:
                results["watcher"] = {"started": False, "already_running": True}

            # Start output forwarder if not running
            _fwd_session = _resolve_forwarder_session_name()
            _fwd_pid_file = os.path.join(ROOT_DIR, "Backend", "pids", "output_forwarder.pid")
            _fwd_alive = False
            try:
                _fp = int(open(_fwd_pid_file).read().strip())
                os.kill(_fp, 0)
                _fwd_alive = True
            except (OSError, ValueError):
                pass
            if not _fwd_alive:
                _fwd_script = os.path.join(ROOT_DIR, "Backend", "output_forwarder.py")
                if os.path.isfile(_fwd_script) and _tmux_session_name_exists(_fwd_session):
                    _fwd_log = os.path.join(ROOT_DIR, "Backend", "logs", "output_forwarder.log")
                    _fwd_env = dict(os.environ)
                    _fwd_env["FORWARDER_SESSION"] = _fwd_session
                    _fp = _sp.Popen(
                        ["python3", "-u", _fwd_script],
                        stdout=open(_fwd_log, "a"), stderr=_sp.STDOUT,
                        cwd=os.path.join(ROOT_DIR, "Backend"),
                        start_new_session=True,
                        env=_fwd_env,
                    )
                    with open(_fwd_pid_file, "w") as _f:
                        _f.write(str(_fp.pid))
                    results["forwarder"] = {"started": True, "pid": _fp.pid, "session": _fwd_session}
                else:
                    results["forwarder"] = {
                        "started": False,
                        "reason": "forwarder script or session missing",
                        "session": _fwd_session,
                    }
            else:
                results["forwarder"] = {"started": False, "already_running": True}

            # Start agents marked active=true and auto_start=true via existing start API
            if TEAM_CONFIG:
                for _ag in TEAM_CONFIG.get("agents", []):
                    if not _ag.get("active", False) or not _ag.get("auto_start", False):
                        continue
                    _aid = _ag.get("id", "")
                    _sess = _session_name_for(_aid)
                    if _sp.run(["tmux", "has-session", "-t", _sess], capture_output=True).returncode == 0:
                        results["agents"].append({"id": _aid, "status": "already_running"})
                        continue
                    # Use internal _start_agent_session helper
                    try:
                        ok = _start_agent_from_conf(_aid)
                        results["agents"].append({"id": _aid, "status": "starting" if ok else "failed"})
                    except Exception as exc:
                        results["agents"].append({"id": _aid, "status": "error", "error": str(exc)})

            # Clear shutdown state if active
            if _SYSTEM_STATUS.get("shutdown_active"):
                _SYSTEM_STATUS["shutdown_active"] = False
                _SYSTEM_STATUS["shutdown_since"] = None
                _SYSTEM_STATUS["shutdown_by"] = None
                _SYSTEM_STATUS["shutdown_reason"] = None

            self._respond(200, {"ok": True, "results": results})
            return

        # POST /platform/stop — Gracefully stop agents + watcher + forwarder + server
        if path == "/platform/stop":
            import subprocess as _sp
            import signal as _sig
            data = self._parse_json_body() or {}
            stop_server = bool(data.get("stop_server", False))
            results = {"agents": [], "watcher": None, "forwarder": None, "server": None}

            # Stop all agents marked active=true and auto_start=true
            if TEAM_CONFIG:
                for _ag in TEAM_CONFIG.get("agents", []):
                    if not _ag.get("active", False) or not _ag.get("auto_start", False):
                        continue
                    _aid = _ag.get("id", "")
                    _sess = _session_name_for(_aid)
                    if _sp.run(["tmux", "has-session", "-t", _sess], capture_output=True).returncode == 0:
                        _sp.run(["tmux", "kill-session", "-t", _sess], capture_output=True)
                        results["agents"].append({"id": _aid, "status": "stopped"})
                    else:
                        results["agents"].append({"id": _aid, "status": "not_running"})

            # Stop watcher
            _watcher_pid_file = os.path.join(ROOT_DIR, "Backend", "pids", "watcher.pid")
            try:
                _wp = int(open(_watcher_pid_file).read().strip())
                os.kill(_wp, _sig.SIGTERM)
                results["watcher"] = {"stopped": True, "pid": _wp}
            except (OSError, ValueError):
                results["watcher"] = {"stopped": False, "reason": "not_running"}

            # Stop forwarder
            _fwd_pid_file = os.path.join(ROOT_DIR, "Backend", "pids", "output_forwarder.pid")
            try:
                _fp = int(open(_fwd_pid_file).read().strip())
                os.kill(_fp, _sig.SIGTERM)
                results["forwarder"] = {"stopped": True, "pid": _fp}
            except (OSError, ValueError):
                results["forwarder"] = {"stopped": False, "reason": "not_running"}

            # Set shutdown state
            _SYSTEM_STATUS["shutdown_active"] = True
            _SYSTEM_STATUS["shutdown_since"] = utc_now_iso()
            _SYSTEM_STATUS["shutdown_by"] = "platform_stop"

            if stop_server:
                # Touch stop marker to kill restart_wrapper loop, then exit server
                results["server"] = {"stopping": True}
                self._respond(200, {"ok": True, "results": results})
                # Deferred server stop after response is sent
                def _deferred_stop():
                    import time as _t
                    _t.sleep(1)
                    open("/tmp/bridge_stop_requested", "w").write("platform_stop")
                    os._exit(0)
                threading.Thread(target=_deferred_stop, daemon=True).start()
            else:
                results["server"] = {"stopping": False, "hint": "set stop_server=true to also stop the server process"}
                self._respond(200, {"ok": True, "results": results})
            return

        # ===== GIT ADVISORY LOCKS POST/DELETE (RB2) =====

        # POST /git/lock — acquire advisory lock (delegates to git_collaboration)
        # Identity binding: X-Bridge-Agent header must match body agent_id (anti-spoofing)
        if _handle_git_lock_post(self, path):
            return

        # ===== CREDENTIAL STORE POST ENDPOINT (E1) =====
        if _handle_credentials_post(self, path):
            return

        # ===== TOKEN USAGE POST ENDPOINT (C2) =====
        if _handle_metrics_post(self, path):
            return

        if _handle_event_subscriptions_post(self, path):
            return

        if _handle_workflows_post(self, path):
            return

        # ===== STRUCTURED TASK PROTOCOL ENDPOINTS =====

        if path == "/task/create":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            task_type = str(data.get("type", "")).strip()
            if task_type not in VALID_TASK_TYPES:
                self._respond(400, {"error": f"invalid task type '{task_type}', valid: {sorted(VALID_TASK_TYPES)}"})
                return
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                self._respond(400, {"error": "payload must be a dict"})
                return
            # V2: title (required), team, priority, labels
            title = html.escape(str(data.get("title", "")).strip())
            if not title or len(title) > TASK_TITLE_MAX_LEN:
                self._respond(400, {"error": f"title is required (1-{TASK_TITLE_MAX_LEN} chars)"})
                return
            team = str(data.get("team", "")).strip() or None
            if team and TEAM_CONFIG:
                valid_team_ids = {t.get("id") for t in TEAM_CONFIG.get("teams", [])}
                if team not in valid_team_ids:
                    self._respond(400, {"error": f"unknown team '{team}', valid: {sorted(valid_team_ids)}"})
                    return
            priority = 1
            if "priority" in data:
                try:
                    priority = int(data["priority"])
                except (ValueError, TypeError):
                    self._respond(400, {"error": "priority must be an integer (1-3)"})
                    return
                if priority not in VALID_TASK_PRIORITIES:
                    self._respond(400, {"error": f"priority must be 1-3, got {priority}"})
                    return
            labels_raw = data.get("labels", [])
            if not isinstance(labels_raw, list):
                self._respond(400, {"error": "labels must be a list"})
                return
            warnings: list[str] = []
            # F-13: warn on label truncation
            if len(labels_raw) > TASK_LABEL_MAX_COUNT:
                warnings.append(f"labels truncated from {len(labels_raw)} to {TASK_LABEL_MAX_COUNT}")
            labels = [html.escape(str(l).strip()[:TASK_LABEL_MAX_LEN]) for l in labels_raw[:TASK_LABEL_MAX_COUNT] if str(l).strip()]
            # F-04: description as real top-level field
            description = html.escape(str(data.get("description", "")).strip()) or None
            assigned_to = str(data.get("assigned_to", "")).strip() or None
            required_capabilities = _task_required_capabilities(data)
            # F-08: warn when assigned_to is not a registered agent
            if assigned_to and assigned_to not in REGISTERED_AGENTS:
                warnings.append(f"assigned_to '{assigned_to}' is not a registered agent")
            elif assigned_to and required_capabilities:
                assigned_registered, assigned_caps = _get_registered_agent_capabilities(assigned_to)
                caps_match, missing_caps = _capability_match(
                    required_capabilities,
                    assigned_caps,
                    agent_registered=assigned_registered,
                )
                if not caps_match:
                    self._respond(400, {
                        "error": (
                            f"assigned_to '{assigned_to}' is missing required_capabilities: "
                            f"{missing_caps}"
                        ),
                        "required_capabilities": required_capabilities,
                        "missing_capabilities": missing_caps,
                    })
                    return
            created_by = str(data.get("created_by", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip() or "unknown"
            # F-10: warn when created_by falls back to "unknown"
            if created_by == "unknown":
                warnings.append("created_by is 'unknown' — set created_by in body or X-Bridge-Agent header for audit trail")
            idempotency_key = str(data.get("idempotency_key", "")).strip() or None
            # Deduplication via idempotency_key
            if idempotency_key:
                with TASK_LOCK:
                    for tid, t in TASKS.items():
                        if t.get("idempotency_key") == idempotency_key:
                            self._respond(200, {"ok": True, "task_id": tid, "deduplicated": True, "task": t})
                            return
            try:
                ack_deadline = int(data.get("ack_deadline_seconds", TASK_DEFAULT_ACK_DEADLINE))
                max_retries = int(data.get("max_retries", TASK_DEFAULT_MAX_RETRIES))
            except (ValueError, TypeError):
                self._respond(400, {"error": "ack_deadline_seconds and max_retries must be integers"})
                return
            # V4: blocker_reason — orthogonal to state (any state can be blocked)
            blocker_reason = str(data.get("blocker_reason", "")).strip() or None
            # Attachments — list of {url, original_name, mime?, size?}
            attachments_raw = data.get("attachments", [])
            attachments: list[dict[str, Any]] = []
            if attachments_raw:
                if not isinstance(attachments_raw, list):
                    self._respond(400, {"error": "attachments must be a list"})
                    return
                if len(attachments_raw) > 10:
                    self._respond(400, {"error": "max 10 attachments per task"})
                    return
                for att in attachments_raw:
                    if not isinstance(att, dict):
                        self._respond(400, {"error": "each attachment must be an object"})
                        return
                    att_url = str(att.get("url", "")).strip()
                    att_name = str(att.get("original_name", "")).strip()
                    if not att_url or not att_name:
                        self._respond(400, {"error": "each attachment requires 'url' and 'original_name'"})
                        return
                    if not att_url.startswith("/files/"):
                        self._respond(400, {"error": f"attachment url must start with /files/, got: {att_url[:50]}"})
                        return
                    attachments.append({
                        "url": att_url,
                        "original_name": html.escape(att_name[:200]),
                        "mime": str(att.get("mime", "")).strip()[:100] or None,
                        "size": int(att["size"]) if "size" in att and att["size"] is not None else None,
                    })
            task_id = str(uuid.uuid4())
            task: dict[str, Any] = {
                "task_id": task_id,
                "type": task_type,
                "title": title,
                "description": description,
                "team": team,
                "priority": priority,
                "labels": labels,
                "payload": payload,
                "required_capabilities": required_capabilities,
                "assigned_to": assigned_to,
                "created_by": created_by,
                "state": "created",
                "created_at": utc_now_iso(),
                "ack_deadline_seconds": ack_deadline,
                "idempotency_key": idempotency_key,
                "retry_count": 0,
                "max_retries": max_retries,
                # V3 T10: Timeout fields
                "timeout_seconds": int(data.get("timeout_seconds", 1800)),  # 30min default
                "deadline": data.get("deadline"),  # optional ISO timestamp
                "last_checkin": None,
                "checkin_note": None,
                # V4: blocker_reason — orthogonal blocked indicator
                "blocker_reason": blocker_reason,
                "attachments": attachments,
                "state_history": [{"state": "created", "at": utc_now_iso(), "by": created_by}],
            }
            with TASK_LOCK:
                TASKS[task_id] = task
                # Phase 4: Backlog alert check
                backlog_warning = None
                if assigned_to:
                    active_count = sum(
                        1 for t in TASKS.values()
                        if t.get("assigned_to") == assigned_to and t["state"] in ("created", "claimed", "acked")
                    )
                    if active_count >= TASK_BACKLOG_WARN_THRESHOLD:
                        backlog_warning = f"Agent '{assigned_to}' has {active_count} active tasks (threshold: {TASK_BACKLOG_WARN_THRESHOLD})"
                _persist_tasks()
                _append_task_transition_wal(task_id, "created", created_by, None, task, {"assigned_to": assigned_to})
            # Auto-claim: if assigned_to is online, skip the created→claimed hop
            _auto_claimed = False
            if assigned_to and assigned_to in REGISTERED_AGENTS:
                with AGENT_STATE_LOCK:
                    _reg = REGISTERED_AGENTS.get(assigned_to)
                    if _reg and _agent_is_live(assigned_to, stale_seconds=120.0, reg=_reg):
                        _now_iso = utc_now_iso()
                        with TASK_LOCK:
                            task["state"] = "claimed"
                            task["claimed_at"] = _now_iso
                            task["state_history"].append({"state": "claimed", "at": _now_iso, "by": "system"})
                            _persist_tasks()
                        _append_task_transition_wal(task_id, "claimed", "system", None, task, {"auto_claim": True})
                        _auto_claimed = True
                        print(f"[task-create] Auto-claimed task {task_id} for online agent {assigned_to}")
            ws_broadcast("task_created", {"task": task})
            # Notification via append_message (not just WS broadcast).
            if assigned_to:
                _desc_preview = str(data.get("description", ""))[:300]
                if _auto_claimed:
                    append_message(
                        "system", assigned_to,
                        f"[TASK — AUTO-CLAIMED] Aufgabe '{title}' (ID: {task_id}) — von {created_by}.\n"
                        f"Beschreibung: {_desc_preview}\n\n"
                        f"Task wurde automatisch geclaimed. NUR noch ACK + bearbeiten:\n"
                        f"1. bridge_task_ack(task_id='{task_id}')\n"
                        f"2. Task bearbeiten\n"
                        f"3. bridge_task_done(task_id='{task_id}', result_summary='...')\n"
                        f"4. Ergebnis an {created_by} via bridge_send melden",
                        meta={"type": "task_notification", "task_id": task_id, "auto_claimed": True},
                    )
                else:
                    append_message(
                        "system", assigned_to,
                        f"[TASK — SOFORT CLAIMEN] Neue Aufgabe: '{title}' (ID: {task_id}) — von {created_by}.\n"
                        f"Beschreibung: {_desc_preview}\n\n"
                        f"SOFORT ausfuehren:\n"
                        f"1. bridge_task_claim(task_id='{task_id}')\n"
                        f"2. bridge_task_ack(task_id='{task_id}')\n"
                        f"3. Task bearbeiten (Details oben)\n"
                        f"4. bridge_task_done(task_id='{task_id}', result_summary='...')\n"
                        f"5. Ergebnis an {created_by} via bridge_send melden",
                        meta={"type": "task_notification", "task_id": task_id},
                    )
            _log_task_event(task_id, "created", created_by, {"type": task_type, "assigned_to": assigned_to})
            event_bus.emit_task_created(task_id, title, assigned_to or "", priority, created_by)
            if backlog_warning:
                ws_broadcast("backlog_alert", {"agent_id": assigned_to, "warning": backlog_warning})
            # Auto-Mode-Escalation: if assigned agent is in standby, switch to normal
            if assigned_to:
                _as = _load_agent_state(assigned_to)
                if _as.get("mode") == "standby":
                    _save_agent_state(assigned_to, {"mode": "normal"})
                    append_message("system", assigned_to,
                                   "[MODE CHANGE] Dein Modus wurde auf 'normal' geaendert. "
                                   "Arbeite aktuelle Aufgabe ab, dann warte auf Input.",
                                   meta={"type": "mode_change", "mode": "normal"})
                    print(f"[task-create] Auto-escalated {assigned_to} from standby→normal for task {task_id}")
            # V4: Auto-ensure assigned agent is online
            agent_status = None
            if assigned_to:
                agent_status = _ensure_agent_online(assigned_to, task_id=task_id, requester=created_by)
            # G-NEW-2b: Warn if assigned_to agent is not currently registered (orphan risk)
            if assigned_to and assigned_to not in REGISTERED_AGENTS:
                orphan_warning = (
                    f"Agent '{assigned_to}' is not registered. Task may be orphaned if agent never comes online. "
                    f"Use /task/{task_id}/update to reassign or wait for agent registration."
                )
                warnings.append(orphan_warning)
                print(f"[task_create] G-NEW-2b WARNING: {orphan_warning}")
            response_data: dict[str, Any] = {"ok": True, "task_id": task_id, "task": task}
            if backlog_warning:
                response_data["backlog_warning"] = backlog_warning
            if warnings:
                response_data["warnings"] = warnings
            if agent_status and not agent_status["online"]:
                response_data["agent_status"] = agent_status
            self._respond(201, response_data)
            return

        task_claim_match = re.match(r"^/task/([^/]+)/claim$", path)
        if task_claim_match:
            task_id = task_claim_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                # G9: Idempotent reclaim — agent reclaims own task after restart
                if task["state"] in ("claimed", "acked") and task.get("assigned_to") == agent_id:
                    self._respond(200, {"ok": True, "task": task, "reclaimed": True})
                    return
                if task["state"] != "created":
                    self._respond(409, {"error": f"task state is '{task['state']}', expected 'created'"})
                    return
                # Pre-assignment check: if task is assigned to someone else, reject
                pre_assigned = task.get("assigned_to")
                if pre_assigned and pre_assigned != agent_id:
                    self._respond(403, {"error": f"task pre-assigned to '{pre_assigned}', not '{agent_id}'"})
                    return
                # G5: Capability check — agent must satisfy required_capabilities
                required_caps = _task_required_capabilities(task)
                if required_caps:
                    is_registered, agent_caps = _get_registered_agent_capabilities(agent_id)
                    cap_ok, missing = _capability_match(required_caps, agent_caps, agent_registered=is_registered)
                    if not cap_ok:
                        self._respond(403, {
                            "error": f"agent '{agent_id}' lacks required capabilities: {missing}",
                            "required_capabilities": required_caps,
                            "agent_capabilities": agent_caps,
                        })
                        return
                active_count = _count_agent_active_tasks(agent_id)
                if active_count >= TASK_MAX_ACTIVE_PER_AGENT:
                    self._respond(429, {
                        "error": f"agent '{agent_id}' already has {active_count} active tasks",
                        "active_tasks": active_count,
                        "max_active_tasks": TASK_MAX_ACTIVE_PER_AGENT,
                    })
                    return
                before_task_claim = copy.deepcopy(task)
                task["state"] = "claimed"
                task["assigned_to"] = agent_id
                task["claimed_at"] = utc_now_iso()
                task["state_history"].append({"state": "claimed", "at": utc_now_iso(), "by": agent_id})
                _persist_tasks()
                _append_task_transition_wal(task_id, "claimed", agent_id, before_task_claim, task)
            ws_broadcast("task_claimed", {"task_id": task_id, "agent_id": agent_id})
            _log_task_event(task_id, "claimed", agent_id)
            # V3: Auto whiteboard entry
            _whiteboard_post(agent_id, "status", f"Arbeitet an: {task.get('title', task_id)}", task_id=task_id, task_title=task.get("title"), ttl_seconds=3600)
            self._respond(200, {"ok": True, "task": task})
            return

        task_ack_match = re.match(r"^/task/([^/]+)/ack$", path)
        if task_ack_match:
            task_id = task_ack_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task["state"] != "claimed":
                    self._respond(409, {"error": f"task state is '{task['state']}', expected 'claimed'"})
                    return
                if task.get("assigned_to") != agent_id:
                    self._respond(403, {"error": f"task assigned to '{task.get('assigned_to')}', not '{agent_id}'"})
                    return
                active_count = _count_agent_active_tasks(agent_id, exclude_task_id=task_id)
                if active_count >= TASK_MAX_ACTIVE_PER_AGENT:
                    self._respond(429, {
                        "error": f"agent '{agent_id}' already has {active_count} active tasks",
                        "active_tasks": active_count,
                        "max_active_tasks": TASK_MAX_ACTIVE_PER_AGENT,
                    })
                    return
                before_task_ack = copy.deepcopy(task)
                task["state"] = "acked"
                task["acked_at"] = utc_now_iso()
                _refresh_task_lease(task, ref_iso=task["acked_at"])
                task["state_history"].append({"state": "acked", "at": utc_now_iso(), "by": agent_id})
                _persist_tasks()
                _append_task_transition_wal(task_id, "acked", agent_id, before_task_ack, task)
            ws_broadcast("task_acked", {"task_id": task_id, "agent_id": agent_id})
            _log_task_event(task_id, "acked", agent_id)
            self._respond(200, {"ok": True, "task": task})
            return

        task_done_match = re.match(r"^/task/([^/]+)/done$", path)
        if task_done_match:
            task_id = task_done_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            result = data.get("result", {})
            result_code = str(data.get("result_code", "success")).strip()
            result_summary = str(data.get("result_summary", "")).strip()
            evidence = data.get("evidence")
            if result_code not in VALID_RESULT_CODES:
                self._respond(400, {"error": f"invalid result_code '{result_code}', valid: {sorted(VALID_RESULT_CODES)}"})
                return
            # ── Evidenz-Pflicht: result_summary + evidence bei success/partial ──
            if result_code in ("success", "partial") and not result_summary:
                self._respond(400, {
                    "error": "result_summary ist Pflichtfeld bei result_code 'success'/'partial'. "
                             "Beschreibe WAS erledigt wurde und WIE verifiziert (Logs, Tests, Screenshots).",
                    "hint": "Beispiel: result_summary='Feature X implementiert. Verifiziert: 5/5 Tests PASS, curl-Test OK.'"
                })
                return
            # ── Evidence-Objekt: bei success/partial Pflicht, sonst optional aber valide falls gesetzt ──
            VALID_EVIDENCE_TYPES = {"test", "log", "screenshot", "code", "manual", "review"}
            evidence_payload: dict[str, str] | None = None
            if result_code in ("success", "partial") and (not evidence or not isinstance(evidence, dict)):
                self._respond(400, {
                    "error": "evidence-Objekt ist Pflicht bei result_code 'success'/'partial'. "
                             "Jeder Task-Abschluss braucht einen Beweis.",
                    "hint": "evidence: {\"type\": \"test|log|screenshot|code|manual|review\", "
                            "\"ref\": \"Beschreibung/Datei/URL des Belegs\"}"
                })
                return
            if evidence is not None:
                if not isinstance(evidence, dict):
                    self._respond(400, {"error": "evidence muss ein Objekt sein."})
                    return
                ev_type = str(evidence.get("type", "")).strip().lower()
                ev_ref = str(evidence.get("ref", "")).strip()
                if ev_type not in VALID_EVIDENCE_TYPES:
                    self._respond(400, {
                        "error": f"evidence.type '{ev_type}' ungueltig. Erlaubt: {sorted(VALID_EVIDENCE_TYPES)}",
                    })
                    return
                if not ev_ref:
                    self._respond(400, {"error": "evidence.ref darf nicht leer sein. Beschreibe den Beleg."})
                    return
                # Evidence hardening: manual type requires detailed ref (min 50 chars)
                if ev_type == "manual" and len(ev_ref) < 50:
                    self._respond(400, {
                        "error": "evidence_ref too short for manual evidence type. Minimum 50 characters required. "
                                 "Provide concrete description of what was verified.",
                        "current_length": len(ev_ref),
                    })
                    return
                evidence_payload = {"type": ev_type, "ref": ev_ref}
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task["state"] != "acked":
                    self._respond(409, {
                        "error": f"task state is '{task['state']}', expected 'acked'",
                        "hint": "Call /task/{id}/ack successfully before /task/{id}/done.",
                    })
                    return
                if not task.get("acked_at"):
                    self._respond(409, {
                        "error": "task is missing acked_at, cannot complete without a durable ack marker",
                        "hint": "Repeat /task/{id}/ack before /task/{id}/done.",
                    })
                    return
                if task.get("assigned_to") != agent_id:
                    self._respond(403, {"error": f"task assigned to '{task.get('assigned_to')}', not '{agent_id}'"})
                    return
                # ── Mandatory Code Review Gate: code_change tasks require reviewed_by ──
                if task.get("type") == "code_change" and result_code in ("success", "partial"):
                    reviewed_by = str(data.get("reviewed_by", "")).strip()
                    if not reviewed_by:
                        self._respond(400, {
                            "error": "code_change Tasks erfordern 'reviewed_by' Feld. "
                                     "Kein Code-Change ohne durchlaufenes Review.",
                            "hint": "reviewed_by: '<agent_id>' — wer hat den Code reviewed?"
                        })
                        return
                    if reviewed_by == agent_id:
                        self._respond(400, {
                            "error": "Self-Review nicht erlaubt. reviewed_by muss ein anderer Agent sein.",
                        })
                        return
                    if reviewed_by not in REGISTERED_AGENTS and reviewed_by != "user":
                        self._respond(400, {
                            "error": f"reviewed_by '{reviewed_by}' ist kein registrierter Agent.",
                            "hint": "reviewed_by muss ein aktuell registrierter Agent oder 'user' sein."
                        })
                        return
                    task["reviewed_by"] = reviewed_by
                # C3: Output-schema check (warn, don't block)
                schema_valid, schema_errors = guardrails.check_output_schema(
                    agent_id, {"result": result, "result_code": result_code, "result_summary": result_summary}
                )
                before_task_done = copy.deepcopy(task)
                task["state"] = "done"
                task["done_at"] = utc_now_iso()
                task["result"] = result
                task["result_code"] = result_code
                task["result_summary"] = result_summary
                if not schema_valid:
                    task["output_schema_warnings"] = schema_errors
                if evidence_payload:
                    task["evidence"] = {**evidence_payload, "verified_at": utc_now_iso()}
                task["state_history"].append({"state": "done", "at": utc_now_iso(), "by": agent_id, "result_code": result_code})
                _persist_tasks()
                _append_task_transition_wal(task_id, "done", agent_id, before_task_done, task, {"result_code": result_code})
            ws_broadcast("task_done", {"task_id": task_id, "agent_id": agent_id, "result": result, "result_code": result_code})
            _log_task_event(task_id, "done", agent_id, {"result_code": result_code})
            event_bus.emit_task_done(task_id, agent_id, str(result_code))
            # V3: Auto whiteboard entry
            _whiteboard_post(agent_id, "result", f"Fertig: {task.get('title', task_id)}", task_id=task_id, task_title=task.get("title"), ttl_seconds=600)
            # V3: Auto-release all scope locks for this task
            released_locks = _unlock_scope_paths(task_id)
            for rl in released_locks:
                ws_broadcast("scope_unlocked", {"path": rl["path"], "agent_id": rl["agent_id"], "task_id": task_id})
            # Auto-notify creator on task completion
            task_creator = task.get("created_by", "")
            if task_creator and task_creator != agent_id:
                append_message(
                    sender="system",
                    recipient=task_creator,
                    content=f"[TASK DONE] {task.get('title', task_id)} abgeschlossen von {agent_id} — {result_code}",
                    meta={"type": "task_completion", "task_id": task_id, "result_code": result_code, "completed_by": agent_id},
                )
            # Evidence hardening: warn creator + viktor on manual evidence
            if evidence and isinstance(evidence, dict) and str(evidence.get("type", "")).lower() == "manual":
                warn_msg = (
                    f"[EVIDENCE WARNING] Task {task_id} '{task.get('title', '')}' von {agent_id} "
                    f"mit evidence_type='manual' abgeschlossen. Manuelle Verifikation empfohlen. "
                    f"evidence_ref: {str(evidence.get('ref', ''))[:200]}"
                )
                task_creator = task.get("created_by", "")
                if task_creator:
                    append_message(sender="system", recipient=task_creator, content=warn_msg,
                                   meta={"type": "evidence_warning", "task_id": task_id})
                append_message(sender="system", recipient="viktor", content=warn_msg,
                               meta={"type": "evidence_warning", "task_id": task_id})
            self._respond(200, {"ok": True, "task": task})
            return

        # ===== POST /task/{id}/verify — Manager sets verification =====
        task_verify_match = re.match(r"^/task/([^/]+)/verify$", path)
        if task_verify_match:
            task_id = task_verify_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            verification_note = str(data.get("note", "")).strip()
            if not agent_id:
                self._respond(400, {"error": "agent_id required"})
                return
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task["state"] != "done":
                    self._respond(409, {"error": f"task state is '{task['state']}', verify only for 'done' tasks"})
                    return
                # Self-verification prevention: implementer cannot verify own work
                done_by = None
                for entry in task.get("state_history", []):
                    if entry.get("state") == "done":
                        done_by = entry.get("by")
                if done_by and done_by == agent_id:
                    self._respond(403, {"error": f"Self-verification nicht erlaubt. Task wurde von '{agent_id}' implementiert."})
                    return
                before_task_verify = copy.deepcopy(task)
                task["verified_by"] = agent_id
                task["verified_at"] = utc_now_iso()
                if verification_note:
                    task["verification_note"] = verification_note
                task["state_history"].append({
                    "state": "verified", "at": utc_now_iso(), "by": agent_id,
                    "note": verification_note or None,
                })
                _persist_tasks()
                _append_task_transition_wal(task_id, "verified", agent_id, before_task_verify, task)
            ws_broadcast("task_verified", {"task_id": task_id, "verified_by": agent_id})
            _log_task_event(task_id, "verified", agent_id, {"note": verification_note})
            self._respond(200, {"ok": True, "task": task})
            return

        task_fail_match = re.match(r"^/task/([^/]+)/fail$", path)
        if task_fail_match:
            task_id = task_fail_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            error_msg = str(data.get("error", "")).strip() or "unknown error"
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task["state"] in ("done", "failed"):
                    self._respond(409, {"error": f"task already in terminal state '{task['state']}'"})
                    return
                # Owner check: only assigned agent or task creator can fail
                task_owner = task.get("assigned_to")
                task_creator = task.get("created_by")
                allowed = {task_creator}
                if task_owner:
                    allowed.add(task_owner)
                if agent_id not in allowed:
                    self._respond(403, {"error": f"task assigned to '{task_owner}', not '{agent_id}'"})
                    return
                previous_state = task["state"]
                before_task_fail = copy.deepcopy(task)
                task["state"] = "failed"
                task["failed_at"] = utc_now_iso()
                task["error"] = error_msg
                if previous_state in ("claimed", "acked"):
                    task["retry_count"] = task.get("retry_count", 0) + 1
                task["state_history"].append({"state": "failed", "at": utc_now_iso(), "by": agent_id, "error": error_msg})
                _persist_tasks()
                _append_task_transition_wal(task_id, "failed", agent_id, before_task_fail, task, {"error": error_msg})
            ws_broadcast("task_failed", {"task_id": task_id, "agent_id": agent_id, "error": error_msg})
            _log_task_event(task_id, "failed", agent_id, {"error": error_msg})
            event_bus.emit_task_failed(task_id, agent_id, error_msg)
            # V3: Auto whiteboard entry
            _whiteboard_post(agent_id, "alert", f"Fehlgeschlagen: {task.get('title', task_id)}", task_id=task_id, task_title=task.get("title"), severity="warning", ttl_seconds=1800)
            # V3: Auto-release all scope locks for this task
            released_locks = _unlock_scope_paths(task_id)
            for rl in released_locks:
                ws_broadcast("scope_unlocked", {"path": rl["path"], "agent_id": rl["agent_id"], "task_id": task_id})
            # Auto-notify creator on task failure
            task_creator = task.get("created_by", "")
            if task_creator and task_creator != agent_id:
                append_message(
                    sender=agent_id,
                    recipient=task_creator,
                    content=f"[TASK FAILED] {task.get('title', task_id)} — {error_msg}",
                    meta={"type": "task_failure", "task_id": task_id, "error": error_msg},
                )
            self._respond(200, {"ok": True, "task": task})
            return

        # V3 T10: POST /task/{id}/checkin — agent heartbeat for running task
        task_checkin_match = re.match(r"^/task/([^/]+)/checkin$", path)
        if task_checkin_match:
            task_id = task_checkin_match.group(1)
            data = self._parse_json_body() or {}
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            note = str(data.get("note", "")).strip() or None
            refreshed_scope_locks: list[dict[str, Any]] = []
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task["state"] not in ("claimed", "acked"):
                    self._respond(409, {"error": f"task state is '{task['state']}', checkin only for claimed/acked"})
                    return
                if task.get("assigned_to") != agent_id:
                    self._respond(403, {"error": f"task assigned to '{task.get('assigned_to')}', not '{agent_id}'"})
                    return
                before_task_checkin = copy.deepcopy(task)
                task["last_checkin"] = utc_now_iso()
                task["checkin_note"] = note
                task["state_history"].append({
                    "state": "checkin",
                    "at": task["last_checkin"],
                    "by": agent_id,
                    "note": note,
                })
                _refresh_task_lease(task, ref_iso=task["last_checkin"])  # Lease renewal fix
                _persist_tasks()
                _append_task_transition_wal(task_id, "checkin", agent_id, before_task_checkin, task, {"note": note})
            refreshed_scope_locks = _refresh_scope_locks_for_task(task_id)
            # Clear stale escalation state — agent checked in, reset the clock
            with ESCALATION_LOCK:
                ESCALATION_STATE.pop(task_id, None)
                _persist_escalation_state()
            _log_task_event(task_id, "checkin", agent_id, {
                "note": note,
                "scope_locks_refreshed": len(refreshed_scope_locks),
            })
            ws_broadcast("task_checkin", {"task_id": task_id, "agent_id": agent_id, "note": note})
            self._respond(200, {"ok": True, "task_id": task_id, "last_checkin": task["last_checkin"]})
            return

        # ===== END STRUCTURED TASK PROTOCOL =====

        if _handle_subscriptions_post(self, path):
            return

        # ===== V3 SCOPE-LOCK POST ENDPOINTS =====

        # POST /scope/lock — acquire scope lock(s) for a task
        if path == "/scope/lock":
            data = self._parse_json_body() or {}
            task_id = str(data.get("task_id", "")).strip()
            paths_raw = data.get("paths", [])
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            lock_type = str(data.get("lock_type", "file")).strip()
            ttl = data.get("ttl")

            if not task_id:
                self._respond(400, {"error": "task_id is required"})
                return
            if not paths_raw or not isinstance(paths_raw, list):
                self._respond(400, {"error": "paths[] is required (list of file/directory paths)"})
                return
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return
            if lock_type not in ("file", "directory"):
                self._respond(400, {"error": "lock_type must be 'file' or 'directory'"})
                return

            # Verify task exists and agent has claimed it (S1: scope lock ownership)
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                task_state = task.get("state", "")
                task_owner = task.get("assigned_to")
                # S1 FIX: Agent must have claimed/acked the task to lock scope.
                # Unassigned tasks are not yet owned — scope lock is rejected to prevent conflicts.
                if task_state not in ("claimed", "acked"):
                    self._respond(409, {"error": f"scope lock requires task in 'claimed' or 'acked' state, got '{task_state}'"})
                    return
                if task_owner != agent_id:
                    self._respond(403, {"error": f"task assigned to '{task_owner}', not '{agent_id}'"})
                    return

            acquired: list[dict[str, Any]] = []
            conflicts: list[dict[str, str]] = []
            ttl_int = int(ttl) if ttl is not None else None

            for p in paths_raw:
                p_str = str(p).strip()
                if not p_str:
                    continue
                result_lock = _lock_scope_path(p_str, task_id, agent_id, lock_type, ttl_int)
                if isinstance(result_lock, str):
                    conflicts.append({"path": p_str, "error": result_lock})
                else:
                    acquired.append(result_lock)
                    ws_broadcast("scope_locked", {
                        "path": result_lock["path"],
                        "label": result_lock["label"],
                        "agent_id": agent_id,
                        "task_id": task_id,
                    })

            if conflicts:
                # Rollback acquired locks on partial failure
                for lock in acquired:
                    _unlock_scope_paths(task_id, [lock["path"]])
                    ws_broadcast("scope_unlocked", {
                        "path": lock["path"],
                        "agent_id": agent_id,
                        "task_id": task_id,
                    })
                self._respond(409, {
                    "error": "scope conflict",
                    "conflicts": conflicts,
                    "message": f"Cannot lock: {conflicts[0]['error']}",
                })
                return

            self._respond(200, {"ok": True, "locks": acquired})
            return

        # POST /scope/unlock — release scope lock(s) for a task
        if path == "/scope/unlock":
            data = self._parse_json_body() or {}
            task_id = str(data.get("task_id", "")).strip()
            paths_raw = data.get("paths")  # None = release all for task
            agent_id = str(data.get("agent_id", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()

            if not task_id:
                self._respond(400, {"error": "task_id is required"})
                return
            if not agent_id:
                self._respond(400, {"error": "agent_id is required"})
                return

            paths_list: list[str] | None = None
            if paths_raw and isinstance(paths_raw, list):
                paths_list = [str(p).strip() for p in paths_raw if str(p).strip()]

            foreign_locks: list[dict[str, Any]] = []
            if agent_id not in {"system", "watcher"}:
                with SCOPE_LOCK_LOCK:
                    if paths_list:
                        for path_item in paths_list:
                            lock = SCOPE_LOCKS.get(_normalize_scope_path(path_item))
                            if lock and lock["task_id"] == task_id and lock["agent_id"] != agent_id:
                                foreign_locks.append(lock)
                    else:
                        foreign_locks = [
                            lock for lock in SCOPE_LOCKS.values()
                            if lock["task_id"] == task_id and lock["agent_id"] != agent_id
                        ]
            if foreign_locks:
                owners = sorted({str(lock["agent_id"]) for lock in foreign_locks})
                self._respond(403, {
                    "error": f"scope lock owned by {', '.join(owners)}, not '{agent_id}'",
                    "owners": owners,
                    "task_id": task_id,
                })
                return

            released = _unlock_scope_paths(task_id, paths_list)
            for lock in released:
                ws_broadcast("scope_unlocked", {
                    "path": lock["path"],
                    "agent_id": lock["agent_id"],
                    "task_id": task_id,
                })

            self._respond(200, {"ok": True, "released": released, "count": len(released)})
            return

        # ===== END V3 SCOPE-LOCK POST ENDPOINTS =====

        if _handle_whiteboard_post(self, path):
            return

        # ===== V3 ESCALATION ENDPOINT (T11) =====

        # POST /escalation/{task_id}/resolve — Susi resolves Stage 3 escalation
        esc_resolve_match = re.match(r"^/escalation/([^/]+)/resolve$", path)
        if esc_resolve_match:
            task_id = esc_resolve_match.group(1)
            data = self._parse_json_body() or {}
            action = str(data.get("action", "")).strip()
            reassign_to = data.get("reassign_to")
            if reassign_to:
                reassign_to = str(reassign_to).strip()

            if action not in ("extend", "reassign", "cancel"):
                self._respond(400, {"error": f"action must be 'extend', 'reassign', or 'cancel', got '{action}'"})
                return

            result_esc = _resolve_escalation(task_id, action, reassign_to)
            if isinstance(result_esc, str):
                self._respond(400, {"error": result_esc})
                return

            # Post escalation response to whiteboard for audit
            _whiteboard_post("user", "escalation_response", f"Entscheidung: {action} fuer {task_id}", task_id=task_id, severity="info", ttl_seconds=600)
            self._respond(200, {"ok": True, "result": result_esc})
            return

        # ===== END V3 ESCALATION ENDPOINT =====

        start_agent_match = re.match(r"^/agents/([^/]+)/start$", path)
        if start_agent_match:
            data = self._parse_json_body() or {}
            caller = str(data.get("from", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            auth_role, auth_identity = self._resolve_auth_identity()
            if auth_role == "invalid":
                self._respond(403, {"ok": False, "error": "invalid session token"})
                return
            if auth_role == "user":
                caller = "user"
            elif auth_role == "agent":
                if caller and caller != auth_identity:
                    self._respond(403, {"ok": False, "error": "token sender mismatch"})
                    return
                caller = caller or str(auth_identity or "").strip()
            # Allow user, system, and manager agents to start other agents
            if caller not in {"user", "system"} | PLATFORM_OPERATOR_AGENTS:
                self._respond(403, {"ok": False, "error": "only user/system/managers may start agents"})
                return

            agent_id = start_agent_match.group(1).strip()
            if not agent_id:
                self._respond(400, {"ok": False, "error": "missing agent_id"})
                return

            if is_session_alive(agent_id):
                now_ts = time.time()
                now_iso = utc_now_iso()
                with AGENT_STATE_LOCK:
                    reg = REGISTERED_AGENTS.get(agent_id)
                    previous_last_hb = float(reg.get("last_heartbeat", 0) or 0) if reg else 0.0
                    if reg is None:
                        REGISTERED_AGENTS[agent_id] = {
                            "role": _get_runtime_agent_role(agent_id),
                            "capabilities": [],
                            "engine": _get_agent_engine(agent_id),
                            "registered_at": now_iso,
                            "last_heartbeat": now_ts,
                            "last_heartbeat_iso": now_iso,
                        }
                    else:
                        reg["last_heartbeat"] = now_ts
                        reg["last_heartbeat_iso"] = now_iso
                        if not reg.get("registered_at"):
                            reg["registered_at"] = now_iso
                    AGENT_LAST_SEEN[agent_id] = now_ts
                    AGENT_BUSY[agent_id] = False
                update_agent_status(agent_id)
                blocker = _agent_runtime_blocker(agent_id)
                if blocker:
                    reason = str(blocker.get("reason", "")).strip()
                    detail = str(blocker.get("detail", "")).strip()
                    if reason == "login_required":
                        _AGENT_AUTH_BLOCKED.add(agent_id)
                        self._respond(
                            200,
                            {
                                "ok": True,
                                "agent_id": agent_id,
                                "status": "auth_blocked",
                                "message": detail or "Agent needs manual login",
                            },
                        )
                        return
                    self._respond(
                        200,
                        {
                            "ok": True,
                            "agent_id": agent_id,
                            "status": reason or "blocked",
                            "message": detail or f"{agent_id} is blocked in the CLI session",
                        },
                    )
                    return
                # Force-restart if tmux alive but no heartbeat for >60s (dead CLI)
                if previous_last_hb and (now_ts - previous_last_hb) > 60:
                    print(
                        f"[start] {agent_id}: tmux alive but no heartbeat for "
                        f"{int(now_ts - previous_last_hb)}s — force-restarting"
                    )
                    if _auto_restart_agent(agent_id):
                        self._respond(200, {"ok": True, "agent_id": agent_id, "status": "force_restarted"})
                    else:
                        self._respond(500, {"ok": False, "error": f"force-restart failed for {agent_id}"})
                    return
                # ISSUE-002: If agent is at prompt, nudge instead of just "already_running"
                if _is_agent_at_prompt_inline(agent_id):
                    _nudge_idle_agent(agent_id, "start_endpoint")
                    _AGENT_LAST_NUDGE[agent_id] = time.time()
                    self._respond(200, {"ok": True, "agent_id": agent_id, "status": "nudged"})
                    return
                self._respond(200, {"ok": True, "agent_id": agent_id, "status": "already_running"})
                return

            runtime_agent_ids = set(current_runtime_agent_ids())
            if agent_id not in runtime_agent_ids:
                configured_agent_ids = _configured_agent_ids()
                if _start_agent_from_conf(agent_id):
                    phantom_role = agent_id
                    if TEAM_CONFIG:
                        with TEAM_CONFIG_LOCK:
                            for _agent_conf in TEAM_CONFIG.get("agents", []):
                                if _agent_conf.get("id") == agent_id:
                                    phantom_role = _role_description_for(_agent_conf, fallback=agent_id) or agent_id
                                    break
                    _seed_phantom_agent_registration(agent_id, role=phantom_role)
                    self._respond(200, {"ok": True, "agent_id": agent_id, "status": "starting"})
                else:
                    if _check_tmux_session(agent_id):
                        phantom_role = agent_id
                        if TEAM_CONFIG:
                            with TEAM_CONFIG_LOCK:
                                for _agent_conf in TEAM_CONFIG.get("agents", []):
                                    if _agent_conf.get("id") == agent_id:
                                        phantom_role = _role_description_for(_agent_conf, fallback=agent_id) or agent_id
                                        break
                        _seed_phantom_agent_registration(agent_id, role=phantom_role)
                        update_agent_status(agent_id)
                        self._respond(200, {
                            "ok": True,
                            "agent_id": agent_id,
                            "status": "already_running",
                            "message": "session became active during concurrent start",
                        })
                        return
                    if agent_id in configured_agent_ids:
                        self._respond(500, {"ok": False, "error": f"failed to start configured agent: {agent_id}"})
                    else:
                        self._respond(404, {"ok": False, "error": f"agent {agent_id} not found in team.json or agents.conf"})
                return

            if _auto_restart_agent(agent_id):
                self._respond(200, {"ok": True, "agent_id": agent_id, "status": "starting"})
            else:
                self._respond(500, {"ok": False, "error": f"failed to start agent: {agent_id}"})
            return

        # ===== POST /messages/{id}/reaction — Chat-Daumen (Thumbs up/down) =====
        _reaction_match = re.match(r"^/messages/(\d+)/reaction$", path)
        if _reaction_match:
            msg_id = int(_reaction_match.group(1))
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid or missing JSON body"})
                return
            raw_reaction = data.get("reaction")
            reaction = "" if raw_reaction is None else str(raw_reaction).strip()
            reactor = str(data.get("from", "user")).strip() or "user"
            clear_requested = reaction == ""
            if not clear_requested and reaction not in ("thumbs_up", "thumbs_down"):
                self._respond(400, {"error": "reaction must be 'thumbs_up' or 'thumbs_down' or null to clear"})
                return

            # Find message by ID and store reaction under lock
            target_msg = None
            original_sender = ""
            with COND:
                for m in MESSAGES:
                    if m.get("id") == msg_id:
                        target_msg = m
                        break
                if target_msg is not None:
                    reactions = target_msg.setdefault("reactions", {})
                    if clear_requested:
                        reactions.pop(reactor, None)
                        if not reactions:
                            target_msg.pop("reactions", None)
                    else:
                        reactions[reactor] = {
                            "type": reaction,
                            "at": utc_now_iso(),
                        }
                    original_sender = target_msg.get("from", "")
            if target_msg is None:
                self._respond(404, {"error": f"message {msg_id} not found"})
                return
            _non_agent = {"system", "user", "all", "all_managers", "leads"}
            if not clear_requested and original_sender and original_sender not in _non_agent:
                if reaction == "thumbs_up":
                    feedback = "Leo hat deine Nachricht positiv bewertet."
                else:
                    feedback = "Leo hat Bedenken \u2014 Ansatz ueberdenken."
                append_message("system", original_sender, feedback,
                               meta={"type": "reaction_feedback", "reaction": reaction,
                                     "original_msg_id": msg_id, "reactor": reactor})

            # Broadcast reaction to UI via WebSocket
            ws_broadcast("reaction", {
                "msg_id": msg_id,
                "reaction": None if clear_requested else reaction,
                "reactor": reactor,
                "cleared": clear_requested,
            })

            self._respond(200, {"ok": True, "msg_id": msg_id,
                                "reaction": None if clear_requested else reaction,
                                "cleared": clear_requested,
                                "reactor": reactor,
                                "original_sender": original_sender})
            return

        if path == "/send":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return

            raw_content = data.get("content")
            if raw_content is None or not isinstance(raw_content, (str, int, float)):
                self._respond(400, {"error": "fields 'from', 'to', 'content' are required"})
                return
            sender = str(data.get("from", "")).strip()
            recipient = str(data.get("to", "")).strip()
            content = str(raw_content).strip()
            meta = data.get("meta")
            reply_to = data.get("reply_to")
            federation_target = _is_federation_target(recipient)

            has_attachments = isinstance(meta, dict) and isinstance(meta.get("attachments"), list) and len(meta.get("attachments", [])) > 0
            if not sender or not recipient or (not content and not has_attachments):
                self._respond(400, {"error": "fields 'from', 'to', 'content' are required"})
                return
            if federation_target and has_attachments:
                self._respond(400, {"error": "federation target does not support attachments in V1"})
                return
            if len(content) > 500_000:
                self._respond(400, {"error": "content too large (max 500KB)"})
                return
            if len(sender) > 128 or len(recipient) > 128:
                self._respond(400, {"error": "sender/recipient too long (max 128 chars)"})
                return

            # watcher remains system-internal; agent -> system is allowed again
            # so operational reports can stay off the user-facing chat path.
            _system_only_recipients = {"watcher"}
            if recipient in _system_only_recipients and sender not in {"user", "system"}:
                self._respond(200, {"ok": True, "suppressed": True, "reason": f"'{recipient}' is not a valid recipient for agents"})
                return

            # Token-based sender validation (anti-impersonation).
            # In strict mode, every sender must authenticate and match token identity.
            _privileged_senders = {"user", "system"}
            if BRIDGE_STRICT_AUTH:
                ok, role, identity = self._require_authenticated()
                if not ok:
                    return
                if role == "user":
                    if sender not in _privileged_senders:
                        self._respond(403, {"error": "user token may only send as 'user' or 'system'"})
                        return
                elif role == "agent":
                    if sender != identity:
                        self._respond(403, {"error": "token sender mismatch"})
                        return
            else:
                token = self.headers.get("X-Bridge-Token", "")
                if sender not in _privileged_senders:
                    if token:
                        with AGENT_STATE_LOCK:
                            bound_agent = SESSION_TOKENS.get(token)
                        if bound_agent is None:
                            self._respond(403, {"error": "invalid session token"})
                            return
                        if sender != bound_agent:
                            # Server overrides from-field to prevent impersonation
                            print(f"[send] Token mismatch: from={sender} but token bound to {bound_agent} — overriding")
                            sender = bound_agent
                    else:
                        # No token, not a privileged sender — warn (transition phase)
                        print(f"[send] WARNING: No token for sender '{sender}' — allowing in transition phase")

            # Check if recipient exists (registered or special)
            _special_recipients = {"system", "user", "all", "all_managers", "leads"}
            # Also treat team:<id> as special
            if recipient.startswith("team:"):
                _special_recipients.add(recipient)
            if federation_target:
                _special_recipients.add(recipient)
            warning = None
            delivery_targets: list[str] | None = None
            if recipient not in _special_recipients:
                with AGENT_STATE_LOCK:
                    _recipient_registered = recipient in REGISTERED_AGENTS
                if not _recipient_registered:
                    warning = f"recipient '{recipient}' is not registered — message may not be delivered"
                    # Auto-start buddy agent on first message if offline
                    if recipient == "buddy":
                        _buddy_started = _auto_start_buddy_agent()
                        if _buddy_started:
                            warning = "buddy agent was offline — auto-started. Message stored for delivery."
            elif recipient in {"all", "all_managers", "leads"} or recipient.startswith("team:"):
                delivery_targets = _resolve_configured_message_targets(recipient, sender=sender)
                if recipient != "all" and not delivery_targets:
                    warning = f"recipient '{recipient}' currently resolves to 0 active targets"

            raw_channel = data.get("channel")
            msg_channel = str(raw_channel).strip() if raw_channel else None
            raw_team = data.get("team")
            msg_team = str(raw_team).strip() if raw_team else None

            # ── M3: Evidenz-Enforcement DISABLED by Leo (2026-03-07) ──
            # Keyword matching is cosmetic, not structural. Structural enforcement
            # lives in bridge_task_done (result_summary + evidence required).
            evidence_warning = None
            msg_meta = dict(meta) if isinstance(meta, dict) else None
            if federation_target:
                try:
                    fed_meta = _federation_send_outbound(sender, recipient, content)
                except ValueError as exc:
                    self._respond(400, {"error": str(exc)})
                    return
                except RuntimeError as exc:
                    self._respond(503, {"error": str(exc)})
                    return
                if msg_meta is None:
                    msg_meta = {}
                msg_meta["federation"] = fed_meta

            msg = append_message(
                sender, recipient, content,
                msg_meta,
                suppress_team_lead=False,
                reply_to=int(reply_to) if reply_to is not None else None,
                channel=msg_channel,
                team=msg_team,
            )
            event_bus.emit_message_sent(sender, recipient, msg_channel or "work")
            event_bus.emit_message_received(sender, recipient, msg_channel or "work")

            # Graceful Shutdown: detect [SHUTDOWN_ACK] from agents
            if "[SHUTDOWN_ACK]" in content and sender not in {"system", "user"}:
                _handle_shutdown_ack(sender)

            # M3 evidence-warning on /send: DISABLED by Leo (keyword matching is cosmetic)
            # Structural enforcement remains on bridge_task_done (result_summary + evidence)

            # Track agent activity: recipient is now busy (processing), sender just finished
            # Only track real agents, not system/user senders
            _non_agent = {"system", "user", "all", "all_managers", "leads"}
            if recipient.startswith("team:"):
                _non_agent.add(recipient)
            if federation_target:
                _non_agent.add(recipient)
            if recipient not in _non_agent:
                with AGENT_STATE_LOCK:
                    AGENT_BUSY[recipient] = True
                update_agent_status(recipient)
            if sender not in _non_agent:
                with AGENT_STATE_LOCK:
                    AGENT_BUSY[sender] = False
                    AGENT_LAST_SEEN[sender] = time.time()
                update_agent_status(sender)
            # Phase 1: Persist last sent message ID to agent state store
            if sender not in _non_agent and msg.get("id") is not None:
                _save_agent_state(sender, {
                    "last_message_id_sent": msg["id"],
                    "last_seen": utc_now_iso(),
                })

            if msg.get("suppressed"):
                response = {"ok": True, "suppressed": True, "reason": "dedup", "message": msg}
                if warning:
                    response["warning"] = warning
                if delivery_targets is not None:
                    response["delivery_targets"] = delivery_targets
                    response["delivery_count"] = len(delivery_targets)
                self._respond(200, response)
            else:
                response = {"ok": True, "message": msg}
                if warning:
                    response["warning"] = warning
                if delivery_targets is not None:
                    response["delivery_targets"] = delivery_targets
                    response["delivery_count"] = len(delivery_targets)
                if evidence_warning:
                    response["evidence_warning"] = evidence_warning
                self._respond(201, response)

            return

        if _handle_onboarding_post(self, path):
            return

        # POST /skills/assign — assign skills to an agent
        if _handle_skills_post(self, path):
            return

        if path == "/register":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            agent_id = str(data.get("agent_id", "")).strip()
            role = str(data.get("role", "")).strip()
            capabilities = data.get("capabilities", [])
            runtime_profile = _runtime_profile_for_agent(agent_id)
            runtime_caps = _runtime_profile_capabilities(agent_id)
            engine = str(data.get("engine", "")).strip().lower() or str(runtime_profile.get("engine", "")).strip().lower()
            # Hardening: Read session_nonce and context_lost (optional, backward-compatible)
            session_nonce = data.get("session_nonce")
            if session_nonce is not None:
                session_nonce = str(session_nonce).strip() or None
            context_lost = bool(data.get("context_lost", False))
            cli_identity = _cli_identity_bundle(agent_id, data)
            # Normalize: registration always records "cli_register" regardless
            # of whatever transport-level source the client sent.
            if cli_identity.get("cli_identity_source"):
                cli_identity["cli_identity_source"] = "cli_register"
            if not agent_id:
                self._respond(400, {"error": "field 'agent_id' is required"})
                return
            # Accept capabilities as list OR dict (structured capabilities)
            if not isinstance(capabilities, (list, dict)):
                capabilities = []
            if isinstance(capabilities, list):
                capabilities = _normalize_capability_list(capabilities)
            # Schema validation for dict capabilities
            if isinstance(capabilities, dict):
                VALID_CAP_KEYS = {
                    "shell": bool, "file_write": bool, "file_read": bool,
                    "network": bool, "browser": bool, "mcp_tools": list,
                    "sandbox_mode": str, "max_context_tokens": int,
                }
                sanitized: dict[str, Any] = {}
                for k, v in capabilities.items():
                    if k in VALID_CAP_KEYS:
                        if isinstance(v, VALID_CAP_KEYS[k]):
                            sanitized[k] = v
                    # Unknown keys silently dropped
                capabilities = sanitized
            if isinstance(runtime_profile, dict) and runtime_profile:
                incoming_caps = capabilities
                capabilities = list(runtime_caps)
                if incoming_caps != capabilities:
                    print(
                        f"[register] Overriding client capabilities for managed agent "
                        f"{agent_id}: incoming={incoming_caps!r} runtime={capabilities!r}"
                    )
            elif not capabilities and runtime_caps:
                capabilities = list(runtime_caps)

            existing_state = _load_agent_state(agent_id)

            # Hardening (T4/C6): Protect stored role — don't overwrite with empty string
            if not role:
                stored_role = existing_state.get("role", "") if existing_state else ""
                if stored_role:
                    role = stored_role
                    print(f"[register] Preserved stored role for {agent_id}: {role}")

            now_iso = utc_now_iso()
            now_ts = time.time()
            token = secrets.token_hex(32)
            with AGENT_STATE_LOCK:
                # Hardening (H1): Move old token to grace period instead of instant invalidation
                old_token = AGENT_TOKENS.pop(agent_id, None)
                if old_token:
                    SESSION_TOKENS.pop(old_token, None)
                    GRACE_TOKENS[old_token] = (agent_id, now_ts + TOKEN_GRACE_SECONDS)
                SESSION_TOKENS[token] = agent_id
                AGENT_TOKENS[agent_id] = token
                REGISTERED_AGENTS[agent_id] = {
                    "role": role,
                    "capabilities": capabilities,
                    "engine": engine,
                    "registered_at": now_iso,
                    "last_heartbeat": now_ts,
                    "last_heartbeat_iso": now_iso,
                    "resume_id": cli_identity.get("resume_id", ""),
                    "workspace": cli_identity.get("workspace", ""),
                    "project_root": cli_identity.get("project_root", ""),
                    "home_dir": cli_identity.get("home_dir", ""),
                    "instruction_path": cli_identity.get("instruction_path", ""),
                    "cli_identity_source": cli_identity.get("cli_identity_source", ""),
                }
                AGENT_LAST_SEEN[agent_id] = now_ts
            # Clear rate-limit and auth-failure state on successful re-registration
            with AGENT_STATE_LOCK:
                _was_rl = AGENT_RATE_LIMITED.pop(agent_id, None)
            if _was_rl:
                print(f"[register] Clearing rate-limit state for {agent_id}")
            _CLI_AUTH_ALERTED.discard(agent_id)
            ws_broadcast("agent_registered", {
                "agent_id": agent_id,
                "role": role,
                "capabilities": capabilities,
                "registered_at": now_iso,
            })
            print(f"[register] Agent registered: {agent_id} (role={role}, nonce={'yes' if session_nonce else 'no'}, context_lost={context_lost})")
            event_bus.emit_agent_online(agent_id, role)

            # Hardening: Decide whether to send CONTEXT RESTORE
            send_restore = _should_send_context_restore(agent_id, session_nonce, context_lost)

            # Update nonce tracking
            if session_nonce:
                AGENT_NONCES[agent_id] = session_nonce

            _restore_receive_cursor_from_state(agent_id, existing_state)

            # Save role to state store (preserve existing mode)
            state_updates: dict[str, Any] = {"role": role, "last_seen": now_iso}
            if "mode" not in existing_state:
                state_updates["mode"] = "normal"
            state_updates.update(
                {
                    "resume_id": cli_identity.get("resume_id", ""),
                    "workspace": cli_identity.get("workspace", ""),
                    "project_root": cli_identity.get("project_root", ""),
                    "home_dir": cli_identity.get("home_dir", ""),
                    "instruction_path": cli_identity.get("instruction_path", ""),
                    "cli_identity_source": cli_identity.get("cli_identity_source", ""),
                }
            )
            _save_agent_state(agent_id, state_updates)

            # Skills auto-provisioning: assign suggested skills if empty
            _auto_provision_skills(agent_id)

            if send_restore:
                saved_state = _load_agent_state(agent_id)
                restore_msg = _build_context_restore_message(agent_id, saved_state)
                if restore_msg:
                    append_message("system", agent_id, restore_msg,
                                   meta={"type": "context_restore"})
                    AGENT_LAST_CONTEXT_RESTORE[agent_id] = now_ts
                    print(f"[register] Context restored for {agent_id}")

            # Auto-index MEMORY.md into semantic memory (background, non-blocking)
            def _auto_index_memory(aid: str) -> None:
                try:
                    agent_home = _get_agent_home_dir(aid)
                    if not agent_home:
                        return
                    config_dir = _get_runtime_config_dir(aid)
                    memory_path = find_agent_memory_path(aid, agent_home, config_dir)
                    if not memory_path:
                        return
                    with open(memory_path, "r", encoding="utf-8") as f:
                        text = f.read()
                    if len(text) < 50:
                        return  # too small, skip
                    import semantic_memory
                    semantic_memory.index_scoped_text(
                        "agent",
                        aid,
                        text,
                        metadata={"source": "MEMORY.md", "auto_indexed": True, "memory_path": memory_path},
                        document_id=f"memory::{aid}::{memory_path}",
                        replace_document=True,
                    )
                    print(f"[register] Auto-indexed MEMORY.md for {aid} ({len(text)} chars)")
                except Exception as exc:
                    print(f"[register] Auto-index failed for {aid}: {exc}")
            threading.Thread(target=_auto_index_memory, args=(agent_id,), daemon=True).start()

            # P1: Memory-Bootstrap — create MEMORY.md template if agent has none
            def _memory_bootstrap(aid: str, aid_role: str) -> None:
                try:
                    agent_home = _get_agent_home_dir(aid)
                    if not agent_home:
                        return
                    config_dir = _get_runtime_config_dir(aid)
                    existing_memory = find_agent_memory_path(aid, agent_home, config_dir)
                    if existing_memory:
                        return
                    memory_path = ensure_agent_memory_file(aid, aid_role, agent_home, config_dir)
                    if memory_path:
                        print(f"[register] Memory-Bootstrap: Created MEMORY.md for {aid} at {memory_path}")
                except Exception as exc:
                    print(f"[register] Memory-Bootstrap failed for {aid}: {exc}")
            threading.Thread(target=_memory_bootstrap, args=(agent_id, role), daemon=True).start()

            # P2: Catch-up missed automations (background, non-blocking)
            def _run_catch_up(aid: str) -> None:
                try:
                    import automation_engine
                    results = automation_engine.check_catch_up(aid)
                    if results:
                        total = sum(r["executed"] for r in results)
                        print(f"[register] Catch-up for {aid}: {len(results)} automations, {total} runs executed")
                except Exception as exc:
                    print(f"[register] Catch-up failed for {aid}: {exc}")
            threading.Thread(target=_run_catch_up, args=(agent_id,), daemon=True).start()

            # G9 FIX: Push pending tasks on registration (split-brain recovery after restart)
            def _push_pending_tasks_on_register(aid: str) -> None:
                """Notify agent of unclaimed/active tasks assigned to them, immediately on registration."""
                import time as _time
                _time.sleep(2)  # Short delay to let agent's receive buffer initialize
                with TASK_LOCK:
                    pending = [
                        dict(t) for t in TASKS.values()
                        if t.get("assigned_to") == aid and t.get("state") in ("created", "claimed", "acked")
                    ]
                if not pending:
                    return
                for t in pending:
                    tid = t.get("task_id", "")
                    title = str(t.get("title", tid))[:200]
                    state = t.get("state", "created")
                    creator = t.get("created_by", "unknown")
                    desc = str(t.get("description", ""))[:300]
                    if state == "created":
                        msg = (
                            f"[RESTART RECOVERY] Du hast einen unbearbeiteten Task:\n"
                            f"Task: '{title}' (ID: {tid}) — von {creator}\n"
                            f"Beschreibung: {desc}\n\n"
                            f"SOFORT ausfuehren:\n"
                            f"1. bridge_task_claim(task_id='{tid}')\n"
                            f"2. bridge_task_ack(task_id='{tid}')\n"
                            f"3. Task bearbeiten\n"
                            f"4. bridge_task_done(task_id='{tid}', result_summary='...')"
                        )
                    else:
                        msg = (
                            f"[RESTART RECOVERY] Task '{title}' (ID: {tid}) ist in deinem Besitz (state={state}).\n"
                            f"Du kannst direkt weitermachen oder erneut claimen: bridge_task_claim(task_id='{tid}')"
                        )
                    append_message("system", aid, msg, meta={"type": "restart_task_recovery", "task_id": tid, "state": state})
                print(f"[register] G9: Pushed {len(pending)} pending task(s) to {aid} on registration")
            threading.Thread(target=_push_pending_tasks_on_register, args=(agent_id,), daemon=True).start()

            # Agent-Discovery: Include online agents + roles in register response
            with AGENT_STATE_LOCK:
                discovery_agents = []
                for aid, reg in REGISTERED_AGENTS.items():
                    if aid == agent_id:
                        continue  # skip self
                    hb_age = now_ts - reg.get("last_heartbeat", 0)
                    if hb_age < 120:  # only truly online agents
                        discovery_agents.append({
                            "id": aid,
                            "role": reg.get("role", ""),
                            "online": True,
                        })

            self._respond(200, {
                "ok": True,
                "registered_at": now_iso,
                "session_token": token,
                "discovery": {
                    "online_agents": discovery_agents,
                    "total_online": len(discovery_agents),
                },
            })
            return

        if path == "/heartbeat":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            agent_id = str(data.get("agent_id", "")).strip()
            if not agent_id:
                self._respond(400, {"error": "field 'agent_id' is required"})
                return
            if BRIDGE_STRICT_AUTH:
                ok, role, identity = self._require_authenticated()
                if not ok:
                    return
                if role == "agent" and identity != agent_id:
                    self._respond(403, {"error": "token agent mismatch for heartbeat endpoint"})
                    return
            now_iso = utc_now_iso()
            now_ts = time.time()
            with AGENT_STATE_LOCK:
                reg = REGISTERED_AGENTS.get(agent_id)
                is_registered = reg is not None
                if is_registered:
                    reg["last_heartbeat"] = now_ts
                    reg["last_heartbeat_iso"] = now_iso
                # Update AGENT_LAST_SEEN for backward compatibility
                AGENT_LAST_SEEN[agent_id] = now_ts
            update_agent_status(agent_id)
            # Hardening (M2): Include registration status so MCP knows if re-register needed
            self._respond(200, {"ok": True, "timestamp": now_iso, "registered": is_registered})
            return

        # Phase 3: Explicit context save — POST /state/{agent_id}
        state_match = re.match(r"^/state/([^/]+)$", path)
        if state_match:
            agent_id = state_match.group(1)
            if BRIDGE_STRICT_AUTH:
                ok, role, identity = self._require_authenticated()
                if not ok:
                    return
                if role == "agent" and identity != agent_id:
                    self._respond(403, {"error": "token agent mismatch for state endpoint"})
                    return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            updates: dict[str, Any] = {}
            if "context_summary" in data:
                updates["context_summary"] = str(data["context_summary"]).strip()
            if "open_tasks" in data:
                tasks = data["open_tasks"]
                if isinstance(tasks, list):
                    updates["open_tasks"] = [str(t) for t in tasks]
            if updates:
                _save_agent_state(agent_id, updates)
                self._respond(200, {"ok": True, "saved": list(updates.keys())})
            else:
                self._respond(400, {"error": "no valid fields to save (expected: context_summary, open_tasks)"})
            return

        if path == "/agents/cleanup":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            data = self._parse_json_body() or {}
            ttl = float(data.get("ttl_seconds", 300))
            before_count = len(REGISTERED_AGENTS)
            _auto_cleanup_agents(ttl)
            after_count = len(REGISTERED_AGENTS)
            removed = before_count - after_count
            self._respond(200, {"ok": True, "removed": removed, "remaining": after_count})
            return

        if path == "/runtime/stop":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            try:
                stopped = stop_known_agents()
            except Exception as exc:
                print(f"[ERROR] stop_known_agents failed: {exc}")
                stopped = [{"error": str(exc)}]
            _clear_runtime_configuration(team_lead_reason="runtime_stop")
            ws_broadcast("runtime", {"runtime": runtime_snapshot()})
            self._respond(200, {"ok": True, "stopped": stopped, "runtime": runtime_snapshot()})
            return

        if path == "/teamlead/activate":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            activate = parse_bool(data.get("active"), True)
            with RUNTIME_LOCK:
                RUNTIME["team_lead_enabled"] = activate
                RUNTIME["team_lead_cli_enabled"] = activate
            with TEAM_LEAD_LOCK:
                TEAM_LEAD_STATE["active"] = activate
                TEAM_LEAD_STATE["stopped"] = not activate
                TEAM_LEAD_STATE["stop_reason"] = "" if activate else "user_deactivated"
                TEAM_LEAD_STATE["last_event_at"] = utc_now_iso()
            status = "activated" if activate else "deactivated"
            # Notify all via message
            append_message(
                sender="system",
                recipient="all",
                content=f"Team Lead {status} by user.",
                meta={"control": "teamlead_toggle", "active": activate},
            )
            ws_broadcast("runtime", {"runtime": runtime_snapshot()})
            self._respond(200, {"ok": True, "active": activate, "status": status})
            return

        if path == "/teamlead/control":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            action = str(data.get("action", "")).strip().lower()
            target = str(data.get("target", "")).strip()
            if action not in ("stop", "resume", "stop_all", "resume_all"):
                self._respond(400, {"error": f"unknown action: {action}"})
                return

            if action in ("stop_all", "stop"):
                control_code = "stop_loop"
                control_text = "STOP"
            else:
                control_code = "resume_loop"
                control_text = "RESUME"

            if action in ("stop_all", "resume_all"):
                target = "all"

            if not target:
                self._respond(400, {"error": "target is required"})
                return

            append_message(
                sender=TEAM_LEAD_ID,
                recipient=target,
                content=f"TEAMLEAD CONTROL: {control_text}",
                meta={"control": control_code, "source": TEAM_LEAD_ID, "via": "api"},
            )
            self._respond(200, {"ok": True, "action": action, "target": target})
            return

        if path == "/teamlead/scope":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            if _handle_teamlead_scope_post(self, path):
                return
            self._respond(500, {"error": "teamlead scope handler not available"})
            return

        if path == "/runtime/configure":
            if BRIDGE_STRICT_AUTH:
                ok, _, _ = self._require_platform_operator()
                if not ok:
                    return
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            runtime_request_meta = {
                "remote_addr": self.client_address[0] if self.client_address else "",
                "x_bridge_agent": str(self.headers.get("X-Bridge-Agent", "")).strip(),
                "user_agent": str(self.headers.get("User-Agent", "")).strip(),
                "referer": str(self.headers.get("Referer", "")).strip(),
            }
            runtime_payload_summary = _runtime_configure_payload_summary(data)
            _append_runtime_configure_audit("request", runtime_request_meta, runtime_payload_summary)

            with RUNTIME_LOCK:
                current = dict(RUNTIME)

            current_a_engine = str(current.get("agent_a_engine", "codex")).strip().lower()
            current_b_engine = str(current.get("agent_b_engine", "claude")).strip().lower()

            try:
                raw_agents = [
                    agent
                    for agent in (data.get("agents") if isinstance(data.get("agents"), list) else [])
                    if isinstance(agent, dict)
                ]
                raw_agent_engines = [str(agent.get("engine", "")).strip().lower() for agent in raw_agents]
                explicit_runtime_agents = bool(raw_agents) and all(raw_agent_engines)
                if raw_agents and any(not engine for engine in raw_agent_engines):
                    self._respond(
                        400,
                        {"error": "explicit runtime agent payload requires an engine for every agent"},
                    )
                    return

                agent_a_engine = str(data.get("agent_a_engine", "")).strip().lower()
                agent_b_engine = str(data.get("agent_b_engine", "")).strip().lower()

                if explicit_runtime_agents:
                    agent_a_engine = raw_agent_engines[0]
                    agent_b_engine = raw_agent_engines[1] if len(raw_agent_engines) >= 2 else raw_agent_engines[0]
                if not agent_a_engine:
                    agent_a_engine = current_a_engine
                if not agent_b_engine:
                    agent_b_engine = current_b_engine
                team_lead_engine = str(
                    data.get("team_lead_engine", current.get("team_lead_engine", "codex"))
                ).strip().lower() or "codex"
                live_engines = _detect_available_engines()
                if team_lead_engine not in live_engines:
                    self._respond(
                        400,
                        {
                            "error": "invalid team_lead_engine selection",
                            "available_engines": sorted(live_engines),
                        },
                    )
                    return

                if not explicit_runtime_agents and (agent_a_engine not in live_engines or agent_b_engine not in live_engines):
                    self._respond(
                        400,
                        {
                            "error": "invalid agent engine selection",
                            "available_engines": sorted(live_engines),
                        },
                    )
                    return

                project_path = validate_project_path(data.get("project_path"), PROJECTS_BASE_DIR)
                if not project_path:
                    self._respond(403, {"error": "path outside allowed directory"})
                    return
                if not os.path.isdir(project_path):
                    self._respond(400, {"error": f"project_path does not exist: {project_path}"})
                    return
                project_name = str(data.get("project_name", current.get("project_name", ""))).strip()
                if not project_name:
                    project_name = os.path.basename(project_path.rstrip("/")) or "runtime-project"
                try:
                    scope_file = resolve_team_lead_scope_file(
                        project_path,
                        data.get("team_lead_scope_file", current.get("team_lead_scope_file", "")),
                    )
                except ValueError as exc:
                    self._respond(400, {"error": str(exc)})
                    return

                requested_team_lead_cli = parse_bool(
                    data.get("team_lead_cli_enabled"),
                    parse_bool(
                        data.get("team_lead_enabled"),
                        bool(current.get("team_lead_cli_enabled", current.get("team_lead_enabled", True))),
                    ),
                )
                if explicit_runtime_agents and requested_team_lead_cli:
                    self._respond(
                        400,
                        {
                            "error": "team_lead_cli_enabled is not supported for explicit multi-agent runtime; model leadership via agents[].hierarchyLevel/reportsTo instead"
                        },
                    )
                    return

                config = {
                    "pair_mode": "multi" if explicit_runtime_agents else pair_mode_of(agent_a_engine, agent_b_engine),
                    "agent_a_engine": agent_a_engine,
                    "agent_b_engine": agent_b_engine,
                    "project_path": project_path,
                    "allow_peer_auto": parse_bool(data.get("allow_peer_auto"), bool(current.get("allow_peer_auto", False))),
                    "peer_auto_require_flag": parse_bool(
                        data.get("peer_auto_require_flag"),
                        bool(current.get("peer_auto_require_flag", True)),
                    ),
                    "max_peer_hops": parse_non_negative_int(
                        data.get("max_peer_hops"),
                        int(current.get("max_peer_hops", 20)),
                    ),
                    "max_turns": parse_non_negative_int(data.get("max_turns"), int(current.get("max_turns", 0))),
                    "process_all": parse_bool(data.get("process_all"), bool(current.get("process_all", False))),
                    "keep_history": parse_bool(data.get("keep_history"), bool(current.get("keep_history", False))),
                    "timeout": parse_non_negative_int(data.get("timeout"), int(current.get("timeout", 90))),
                    "team_lead_enabled": parse_bool(
                        data.get("team_lead_enabled"),
                        bool(current.get("team_lead_enabled", True)),
                    ),
                    "team_lead_max_peer_messages": parse_non_negative_int(
                        data.get("team_lead_max_peer_messages"),
                        int(current.get("team_lead_max_peer_messages", 40)),
                    ),
                    "team_lead_cli_enabled": requested_team_lead_cli if not explicit_runtime_agents else False,
                    "project_name": project_name,
                    "team_lead_engine": team_lead_engine,
                    "team_lead_scope_file": scope_file,
                    "agent_a_position": str(data.get("agent_a_position", "")).strip(),
                    "agent_b_position": str(data.get("agent_b_position", "")).strip(),
                }
            except Exception as exc:  # noqa: BLE001
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"runtime configure unexpected failure: {exc}"},
                )
                self._respond(500, {"error": f"runtime configure unexpected failure: {exc}"})
                return

            try:
                if explicit_runtime_agents:
                    runtime_layout = _build_explicit_runtime_layout(raw_agents, live_engines=live_engines)
                else:
                    runtime_layout = resolve_runtime_specs(
                        agent_a_engine,
                        agent_b_engine,
                        team_lead_cli_enabled=bool(config.get("team_lead_cli_enabled", False)),
                        team_lead_engine=team_lead_engine,
                        team_lead_scope_file=scope_file,
                    )
                agent_profiles = _build_runtime_agent_profiles(
                    data,
                    runtime_layout,
                    project_name=project_name,
                    project_path=project_path,
                )
                config["pair_mode"] = _runtime_pair_mode_for_layout(runtime_layout)
                config["agent_profiles"] = agent_profiles
                config["runtime_specs"] = _clone_runtime_layout(runtime_layout)
                config["runtime_overlay"] = _build_runtime_overlay(project_name, project_path, agent_profiles)
                runtime_agent_ids = [spec["id"] for spec in runtime_layout]
            except Exception as exc:  # noqa: BLE001
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"failed to build runtime config: {exc}"},
                )
                self._respond(500, {"error": f"failed to build runtime config: {exc}"})
                return
            with LOCK:
                for agent_id in runtime_agent_ids:
                    if config.get("keep_history", False):
                        CURSORS.pop(agent_id, None)
                    else:
                        CURSORS[agent_id] = len(MESSAGES)

            try:
                # V2: Kill existing tmux sessions + old PID-based agents
                stopped = stop_known_agents()
                # Also kill any acw_* tmux sessions from previous runs
                for agent_id in runtime_agent_ids:
                    kill_agent_session(agent_id)
                # Clear previous registrations
                REGISTERED_AGENTS.clear()
            except Exception as exc:  # noqa: BLE001
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"failed to reset runtime: {exc}"},
                )
                self._respond(500, {"error": f"failed to reset runtime: {exc}"})
                return

            try:
                started = open_agent_sessions(config)
            except Exception as exc:  # noqa: BLE001
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"failed to open agent sessions: {exc}"},
                )
                self._respond(500, {"error": f"failed to open agent sessions: {exc}", "stopped": stopped})
                return

            failed_starts = [
                dict(item)
                for item in started
                if isinstance(item, dict) and not bool(item.get("alive"))
            ]
            if failed_starts:
                try:
                    stop_known_agents()
                except Exception as exc:
                    print(f"[runtime] WARN: cleanup after failed start failed: {exc}")
                _clear_runtime_configuration(team_lead_reason="runtime_configure_failed")
                snapshot = runtime_snapshot()
                ws_broadcast("runtime", {"runtime": snapshot})
                failed_ids = [str(item.get("id", "")).strip() for item in failed_starts if str(item.get("id", "")).strip()]
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"runtime configure failed: failed to start runtime agents: {failed_ids}"},
                )
                self._respond(
                    500,
                    {
                        "error": f"failed to start runtime agents: {failed_ids}",
                        "stopped": stopped,
                        "started": started,
                        "failed": failed_starts,
                        "runtime": snapshot,
                    },
                )
                return

            try:
                # V2: Wait for agent registration (poll REGISTERED_AGENTS) instead of PID stabilization
                registration_timeout = min(
                    max(float(data.get("stabilize_seconds", 30.0)), 0.0),
                    30.0,
                )
                all_registered = _wait_for_agent_registration(runtime_agent_ids, registration_timeout)
                registered_snapshot = _registered_agents_snapshot()
                missing_registrations = [
                    agent_id for agent_id in runtime_agent_ids
                    if agent_id not in registered_snapshot
                ]
                dead_sessions = [
                    agent_id for agent_id in runtime_agent_ids
                    if not is_session_alive(agent_id)
                ]
                if not all_registered or missing_registrations or dead_sessions:
                    failed_runtime_agents = _collect_runtime_registration_failures(
                        runtime_agent_ids,
                        missing_registrations,
                        dead_sessions,
                    )
                    try:
                        stop_known_agents()
                    except Exception as cleanup_exc:
                        print(f"[runtime] WARN: cleanup after registration failure failed: {cleanup_exc}")
                    _clear_runtime_configuration(team_lead_reason="runtime_configure_failed")
                    snapshot = runtime_snapshot()
                    ws_broadcast("runtime", {"runtime": snapshot})
                    details: list[str] = []
                    if missing_registrations:
                        details.append(f"missing registrations: {missing_registrations}")
                    if dead_sessions:
                        details.append(f"dead sessions: {dead_sessions}")
                    details.extend(_summarize_runtime_registration_failures(failed_runtime_agents))
                    error_text = "runtime agents failed to stabilize"
                    if details:
                        error_text += f" ({'; '.join(details)})"
                    _append_runtime_configure_audit(
                        "error",
                        runtime_request_meta,
                        runtime_payload_summary,
                        {"error": f"runtime configure failed: {error_text}"},
                    )
                    self._respond(
                        500,
                        {
                            "error": error_text,
                            "stopped": stopped,
                            "started": started,
                            "failed": failed_runtime_agents,
                            "missing_registrations": missing_registrations,
                            "dead_sessions": dead_sessions,
                            "runtime": snapshot,
                        },
                    )
                    return

                kickoff = str(data.get("kickoff", "")).strip()
                kickoff_sender = str(data.get("kickoff_from", "user")).strip() or "user"
                kickoff_target = str(data.get("kickoff_to", "")).strip()
                if kickoff:
                    if not kickoff_target and started:
                        kickoff_target = str(started[0]["id"])
                    if kickoff_target:
                        kickoff_meta: dict[str, Any] = {"type": "kickoff", "via": "runtime.configure"}
                        raw_kickoff_meta = data.get("kickoff_meta")
                        if isinstance(raw_kickoff_meta, dict):
                            for key, value in raw_kickoff_meta.items():
                                if isinstance(key, str) and key.strip():
                                    kickoff_meta[key] = value
                        append_message(
                            sender=kickoff_sender,
                            recipient=kickoff_target,
                            content=kickoff,
                            meta=kickoff_meta,
                        )

                with RUNTIME_LOCK:
                    RUNTIME.update(config)
                    RUNTIME["last_start_at"] = utc_now_iso()
                _persist_runtime_overlay(config.get("runtime_overlay"))
                reset_team_lead_state("runtime_configure")
                if bool(config.get("team_lead_cli_enabled", False)):
                    ensure_parent_dir(scope_file)
                    if not os.path.exists(scope_file):
                        Path(scope_file).write_text("", encoding="utf-8")

                snapshot = runtime_snapshot()
                ws_broadcast("runtime", {"runtime": snapshot})
            except Exception as exc:  # noqa: BLE001
                _append_runtime_configure_audit(
                    "error",
                    runtime_request_meta,
                    runtime_payload_summary,
                    {"error": f"runtime configure failed: {exc}"},
                )
                self._respond(
                    500,
                    {
                        "error": f"runtime configure failed: {exc}",
                        "stopped": stopped,
                        "started": started,
                    },
                )
                return

            _append_runtime_configure_audit(
                "success",
                runtime_request_meta,
                runtime_payload_summary,
                {
                    "pair_mode": config.get("pair_mode", ""),
                    "project_name": config.get("project_name", ""),
                    "project_path": config.get("project_path", ""),
                    "started_ids": [str(item.get("id", "")).strip() for item in started if isinstance(item, dict)],
                },
            )

            self._respond(
                200,
                {
                    "ok": True,
                    "stopped": stopped,
                    "started": started,
                    "runtime": snapshot,
                },
            )
            return

        if path == "/projects/create":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            try:
                payload = create_project(data)
            except Exception as exc:  # noqa: BLE001
                self._respond(400, {"error": str(exc)})
                return
            self._respond(201, payload)
            return

        if path == "/projects/save-notes":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            raw_path = data.get("project_path")
            if not raw_path:
                self._respond(400, {"error": "project_path is required"})
                return
            project_path = validate_project_path(raw_path, PROJECTS_BASE_DIR)
            if not project_path:
                self._respond(403, {"error": "path outside allowed directory"})
                return
            if not os.path.isdir(project_path):
                self._respond(404, {"error": f"project not found: {project_path}"})
                return
            notes = str(data.get("notes", ""))
            project_md = os.path.join(project_path, "PROJECT.md")
            try:
                Path(project_md).write_text(notes, encoding="utf-8")
            except OSError as exc:
                self._respond(500, {"error": f"could not write PROJECT.md: {exc}"})
                return
            raw_tags = data.get("tags")
            if isinstance(raw_tags, list):
                tags_list = [str(t).strip() for t in raw_tags if str(t).strip()]
                tags_dir = os.path.join(project_path, ".bridge")
                os.makedirs(tags_dir, exist_ok=True)
                tags_path = os.path.join(tags_dir, "tags.json")
                try:
                    Path(tags_path).write_text(
                        json.dumps(tags_list, ensure_ascii=False) + "\n", encoding="utf-8"
                    )
                except OSError as exc:
                    self._respond(500, {"error": f"could not write tags.json: {exc}"})
                    return
            self._respond(200, {"ok": True, "project_path": project_path})
            return

        if path == "/projects/upload":
            parts = self._parse_multipart()
            if not parts:
                self._respond(400, {"error": "no multipart data or empty upload"})
                return
            project_path_part = None
            file_parts: list[dict[str, Any]] = []
            for part in parts:
                if part["name"] == "project_path" and not part["filename"]:
                    project_path_part = part["data"].decode("utf-8", errors="replace").strip()
                elif part["filename"]:
                    file_parts.append(part)
            if not project_path_part:
                self._respond(400, {"error": "project_path field is required"})
                return
            project_path = validate_project_path(project_path_part, PROJECTS_BASE_DIR)
            if not project_path:
                self._respond(403, {"error": "path outside allowed directory"})
                return
            if not os.path.isdir(project_path):
                self._respond(404, {"error": f"project not found: {project_path}"})
                return
            uploads_dir = os.path.join(project_path, ".bridge", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            _PROJ_UPLOAD_MAX_FILE = 50 * 1024 * 1024   # 50 MB per file
            _PROJ_UPLOAD_MAX_TOTAL = 200 * 1024 * 1024  # 200 MB total
            total_size = sum(len(fp["data"]) for fp in file_parts)
            if total_size > _PROJ_UPLOAD_MAX_TOTAL:
                self._respond(413, {"error": f"total upload size {total_size} exceeds {_PROJ_UPLOAD_MAX_TOTAL // (1024*1024)}MB limit"})
                return
            saved: list[dict[str, Any]] = []
            errors: list[str] = []
            for fp in file_parts:
                raw_name = fp["filename"]
                if len(fp["data"]) > _PROJ_UPLOAD_MAX_FILE:
                    errors.append(f"{raw_name}: exceeds {_PROJ_UPLOAD_MAX_FILE // (1024*1024)}MB per-file limit")
                    continue
                safe_name = SAFE_NAME_RE.sub("-", raw_name).strip("-._")
                if not safe_name:
                    safe_name = f"upload-{int(time.time())}"
                dest = os.path.join(uploads_dir, safe_name)
                if not is_within_directory(dest, uploads_dir):
                    continue
                try:
                    with open(dest, "wb") as fh:
                        fh.write(fp["data"])
                    saved.append({"filename": safe_name, "path": dest, "size": len(fp["data"])})
                except OSError:
                    continue
            resp: dict[str, Any] = {"ok": True, "uploaded": saved, "count": len(saved)}
            if errors:
                resp["errors"] = errors
            self._respond(200, resp)
            return

        # POST /chat/upload — upload files for chat attachments
        if path == "/chat/upload":
            parts = self._parse_multipart()
            if not parts:
                self._respond(400, {"error": "no multipart data or empty upload"})
                return
            file_parts = [p for p in parts if p.get("filename")]
            if not file_parts:
                self._respond(400, {"error": "no files in upload"})
                return
            uploaded: list[dict[str, Any]] = []
            errors: list[str] = []
            for fp in file_parts:
                raw_name = fp["filename"]
                file_data = fp["data"]
                # Size check
                if len(file_data) > CHAT_UPLOAD_MAX_SIZE:
                    errors.append(f"{raw_name}: exceeds {CHAT_UPLOAD_MAX_SIZE // (1024*1024)}MB limit")
                    continue
                # MIME type check
                mime_type, _ = mimetypes.guess_type(raw_name)
                if not mime_type:
                    mime_type = "application/octet-stream"
                allowed = any(mime_type.startswith(prefix) for prefix in CHAT_UPLOAD_ALLOWED_MIME_PREFIXES)
                if not allowed:
                    errors.append(f"{raw_name}: MIME type '{mime_type}' not allowed")
                    continue
                # Generate safe filename with UUID prefix
                safe_name = SAFE_NAME_RE.sub("-", raw_name).strip("-._")
                if not safe_name:
                    safe_name = "upload"
                file_id = str(uuid.uuid4())[:8]
                dest_name = f"{file_id}_{safe_name}"
                dest_path = os.path.join(CHAT_UPLOADS_DIR, dest_name)
                if not is_within_directory(dest_path, CHAT_UPLOADS_DIR):
                    errors.append(f"{raw_name}: path traversal denied")
                    continue
                try:
                    with open(dest_path, "wb") as fh:
                        fh.write(file_data)
                    uploaded.append({
                        "id": file_id,
                        "filename": dest_name,
                        "original_name": raw_name,
                        "url": f"/files/{dest_name}",
                        "mime": mime_type,
                        "size": len(file_data),
                    })
                except OSError as exc:
                    errors.append(f"{raw_name}: write failed: {exc}")
            response: dict[str, Any] = {"ok": len(uploaded) > 0, "files": uploaded}
            if errors:
                response["errors"] = errors
            self._respond(200, response)
            return

        if path == "/agent/config":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            project_path = validate_project_path(data.get("project_path"), PROJECTS_BASE_DIR)
            if not project_path:
                self._respond(403, {"error": "path outside allowed directory"})
                return
            engine = str(data.get("engine", "claude")).strip().lower()
            action = str(data.get("action", "")).strip()
            if engine not in CONFIG_ENGINES:
                self._respond(400, {"error": f"unsupported engine: {engine}"})
                return

            if action == "save_instruction":
                content = str(data.get("content", ""))
                inst_file = agent_instruction_file(project_path, engine)
                ensure_parent_dir(inst_file)
                try:
                    Path(inst_file).write_text(content, encoding="utf-8")
                except OSError as exc:
                    self._respond(500, {"error": f"could not write file: {exc}"})
                    return
                self._respond(200, {"ok": True, "file": inst_file, "bytes": len(content.encode("utf-8"))})
                return

            if action == "set_permission":
                permission = str(data.get("permission", "")).strip()
                value = parse_bool(data.get("value"), False)
                valid_perms = {"web_search", "web_fetch", "file_read", "file_write", "shell", "auto_approve", "full_filesystem"}
                if permission not in valid_perms:
                    self._respond(400, {"error": f"unknown permission: {permission}"})
                    return
                try:
                    write_agent_permission(project_path, engine, permission, value)
                except OSError as exc:
                    self._respond(500, {"error": f"could not write config: {exc}"})
                    return
                perms = read_agent_permissions(project_path, engine)
                self._respond(200, {"ok": True, "permission": permission, "value": value, "permissions": perms})
                return

            if action == "open_editor":
                inst_file = agent_instruction_file(project_path, engine)
                if not os.path.exists(inst_file):
                    ensure_parent_dir(inst_file)
                    Path(inst_file).write_text("", encoding="utf-8")
                try:
                    subprocess.Popen(["xdg-open", inst_file], start_new_session=True)  # noqa: S603
                except OSError as exc:
                    self._respond(500, {"error": f"xdg-open failed: {exc}"})
                    return
                self._respond(200, {"ok": True, "file": inst_file})
                return

            self._respond(400, {"error": f"unknown action: {action}"})
            return

        if path == "/agent/config/generate":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            project_path = validate_project_path(data.get("project_path"), PROJECTS_BASE_DIR)
            if not project_path:
                self._respond(403, {"error": "path outside allowed directory"})
                return
            engine = str(data.get("engine", "claude")).strip().lower()
            slot = str(data.get("slot", "a")).strip().lower()
            if engine not in CONFIG_ENGINES:
                self._respond(400, {"error": f"unsupported engine: {engine}"})
                return
            inst_file = agent_instruction_file(project_path, engine)
            filename = os.path.basename(inst_file)
            slot_label = {"lead": "teamlead", "a": "A", "b": "B"}.get(slot, slot)
            scope_content = ""
            scope_file = os.path.join(project_path, "teamlead.md")
            if os.path.isfile(scope_file):
                try:
                    scope_content = Path(scope_file).read_text(encoding="utf-8").strip()
                except OSError:
                    scope_content = ""
            scope_section = f"\nScope:\n{scope_content}" if scope_content else ""
            prompt = (
                f"Erstelle die Instruktionsdatei für Agent {slot_label} mit Engine {engine}.\n"
                f"Dateiname: {filename}\n"
                f"Projektpfad: {project_path}{scope_section}\n"
                f"Erstelle sinnvolle, präzise Instruktionen für diesen Agent in seiner Rolle.\n"
                f"Schreibe den Inhalt direkt als Antwort."
            )
            msg = append_message(
                sender="user",
                recipient=TEAM_LEAD_ID,
                content=prompt,
                meta={"type": "auto_generate", "engine": engine, "slot": slot, "target_file": inst_file},
            )
            key = f"{slot}:{engine}:{project_path}"
            with AUTO_GEN_LOCK:
                AUTO_GEN_PENDING[key] = {
                    "msg_id": int(msg["id"]),
                    "file_path": inst_file,
                    "ts": time.time(),
                }
            self._respond(200, {
                "ok": True,
                "msg_id": msg["id"],
                "target_file": inst_file,
                "pending_key": key,
            })
            return

        if _handle_memory_post(self, path):
            return

        if _handle_board_post(self, path):
            return

        # --- Approval Gate POST endpoints ---
        if path == "/approval/request":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            agent_id = str(data.get("agent_id", "")).strip()
            action = str(data.get("action", "")).strip()
            target = str(data.get("target", "")).strip()
            description = str(data.get("description", "")).strip()
            risk_level = str(data.get("risk_level", "low")).strip()
            payload = data.get("payload") or {}
            timeout_seconds = APPROVAL_DEFAULT_TIMEOUT
            raw_timeout = data.get("timeout_seconds")
            if raw_timeout is not None:
                try:
                    timeout_seconds = max(30, min(int(raw_timeout), 1800))
                except (ValueError, TypeError):
                    pass

            if not agent_id or not action or not description:
                self._respond(400, {"error": "fields 'agent_id', 'action', 'description' are required"})
                return

            # Validate action against allowlist — no wildcards
            if action not in ALLOWED_APPROVAL_ACTIONS:
                self._respond(400, {
                    "error": f"unknown action '{action}'",
                    "allowed": sorted(ALLOWED_APPROVAL_ACTIONS),
                })
                return

            # Validate risk_level
            if risk_level not in ("low", "medium", "high"):
                risk_level = "low"

            # Payload size limit: 10KB
            payload_str = json.dumps(payload, ensure_ascii=False) if payload else ""
            if len(description) + len(payload_str) > 10240:
                self._respond(400, {"error": "payload too large (max 10KB for description + payload)"})
                return

            # Standing Approval check: auto-approve if SA matches
            sa = _check_standing_approval(action, agent_id, target)
            if sa:
                sa_id = sa["id"]
                _sa_increment_usage(sa_id)
                _sa_audit_log({
                    "sa_id": sa_id,
                    "agent": agent_id,
                    "action": action,
                    "target": target,
                    "result": "auto_approved",
                    "use_count": sa.get("use_count", 0) + 1,
                    "description": description,
                })
                print(f"[approval] Auto-approved via Standing Approval {sa_id} for {agent_id} — {action}")
                self._respond(200, {
                    "ok": True,
                    "status": "auto_approved",
                    "standing_approval_id": sa_id,
                    "agent_id": agent_id,
                    "action": action,
                    "target": target,
                    "payload": payload if isinstance(payload, dict) else {},
                })
                return

            # Max 10 pending requests per agent
            with APPROVAL_LOCK:
                pending_count = sum(
                    1 for r in APPROVAL_REQUESTS.values()
                    if r["agent_id"] == agent_id and r["status"] == "pending"
                )
                if pending_count >= 10:
                    self._respond(429, {"error": f"agent '{agent_id}' has too many pending requests (max 10)"})
                    return

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=timeout_seconds)

            request_id = _approval_generate_id()
            req: dict[str, Any] = {
                "request_id": request_id,
                "agent_id": agent_id,
                "action": action,
                "target": target,
                "description": description,
                "risk_level": risk_level,
                "payload": payload if isinstance(payload, dict) else {},
                "status": "pending",
                "requested_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "decided_at": None,
                "decided_by": None,
                "comment": None,
            }

            with APPROVAL_LOCK:
                APPROVAL_REQUESTS[request_id] = req

            # WebSocket push: UI sees the request immediately
            ws_broadcast("approval_request", req)
            print(f"[approval] New request: {request_id} from {agent_id} — {action}: {description}")

            self._respond(201, {
                "ok": True,
                "request_id": request_id,
                "status": "pending",
                "expires_at": expires_at.isoformat(),
            })
            return

        if path == "/approval/respond":
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            request_id = str(data.get("request_id", "")).strip()
            decision = str(data.get("decision", "")).strip()
            comment = str(data.get("comment", "")).strip()
            decided_by = str(data.get("decided_by", "user")).strip()

            if not request_id or decision not in ("approved", "denied"):
                self._respond(400, {"error": "fields 'request_id' and 'decision' (approved|denied) are required"})
                return

            # Only "user" may approve/deny — no agent may decide for Leo
            if decided_by != "user":
                self._respond(403, {"error": "only 'user' (Leo) may approve or deny requests"})
                return

            # Expire check first
            _approval_expire_check()

            with APPROVAL_LOCK:
                req = APPROVAL_REQUESTS.get(request_id)
                if req is None:
                    self._respond(404, {"error": f"approval request not found: {request_id}"})
                    return
                if req["status"] != "pending":
                    self._respond(409, {
                        "error": f"request already {req['status']}",
                        "request_id": request_id,
                        "current_status": req["status"],
                    })
                    return
                now = datetime.now(timezone.utc)
                req["status"] = decision
                req["decided_at"] = now.isoformat()
                req["decided_by"] = decided_by
                req["comment"] = comment or None
                result_req = dict(req)

            # Notify agent via Bridge message
            agent_id = result_req["agent_id"]
            action = result_req["action"]
            desc = result_req["description"]
            status_text = "GENEHMIGT" if decision == "approved" else "ABGELEHNT"
            msg_content = (
                f"[APPROVAL {status_text}] {desc}\n"
                f"Aktion: {action}\n"
                f"Entscheidung: {decision}"
            )
            if comment:
                msg_content += f"\nKommentar: {comment}"
            append_message(
                "system", agent_id, msg_content,
                meta={"type": f"approval_{decision}", "request_id": request_id},
            )

            # WebSocket push: agent + UI see the decision
            ws_payload = {
                "request_id": request_id,
                "agent_id": agent_id,
                "decision": decision,
                "action": action,
                "comment": comment or None,
            }
            ws_broadcast("approval_decided", ws_payload)
            print(f"[approval] Decision: {request_id} → {decision} by {decided_by}")

            self._respond(200, {
                "ok": True,
                "request_id": request_id,
                "decision": decision,
            })
            return

        if _handle_approvals_post(self, path):
            return

        if _handle_teams_post(self, path):
            return

        if _handle_automation_post(self, path):
            return

        # POST /automations/{id}/run — manual trigger (test)
        _auto_run_match = re.match(r"^/automations/([^/]+)/run$", path)
        if _auto_run_match:
            auto_id = _auto_run_match.group(1)
            _handle_automation_run(self, auto_id)
            return

        # POST /automations/{id}/webhook — public local webhook trigger
        _auto_webhook_match = re.match(r"^/automations/([^/]+)/webhook$", path)
        if _auto_webhook_match:
            auto_id = _auto_webhook_match.group(1)
            _handle_automation_webhook(self, auto_id)
            return

        if _handle_execution_post(self, path):
            return

        if _handle_guardrails_post(self, path):
            return

        self._respond(404, {"error": "unknown path"})

    def do_PATCH(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"

        if BRIDGE_STRICT_AUTH and self._path_requires_auth_post(path):
            ok, _, _ = self._require_authenticated()
            if not ok:
                return

        # PATCH /skills/proposals/{id} — approve or reject a skill proposal (G5+M3)
        _proposal_match = re.match(r"^/skills/proposals/([^/]+)$", path)
        if _proposal_match:
            proposal_id = _proposal_match.group(1).strip()
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            action = str(data.get("action", "")).strip()
            reviewer = str(data.get("reviewer", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip()
            if action not in ("approve", "reject"):
                self._respond(400, {"error": "action must be 'approve' or 'reject'"})
                return
            # Only management can review — reject if no reviewer or non-management
            if not reviewer or not _is_management_agent(reviewer):
                self._respond(403, {"error": "only management agents can review proposals"})
                return
            with _PROPOSALS_LOCK:
                proposal = None
                for p in _SKILL_PROPOSALS:
                    if p.get("id") == proposal_id:
                        proposal = p
                        break
                if proposal is None:
                    self._respond(404, {"error": f"proposal '{proposal_id}' not found"})
                    return
                if proposal.get("status") != "pending":
                    self._respond(409, {"error": f"proposal already {proposal.get('status')}"})
                    return
                proposal["status"] = "approved" if action == "approve" else "rejected"
                proposal["reviewed_by"] = reviewer
                proposal["reviewed_at"] = utc_now_iso()
                _save_proposals()
            # On approve: deploy to shared_tools/
            if action == "approve":
                skill_name = proposal.get("skill_name", "")
                content = proposal.get("content", "")
                deploy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared_tools")
                os.makedirs(deploy_dir, exist_ok=True)
                deploy_path = os.path.join(deploy_dir, f"{skill_name}.md")
                try:
                    with open(deploy_path, "w", encoding="utf-8") as f:
                        f.write(content)
                except OSError as exc:
                    self._respond(500, {"error": f"deploy failed: {exc}"})
                    return
                # Notify proposing agent
                append_message("system", proposal.get("agent_id", ""),
                               f"[SKILL APPROVED] Dein Skill '{skill_name}' wurde von {reviewer} genehmigt und deployed nach shared_tools/.",
                               meta={"type": "skill_approved", "proposal_id": proposal_id})
            else:
                append_message("system", proposal.get("agent_id", ""),
                               f"[SKILL REJECTED] Dein Skill '{proposal.get('skill_name', '')}' wurde von {reviewer} abgelehnt.",
                               meta={"type": "skill_rejected", "proposal_id": proposal_id})
            self._respond(200, {"ok": True, "proposal": proposal})
            return

        if _handle_workflows_patch(self, path):
            return

        # PATCH /task/{id} — update task fields (title, priority, assigned_to, labels, team)
        _task_patch_match = re.match(r"^/task/([^/]+)$", path)
        if _task_patch_match:
            task_id = _task_patch_match.group(1)
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            requester = str(data.get("requester", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip() or "unknown"
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                # Permission: assigned_to OR created_by OR team-lead OR management (level <= 1)
                allowed = {task.get("assigned_to"), task.get("created_by")}
                if task.get("team") and TEAM_CONFIG:
                    for tm in TEAM_CONFIG.get("teams", []):
                        if tm.get("id") == task["team"]:
                            allowed.add(tm.get("lead"))
                            break
                # V4: Management-level agents (level 0-1) can update any task
                is_management = False
                if TEAM_CONFIG:
                    for ag in TEAM_CONFIG.get("agents", []):
                        if ag.get("id") == requester and ag.get("level", 99) <= 1:
                            is_management = True
                            break
                if requester not in allowed and requester != "unknown" and requester != "user" and not is_management:
                    self._respond(403, {"error": f"'{requester}' not allowed to update this task"})
                    return
                before_task_update = copy.deepcopy(task)
                changes: dict[str, Any] = {}
                # title (F-03: XSS protection via html.escape)
                if "title" in data:
                    new_title = html.escape(html.unescape(str(data["title"]).strip()))
                    if not new_title or len(new_title) > TASK_TITLE_MAX_LEN:
                        self._respond(400, {"error": f"title must be 1-{TASK_TITLE_MAX_LEN} chars"})
                        return
                    changes["title"] = {"old": task.get("title"), "new": new_title}
                    task["title"] = new_title
                # description (F-04: real top-level field)
                if "description" in data:
                    new_desc = html.escape(html.unescape(str(data["description"]).strip())) or None
                    changes["description"] = {"old": task.get("description"), "new": new_desc}
                    task["description"] = new_desc
                # priority
                if "priority" in data:
                    try:
                        new_prio = int(data["priority"])
                    except (ValueError, TypeError):
                        self._respond(400, {"error": "priority must be 1-3"})
                        return
                    if new_prio not in VALID_TASK_PRIORITIES:
                        self._respond(400, {"error": f"priority must be 1-3, got {new_prio}"})
                        return
                    changes["priority"] = {"old": task.get("priority"), "new": new_prio}
                    task["priority"] = new_prio
                # assigned_to (F-05: reassign resets claimed/acked → created)
                if "assigned_to" in data:
                    new_assigned = str(data["assigned_to"]).strip() or None
                    old_assigned = task.get("assigned_to")
                    changes["assigned_to"] = {"old": old_assigned, "new": new_assigned}
                    task["assigned_to"] = new_assigned
                    if new_assigned != old_assigned and task["state"] in ("claimed", "acked"):
                        old_state = task["state"]
                        task["state"] = "created"
                        changes["state"] = {"old": old_state, "new": "created"}
                        task["state_history"].append({
                            "state": "created",
                            "at": utc_now_iso(),
                            "by": requester,
                            "reason": f"reassigned from {old_assigned} to {new_assigned}",
                        })
                # labels
                if "labels" in data:
                    new_labels = data["labels"]
                    if not isinstance(new_labels, list):
                        self._respond(400, {"error": "labels must be a list"})
                        return
                    new_labels = [html.escape(html.unescape(str(l).strip()[:TASK_LABEL_MAX_LEN])) for l in new_labels[:TASK_LABEL_MAX_COUNT] if str(l).strip()]
                    changes["labels"] = {"old": task.get("labels", []), "new": new_labels}
                    task["labels"] = new_labels
                # team
                if "team" in data:
                    new_team = str(data["team"]).strip() or None
                    if new_team and TEAM_CONFIG:
                        valid_team_ids = {t.get("id") for t in TEAM_CONFIG.get("teams", [])}
                        if new_team not in valid_team_ids:
                            self._respond(400, {"error": f"unknown team '{new_team}', valid: {sorted(valid_team_ids)}"})
                            return
                    changes["team"] = {"old": task.get("team"), "new": new_team}
                    task["team"] = new_team
                # V4: blocker_reason — set or clear (empty string / null = clear)
                if "blocker_reason" in data:
                    raw_br = data["blocker_reason"]
                    new_br = str(raw_br).strip() if raw_br else None
                    new_br = new_br or None  # empty string → None
                    old_br = task.get("blocker_reason")
                    changes["blocker_reason"] = {"old": old_br, "new": new_br}
                    task["blocker_reason"] = new_br
                # Remove unchanged fields from changes dict
                changes = {k: v for k, v in changes.items() if v.get("old") != v.get("new")}
                if not changes:
                    self._respond(400, {"error": "no valid fields to update"})
                    return
                task["state_history"].append({
                    "state": "updated",
                    "at": utc_now_iso(),
                    "by": requester,
                    "changes": changes,
                })
                _persist_tasks()
                _append_task_transition_wal(task_id, "updated", requester, before_task_update, task, {"changes": list(changes.keys())})
            # Broadcast update
            ws_broadcast("task_updated", {"task_id": task_id, "changes": changes, "by": requester})
            # V4: Extra broadcast when blocker_reason changes (UI can react specifically)
            if "blocker_reason" in changes:
                ws_broadcast("task_blocker_changed", {
                    "task_id": task_id,
                    "blocker_reason": changes["blocker_reason"]["new"] if isinstance(changes["blocker_reason"], dict) else changes["blocker_reason"],
                    "by": requester,
                })
            # V4: Auto-ensure newly assigned agent is online
            response_data: dict[str, Any] = {"ok": True, "task_id": task_id, "changes": changes, "task": task}
            _new_assigned = changes["assigned_to"]["new"] if isinstance(changes.get("assigned_to"), dict) else changes.get("assigned_to")
            if _new_assigned:
                agent_status = _ensure_agent_online(_new_assigned, task_id=task_id, requester=requester)
                if not agent_status["online"]:
                    response_data["agent_status"] = agent_status
            self._respond(200, response_data)
            return

        # PATCH /agents/{id}/active — toggle agent active state (Susi: "Aktiv"/"Pausiert")
        _agent_active_match = re.match(r"^/agents/([^/]+)/active$", path)
        if _agent_active_match:
            agent_id = _agent_active_match.group(1)
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            if "active" not in data:
                self._respond(400, {"error": "missing 'active' field (true/false)"})
                return
            new_active = bool(data["active"])
            # Update team.json in-memory + persist
            if TEAM_CONFIG is None:
                self._respond(500, {"error": "team.json not loaded"})
                return
            agent_conf = None
            for a in TEAM_CONFIG.get("agents", []):
                if a.get("id") == agent_id:
                    agent_conf = a
                    break
            if agent_conf is None:
                self._respond(404, {"error": f"agent '{agent_id}' not in team.json"})
                return
            old_active = agent_conf.get("active", False)
            # Mutate + persist under lock (thread-safe)
            try:
                with TEAM_CONFIG_LOCK:
                    agent_conf["active"] = new_active
                    _atomic_write_team_json()
            except OSError as exc:
                agent_conf["active"] = old_active  # rollback
                self._respond(500, {"error": f"failed to persist team.json: {exc}"})
                return
            # Start/stop tmux session
            session_alive = False
            if new_active:
                # Start agent from team.json config (not agents.conf)
                try:
                    if not is_session_alive(agent_id):
                        home_dir = str(agent_conf.get("home_dir", "")).strip()
                        if home_dir and os.path.isdir(home_dir):
                            home_path = Path(home_dir)
                            if home_path.parent.name == ".agent_sessions" and home_path.name == agent_id:
                                project_path = str(home_path.parent.parent)
                            else:
                                project_path = home_dir
                            prompt = "Lies deine Dokumentation. Registriere dich via bridge_register."
                            prompt_file = str(agent_conf.get("prompt_file", "")).strip()
                            if prompt_file and os.path.exists(prompt_file):
                                try:
                                    prompt = Path(prompt_file).read_text(encoding="utf-8").strip() or prompt
                                except Exception:
                                    pass
                            engine = str(agent_conf.get("engine", "claude")).strip() or "claude"
                            toggle_config_dir = str(agent_conf.get("config_dir", "")).strip()
                            toggle_mcp_servers = str(agent_conf.get("mcp_servers", "")).strip()
                            toggle_model = str(agent_conf.get("model", "")).strip()
                            # Hardening (C4): Use description from team.json as role
                            toggle_role = str(agent_conf.get("description", agent_id)).strip() or agent_id
                            create_agent_session(
                                agent_id=agent_id, role=toggle_role,
                                project_path=project_path, team_members=[],
                                engine=engine, bridge_port=PORT, role_description=prompt,
                                config_dir=toggle_config_dir,
                                mcp_servers=toggle_mcp_servers,
                                model=toggle_model,
                                permissions=agent_conf.get("permissions"),
                                scope=agent_conf.get("scope"),
                                report_recipient=str(agent_conf.get("reports_to", "")).strip(),
                                initial_prompt=prompt,
                            )
                    session_alive = is_session_alive(agent_id)
                except Exception:
                    session_alive = False
            else:
                # Stop agent session
                try:
                    kill_agent_session(agent_id)
                except Exception:
                    pass
                _clear_agent_runtime_presence(agent_id)
                session_alive = False
            ws_broadcast("agent_active_changed", {
                "agent_id": agent_id, "active": new_active, "session_alive": session_alive,
            })
            self._respond(200, {
                "ok": True, "agent_id": agent_id,
                "active": new_active, "session_alive": session_alive,
            })
            return

        # PATCH /agents/{id}/mode — set agent mode (normal/auto/standby)
        _agent_mode_match = re.match(r"^/agents/([^/]+)/mode$", path)
        if _agent_mode_match:
            agent_id = _agent_mode_match.group(1)
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            new_mode = data.get("mode")
            valid_modes = ("normal", "auto", "standby")
            if new_mode not in valid_modes:
                self._respond(400, {"error": f"'mode' must be one of {valid_modes}"})
                return
            # Persist mode in agent state
            _save_agent_state(agent_id, {"mode": new_mode})
            # Build instruction text per mode
            mode_instructions = {
                "auto": "Arbeite autonom weiter. Finde selbst die naechste Aufgabe.",
                "normal": "Arbeite aktuelle Aufgabe ab, dann warte auf Input.",
                "standby": "Warte auf direkte Auftraege. Keine eigenstaendige Arbeit.",
            }
            instruction = mode_instructions[new_mode]
            # Notify agent via bridge message
            append_message(
                "system", agent_id,
                f"[MODE CHANGE] Dein Modus wurde auf '{new_mode}' geaendert. {instruction}",
                meta={"type": "mode_change", "mode": new_mode},
            )
            ws_broadcast("agent_mode_changed", {"agent_id": agent_id, "mode": new_mode})
            event_bus.emit_agent_mode_changed(agent_id, str(new_mode))
            self._respond(200, {"ok": True, "agent_id": agent_id, "mode": new_mode})
            return

        if _handle_automation_patch(self, path):
            return

        # PATCH /agents/{id} — update agent profile (Agent-Builder)
        _agent_profile_match = re.match(r"^/agents/([^/]+)$", path)
        if _agent_profile_match:
            agent_id = _agent_profile_match.group(1)
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            if TEAM_CONFIG is None:
                self._respond(500, {"error": "team.json not loaded"})
                return
            agents = TEAM_CONFIG.get("agents", [])
            agent_entry: dict[str, Any] | None = None
            for a in agents:
                if a.get("id") == agent_id:
                    agent_entry = a
                    break
            if agent_entry is None:
                self._respond(404, {"error": f"agent '{agent_id}' not found in team.json"})
                return

            # Collect validated changes
            changes: dict[str, Any] = {}
            _VALID_AUTONOMY = {"restricted", "normal", "full"}

            if "display_name" in data:
                val = str(data["display_name"]).strip()
                if len(val) > 50:
                    self._respond(400, {"error": "display_name max 50 chars"})
                    return
                changes["display_name"] = val

            if "name" in data:
                val = str(data["name"]).strip()
                if not val or len(val) > 50:
                    self._respond(400, {"error": "name must be 1-50 chars"})
                    return
                changes["name"] = val

            if "role" in data:
                changes["role"] = str(data["role"]).strip()[:200]

            if "description" in data:
                changes["description"] = str(data["description"]).strip()[:500]

            if "avatar_url" in data:
                val = str(data["avatar_url"]).strip()
                if val and len(val) > 300:
                    self._respond(400, {"error": "avatar_url max 300 chars"})
                    return
                changes["avatar_url"] = val

            if "skills" in data:
                sk = data["skills"]
                if not isinstance(sk, list):
                    self._respond(400, {"error": "skills must be a list"})
                    return
                if len(sk) > 20:
                    self._respond(400, {"error": "skills max 20 entries"})
                    return
                changes["skills"] = [str(s).strip()[:50] for s in sk]

            if "model_locked" in data:
                changes["model_locked"] = bool(data["model_locked"])

            if "engine" in data:
                val = str(data["engine"]).strip().lower()
                if val not in KNOWN_ENGINES:
                    self._respond(400, {"error": f"engine must be one of {sorted(KNOWN_ENGINES)}"})
                    return
                changes["engine"] = val

            if "model" in data:
                val = str(data["model"]).strip()
                if val and (len(val) > 50 or not re.match(r'^[a-z0-9._-]+$', val)):
                    self._respond(400, {"error": "model must be 1-50 chars, pattern [a-z0-9._-]"})
                    return
                # Enforce model_locked: non-management agents cannot change model
                if agent_entry.get("model_locked", False) and "model_locked" not in changes:
                    requesting_agent = str(self.headers.get("X-Bridge-Agent", "")).strip() or None
                    if requesting_agent and not _is_management_agent(requesting_agent):
                        self._respond(403, {"error": "model is locked — only management agents or user can change it"})
                        return
                target_engine = changes.get("engine", str(agent_entry.get("engine", "claude")).strip() or "claude")
                resolved_model = _resolve_engine_model_choice(str(target_engine), val)
                if val and resolved_model is None:
                    self._respond(400, {"error": f"model '{val}' is not valid for engine '{target_engine}'"})
                    return
                changes["model"] = resolved_model or ""

            if "permissions" in data:
                perm = data["permissions"]
                if not isinstance(perm, dict):
                    self._respond(400, {"error": "permissions must be an object"})
                    return
                merged = dict(agent_entry.get("permissions", {}))
                if "approval_required" in perm:
                    merged["approval_required"] = bool(perm["approval_required"])
                if "autonomy_level" in perm:
                    al = str(perm["autonomy_level"]).strip()
                    if al not in _VALID_AUTONOMY:
                        self._respond(400, {"error": f"autonomy_level must be one of {sorted(_VALID_AUTONOMY)}"})
                        return
                    merged["autonomy_level"] = al
                if "bypass_permissions" in perm:
                    merged["bypass_permissions"] = bool(perm["bypass_permissions"])
                changes["permissions"] = merged

            if not changes:
                self._respond(400, {"error": "no valid fields to update"})
                return

            # Apply under lock + persist
            snapshot = {k: agent_entry.get(k) for k in changes}
            with TEAM_CONFIG_LOCK:
                try:
                    for k, v in changes.items():
                        agent_entry[k] = v
                    _atomic_write_team_json()
                except OSError as exc:
                    for k, v in snapshot.items():
                        if v is None:
                            agent_entry.pop(k, None)
                        else:
                            agent_entry[k] = v
                    self._respond(500, {"error": f"failed to persist: {exc}"})
                    return

            if any(k in changes for k in ("engine", "model")):
                try:
                    _sync_agent_persistent_cli_config(agent_id, agent_entry)
                except (OSError, ValueError) as exc:
                    with TEAM_CONFIG_LOCK:
                        try:
                            for k, v in snapshot.items():
                                if v is None:
                                    agent_entry.pop(k, None)
                                else:
                                    agent_entry[k] = v
                            _atomic_write_team_json()
                        except OSError as rollback_exc:
                            self._respond(500, {"error": f"persistent CLI sync failed: {exc}; rollback failed: {rollback_exc}"})
                            return
                    self._respond(500, {"error": f"persistent CLI sync failed: {exc}"})
                    return

            ws_broadcast("agent_updated", {"agent_id": agent_id, "changes": changes})
            print(f"[agent-builder] PATCH /agents/{agent_id}: {list(changes.keys())}")
            # Team-Change-Event: notify affected agents
            change_keys = list(changes.keys())
            if any(k in change_keys for k in ("role", "team", "reports_to", "level")):
                _notify_team_change("role_changed", f"{agent_id}: {', '.join(change_keys)}", affected_agents=[agent_id])
            if "skills" in change_keys:
                _notify_team_change("skills_changed", f"{agent_id}: skills updated", affected_agents=[agent_id])
            self._respond(200, {"ok": True, "agent_id": agent_id, "changes": changes, "agent": {k: agent_entry.get(k) for k in ("id", "name", "display_name", "role", "description", "avatar_url", "skills", "permissions", "level", "reports_to", "active", "engine", "model", "model_locked")}})
            return

        # PATCH /agents/{id}/parent — move agent in hierarchy (Drag & Drop)
        _agent_parent_match = re.match(r"^/agents/([^/]+)/parent$", path)
        if _agent_parent_match:
            agent_id = _agent_parent_match.group(1)
            data = self._parse_json_body()
            if data is None:
                self._respond(400, {"error": "invalid json body"})
                return
            new_parent = str(data.get("new_parent", "")).strip()
            if not new_parent:
                self._respond(400, {"error": "missing 'new_parent' field"})
                return
            requester = str(data.get("requester", "")).strip() or str(self.headers.get("X-Bridge-Agent", "")).strip() or "user"

            if TEAM_CONFIG is None:
                self._respond(500, {"error": "team.json not loaded"})
                return

            agents = TEAM_CONFIG.get("agents", [])
            agent_map: dict[str, dict[str, Any]] = {a["id"]: a for a in agents}

            # 1. Agent exists?
            if agent_id not in agent_map:
                self._respond(404, {"error": f"agent '{agent_id}' not found"})
                return

            # 2. new_parent exists? ("user" is valid root)
            if new_parent != "user" and new_parent not in agent_map:
                self._respond(400, {"error": f"parent '{new_parent}' not found"})
                return

            # 3. No self-assignment
            if new_parent == agent_id:
                self._respond(400, {"error": "agent cannot be its own parent"})
                return

            # 4. Permission: only Level 1 + user can change hierarchy
            if requester != "user":
                req_agent = agent_map.get(requester)
                if not req_agent or req_agent.get("level", 99) > 1:
                    self._respond(403, {"error": f"'{requester}' not authorized to change hierarchy (Level 1 or user required)"})
                    return

            # 5. Circular reference check: new_parent must NOT be a descendant of agent_id
            def _get_descendants(aid: str) -> set[str]:
                desc: set[str] = set()
                queue = [a["id"] for a in agents if a.get("reports_to") == aid]
                while queue:
                    child = queue.pop(0)
                    if child in desc:
                        continue
                    desc.add(child)
                    queue.extend(a["id"] for a in agents if a.get("reports_to") == child)
                return desc

            if new_parent != "user" and new_parent in _get_descendants(agent_id):
                self._respond(400, {"error": f"circular reference: '{new_parent}' is a descendant of '{agent_id}'"})
                return

            # 6. Calculate new level
            if new_parent == "user":
                new_level = 1
            else:
                new_level = agent_map[new_parent].get("level", 1) + 1

            # 7. Update under lock + persist
            old_parent = agent_map[agent_id].get("reports_to", "")
            old_level = agent_map[agent_id].get("level", 99)
            with TEAM_CONFIG_LOCK:
                # Snapshot inside lock to avoid TOCTOU on levels
                level_snapshot: dict[str, int] = {a["id"]: a.get("level", 99) for a in agents}
                try:
                    agent_map[agent_id]["reports_to"] = new_parent
                    agent_map[agent_id]["level"] = new_level
                    # Recursively update children's levels
                    def _update_children_levels(parent_id: str, parent_level: int) -> None:
                        for a in agents:
                            if a.get("reports_to") == parent_id:
                                a["level"] = parent_level + 1
                                _update_children_levels(a["id"], parent_level + 1)
                    _update_children_levels(agent_id, new_level)
                    _atomic_write_team_json()
                except OSError as exc:
                    # Rollback inside lock — no other thread sees inconsistent state
                    agent_map[agent_id]["reports_to"] = old_parent
                    for a in agents:
                        a["level"] = level_snapshot.get(a["id"], a.get("level", 99))
                    self._respond(500, {"error": f"failed to persist: {exc}"})
                    return

            # 8. Routes: bridge_watcher.py auto-reloads when team.json changes on disk

            # 9. Broadcast
            agent_name = agent_map[agent_id].get("name", agent_id)
            ws_broadcast("hierarchy_changed", {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "old_parent": old_parent,
                "new_parent": new_parent,
                "new_level": new_level,
                "changed_by": requester,
            })

            # 10. Audit log
            print(f"[hierarchy] MOVE: {agent_name} ({agent_id}) → reports_to={new_parent} (level {old_level}→{new_level}) by {requester}")

            self._respond(200, {
                "ok": True,
                "agent_id": agent_id,
                "old_parent": old_parent,
                "new_parent": new_parent,
                "new_level": new_level,
            })
            return

        self._respond(404, {"error": "unknown path"})

    def do_PUT(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"

        if _handle_workflows_put(self, path):
            return

        if _handle_guardrails_put(self, path):
            return

        if _handle_board_put(self, path):
            return

        if _handle_subscriptions_put(self, path):
            return

        if _handle_agents_put(self, path):
            return

        if _handle_teams_put(self, path):
            return

        if _handle_automation_put(self, path):
            return

        self._respond(404, {"error": "unknown path"})

    def do_DELETE(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"

        if BRIDGE_STRICT_AUTH and self._path_requires_auth_post(path):
            ok, _, _ = self._require_authenticated()
            if not ok:
                return

        # ===== GIT LOCK DELETE ENDPOINT (RB2) =====
        # Identity binding: X-Bridge-Agent must match body agent_id (anti-spoofing)
        if _handle_git_lock_delete(self, path):
            return

        if _handle_guardrails_delete(self, path):
            return

        # ===== CREDENTIAL DELETE ENDPOINT (E1) =====
        if _handle_credentials_delete(self, path):
            return

        if _handle_shared_tools_delete(self, path):
            return

        if _handle_workflows_delete(self, path):
            return

        if _handle_event_subscriptions_delete(self, path):
            return

        if _handle_board_delete(self, path):
            return

        if _handle_subscriptions_delete(self, path):
            return

        if _handle_whiteboard_delete(self, path):
            return

        if _handle_teams_delete(self, path):
            return

        # ===== V5: DELETE /task/{id} — soft-delete task =====
        _task_delete_match = re.match(r"^/task/([^/]+)$", path)
        if _task_delete_match:
            task_id = _task_delete_match.group(1)
            # Parse optional JSON body for requester
            requester = "unknown"
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                    requester = str(body.get("requester", "")).strip() or requester
            except Exception:
                pass
            if requester == "unknown":
                requester = str(self.headers.get("X-Bridge-Agent", "")).strip() or "unknown"
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if not task:
                    self._respond(404, {"error": f"task '{task_id}' not found"})
                    return
                if task.get("state") == "deleted":
                    self._respond(400, {"error": f"task '{task_id}' already deleted"})
                    return
                # Permission: same as PATCH — assigned_to, created_by, management (level 0-1)
                allowed = {task.get("assigned_to"), task.get("created_by")}
                if task.get("team") and TEAM_CONFIG:
                    for tm in TEAM_CONFIG.get("teams", []):
                        if tm.get("id") == task["team"]:
                            allowed.add(tm.get("lead"))
                            break
                is_management = False
                if TEAM_CONFIG:
                    for ag in TEAM_CONFIG.get("agents", []):
                        if ag.get("id") == requester and ag.get("level", 99) <= 1:
                            is_management = True
                            break
                if requester not in allowed and requester != "unknown" and requester != "user" and not is_management:
                    self._respond(403, {"error": f"'{requester}' not allowed to delete this task"})
                    return
                before_task_delete = copy.deepcopy(task)
                old_state = task["state"]
                task["state"] = "deleted"
                task["deleted_at"] = utc_now_iso()
                task["deleted_by"] = requester
                task["state_history"].append({
                    "state": "deleted",
                    "at": utc_now_iso(),
                    "by": requester,
                    "previous_state": old_state,
                })
                _persist_tasks()
                _append_task_transition_wal(task_id, "deleted", requester, before_task_delete, task, {"previous_state": old_state})
            ws_broadcast("task_deleted", {"task_id": task_id, "by": requester})
            _log_task_event(task_id, "deleted", requester, {"previous_state": old_state})
            self._respond(200, {"ok": True, "task_id": task_id, "state": "deleted"})
            return

        if _handle_automation_delete(self, path):
            return

        self._respond(404, {"error": "unknown path"})

def main() -> None:
    run_server_main()


# --- Initialize extracted websocket module with shared state & callbacks ---
_init_websocket_server(
    bridge_user_token_getter=lambda: BRIDGE_USER_TOKEN,
    ui_session_token_getter=lambda: _UI_SESSION_TOKEN,
    strict_auth_getter=lambda: BRIDGE_STRICT_AUTH,
    agent_state_lock=AGENT_STATE_LOCK,
    session_tokens=SESSION_TOKENS,
    grace_tokens=GRACE_TOKENS,
    append_message_fn=lambda *args, **kwargs: append_message(*args, **kwargs),
    is_federation_target_fn=_is_federation_target,
    federation_send_outbound_fn=_federation_send_outbound,
    update_agent_status_fn=update_agent_status,
    agent_busy=AGENT_BUSY,
    agent_last_seen=AGENT_LAST_SEEN,
    cond=COND,
    messages=MESSAGES,
    runtime_snapshot_fn=runtime_snapshot,
    get_team_members_fn=get_team_members,
    ws_host_getter=lambda: WS_HOST,
    ws_port_getter=lambda: WS_PORT,
    allowed_origins_getter=lambda: ALLOWED_ORIGINS,
)

# --- Initialize extracted message module with shared state & callbacks ---
_init_messages(
    messages=MESSAGES,
    cursors=CURSORS,
    lock=LOCK,
    cond=COND,
    log_file=LOG_FILE,
    ws_broadcast_message_fn=ws_broadcast_message,
    resolve_agent_alias_fn=resolve_agent_alias,
    push_non_mcp_fn=_push_non_mcp_notification,
    maybe_team_lead_fn=maybe_team_lead_intervene,
    is_management_agent_fn=_is_management_agent,
    get_team_members_fn=get_team_members,
    utc_now_iso_fn=utc_now_iso,
)

_init_federation(
    append_message_fn=lambda *args, **kwargs: append_message(*args, **kwargs),
    emit_message_received_fn=lambda *args, **kwargs: event_bus.emit_message_received(*args, **kwargs),
)

_init_server_utils(
    max_wait_seconds=MAX_WAIT_SECONDS,
    max_limit=MAX_LIMIT,
)

_init_server_runtime_meta(
    runtime_getter=lambda: RUNTIME,
    runtime_lock=RUNTIME_LOCK,
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    detect_available_engines_fn=lambda: _detect_available_engines(),
    known_engines_getter=lambda: KNOWN_ENGINES,
    team_lead_id_getter=lambda: TEAM_LEAD_ID,
)

_init_server_agent_state(
    agent_state_dir=AGENT_STATE_DIR,
    utc_now_iso_fn=utc_now_iso,
    team_config_getter=lambda: TEAM_CONFIG,
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    agent_state_lock=AGENT_STATE_LOCK,
    resolve_agent_cli_layout_fn=resolve_agent_cli_layout,
    agent_state_write_lock=_AGENT_STATE_WRITE_LOCK,
)

_init_server_agent_files(
    instruction_file_by_engine=INSTRUCTION_FILE_BY_ENGINE,
    ensure_parent_dir_fn=ensure_parent_dir,
)

_init_server_context_restore(
    get_agent_home_dir_fn=_get_agent_home_dir,
    normalize_cli_identity_path_fn=_normalize_cli_identity_path,
    get_runtime_config_dir_fn=_get_runtime_config_dir,
    first_existing_path_fn=first_existing_path,
    context_bridge_candidates_fn=context_bridge_candidates,
    soul_candidates_fn=soul_candidates,
    instruction_candidates_fn=instruction_candidates,
    detect_instruction_filename_fn=detect_instruction_filename,
    find_agent_memory_path_fn=find_agent_memory_path,
    find_memory_backup_path_fn=find_memory_backup_path,
    load_standing_approvals_fn=_load_standing_approvals,
    is_management_agent_fn=_is_management_agent,
    agent_is_live_fn=_agent_is_live,
    team_config_getter=lambda: TEAM_CONFIG,
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    tasks_getter=lambda: TASKS,
    messages_getter=lambda: MESSAGES,
    system_status_getter=lambda: _SYSTEM_STATUS,
    agent_state_lock=AGENT_STATE_LOCK,
    task_lock=TASK_LOCK,
    message_lock=LOCK,
    agent_nonces=AGENT_NONCES,
    agent_last_context_restore=AGENT_LAST_CONTEXT_RESTORE,
    context_restore_cooldown=CONTEXT_RESTORE_COOLDOWN,
)

_init_server_request_auth(
    bridge_user_token_getter=lambda: BRIDGE_USER_TOKEN,
    ui_session_token_getter=lambda: _UI_SESSION_TOKEN,
    platform_operator_agents_getter=lambda: PLATFORM_OPERATOR_AGENTS,
    agent_state_lock=AGENT_STATE_LOCK,
    session_tokens=SESSION_TOKENS,
    grace_tokens=GRACE_TOKENS,
    auth_tier2_get_paths=AUTH_TIER2_GET_PATHS,
    auth_tier2_get_patterns=AUTH_TIER2_GET_PATTERNS,
    auth_tier2_post_paths=AUTH_TIER2_POST_PATHS,
    auth_tier3_post_paths=AUTH_TIER3_POST_PATHS,
    auth_tier3_patterns=AUTH_TIER3_PATTERNS,
    auth_tier2_patterns=AUTH_TIER2_PATTERNS,
)

_init_server_http_io(
    allowed_origins=ALLOWED_ORIGINS,
    rate_limit_exempt=RATE_LIMIT_EXEMPT,
    rate_limits=RATE_LIMITS,
    rate_limiter=RATE_LIMITER,
    ws_port=WS_PORT,
)

_init_server_frontend_serve(
    frontend_dir=FRONTEND_DIR,
    ui_session_token_getter=lambda: _UI_SESSION_TOKEN,
    is_within_directory=is_within_directory,
)

_init_server_message_audience(
    team_config_getter=lambda: TEAM_CONFIG,
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    agent_state_lock=AGENT_STATE_LOCK,
    agent_is_live_fn=_agent_is_live,
    get_team_members_fn=get_team_members,
    is_management_agent_fn=_is_management_agent,
)

_init_agents(
    registered_agents=REGISTERED_AGENTS,
    agent_last_seen=AGENT_LAST_SEEN,
    agent_busy=AGENT_BUSY,
    session_tokens=SESSION_TOKENS,
    agent_tokens=AGENT_TOKENS,
    agent_state_lock=AGENT_STATE_LOCK,
    tasks=TASKS,
    task_lock=TASK_LOCK,
    team_config=TEAM_CONFIG,
    team_config_lock=TEAM_CONFIG_LOCK,
    team_config_getter_fn=lambda: TEAM_CONFIG,
    frontend_dir=FRONTEND_DIR,
    runtime=RUNTIME,
    runtime_lock=RUNTIME_LOCK,
    ws_broadcast_fn=ws_broadcast,
    notify_teamlead_crashed_fn=_notify_teamlead_agent_crashed,
    tmux_session_for_fn=_tmux_session_for,
    tmux_session_name_exists_fn=_tmux_session_name_exists,
    runtime_layout_from_state_fn=_runtime_layout_from_state,
    get_agent_home_dir_fn=_get_agent_home_dir,
    check_agent_memory_health_fn=_check_agent_memory_health,
    append_message_fn=append_message,
    atomic_write_team_json_fn=_atomic_write_team_json,
    setup_cli_binaries=_SETUP_CLI_BINARIES,
    materialize_agent_setup_home_fn=_materialize_agent_setup_home,
    sync_agent_persistent_cli_config_fn=_sync_agent_persistent_cli_config,
    root_dir=ROOT_DIR,
    bridge_port=PORT,
    create_agent_session_fn=create_agent_session,
    kill_agent_session_fn=kill_agent_session,
    is_session_alive_fn=is_session_alive,
)

_init_runtime(
    runtime=RUNTIME,
    runtime_lock=RUNTIME_LOCK,
    team_lead_state=TEAM_LEAD_STATE,
    team_lead_lock=TEAM_LEAD_LOCK,
    registered_agents=REGISTERED_AGENTS,
    agent_state_lock=AGENT_STATE_LOCK,
    agent_last_seen=AGENT_LAST_SEEN,
    agent_busy=AGENT_BUSY,
    agent_activities=AGENT_ACTIVITIES,
    runtime_team_path_fn=lambda: RUNTIME_TEAM_PATH,
    team_lead_id=TEAM_LEAD_ID,
    known_engines=KNOWN_ENGINES,
    root_dir=ROOT_DIR,
    ws_broadcast_fn=ws_broadcast,
    tmux_session_for_fn=_tmux_session_for,
    agent_log_path_fn=agent_log_path,
    parse_scope_tokens_fn=_parse_scope_tokens,
    parse_non_negative_int_fn=parse_non_negative_int,
    parse_bool_fn=parse_bool,
    derive_routes_fn=derive_routes,
)

_init_tasks(
    tasks=TASKS,
    task_lock=TASK_LOCK,
    whiteboard=WHITEBOARD,
    whiteboard_lock=WHITEBOARD_LOCK,
    base_dir=BASE_DIR,
    agent_log_dir=AGENT_LOG_DIR,
    task_default_ack_deadline=TASK_DEFAULT_ACK_DEADLINE,
    ws_broadcast_fn=ws_broadcast,
    whiteboard_post_fn=_whiteboard_post,
    refresh_scope_locks_for_task_fn=_refresh_scope_locks_for_task,
    unlock_scope_paths_fn=_unlock_scope_paths,
    log_whiteboard_event_fn=_log_whiteboard_event,
    persist_whiteboard_fn=_persist_whiteboard,
)

_init_scope_locks(
    scope_locks=SCOPE_LOCKS,
    scope_lock_lock=SCOPE_LOCK_LOCK,
    team_config=TEAM_CONFIG,
    team_config_lock=TEAM_CONFIG_LOCK,
    root_dir=ROOT_DIR,
    base_dir=BASE_DIR,
    agent_log_dir=AGENT_LOG_DIR,
)

_init_whiteboard(
    whiteboard=WHITEBOARD,
    whiteboard_lock=WHITEBOARD_LOCK,
    team_config=TEAM_CONFIG,
    base_dir=BASE_DIR,
    agent_log_dir=AGENT_LOG_DIR,
    whiteboard_valid_types=WHITEBOARD_VALID_TYPES,
    ws_broadcast_fn=ws_broadcast,
)

_init_approvals(
    base_dir=BASE_DIR,
    messages_dir=MESSAGES_DIR,
    agent_log_dir=AGENT_LOG_DIR,
    append_message_fn=append_message,
    ws_broadcast_fn=ws_broadcast,
    is_management_agent_fn=_is_management_agent,
    sa_create_allowed_getter=lambda: set(_RBAC_SA_CREATE_ALLOWED),
)

_init_skills(
    team_config_getter=lambda: TEAM_CONFIG,
    team_config_lock=TEAM_CONFIG_LOCK,
    atomic_write_team_json_fn=_atomic_write_team_json,
    ws_broadcast_fn=ws_broadcast,
    deploy_agent_skills_fn=_deploy_agent_skills,
)

_init_health(
    registered_agents=REGISTERED_AGENTS,
    agent_state_lock=AGENT_STATE_LOCK,
    ws_clients=WS_CLIENTS,
    messages=MESSAGES,
    get_agent_home_dir_fn=_get_agent_home_dir,
    get_runtime_config_dir_fn=_get_runtime_config_dir,
    get_start_ts_fn=lambda: START_TS,
    get_port_fn=lambda: PORT,
    get_ws_port_fn=lambda: WS_PORT,
    get_pid_dir_fn=lambda: PID_DIR,
    get_log_file_fn=lambda: LOG_FILE,
    check_tmux_session_fn=_check_tmux_session,
    resolve_forwarder_session_name_fn=_resolve_forwarder_session_name,
    tmux_session_name_exists_fn=_tmux_session_name_exists,
    get_agent_context_pct_fn=_get_agent_context_pct,
    read_pid_file_fn=_read_pid_file,
    pid_alive_fn=_pid_alive,
    pgrep_fn=_pgrep,
    federation_runtime_health_fn=_federation_runtime_health,
)

_init_guardrails_routes(
    is_management_agent_fn=_is_management_agent,
)

_init_shared_tools_routes(
    is_management_agent_fn=_is_management_agent,
    platform_operators_getter=lambda: _RBAC_PLATFORM_OPERATORS,
)

_init_chat_files(
    chat_uploads_dir_getter=lambda: CHAT_UPLOADS_DIR,
    is_within_directory_fn=is_within_directory,
)

_init_meta_routes(
    engine_model_registry_fn=_engine_model_registry,
    get_cli_setup_state_cached_fn=_get_cli_setup_state_cached,
)

_init_teamlead_scope_routes(
    runtime_lock=RUNTIME_LOCK,
    runtime_state_getter=lambda: RUNTIME,
    projects_base_dir_getter=lambda: PROJECTS_BASE_DIR,
    validate_project_path_fn=validate_project_path,
    resolve_team_lead_scope_file_fn=resolve_team_lead_scope_file,
    ensure_parent_dir_fn=ensure_parent_dir,
)

_init_logs_routes(
    parse_non_negative_int_fn=parse_non_negative_int,
    tail_log_fn=tail_log,
)

_init_subscriptions_routes(
    team_config=TEAM_CONFIG,
    team_config_lock=TEAM_CONFIG_LOCK,
    build_subscription_response_item_fn=_build_subscription_response_item,
    infer_subscription_provider_fn=_infer_subscription_provider,
    atomic_write_team_json_fn=_atomic_write_team_json,
)

_init_event_subscriptions_routes(
    list_subscriptions_fn=event_bus.list_subscriptions,
    subscribe_fn=event_bus.subscribe,
    unsubscribe_fn=event_bus.unsubscribe,
)

_init_mcp_catalog_routes(
    runtime_mcp_registry_fn=mcp_catalog.runtime_mcp_registry,
    industry_templates_path=os.path.join(ROOT_DIR, "config", "industry_templates.json"),
    register_runtime_server_fn=mcp_catalog.register_runtime_server,
    rbac_platform_operators_getter=lambda: set(_RBAC_PLATFORM_OPERATORS),
    ws_broadcast_fn=ws_broadcast,
)

_init_board_routes(
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    agent_activities_getter=lambda: AGENT_ACTIVITIES,
    current_runtime_overlay_fn=lambda: _current_runtime_overlay(),
    runtime_overlay_board_projects_response_fn=lambda overlay: _runtime_overlay_board_projects_response(overlay),
)

_init_automation_routes(
    get_all_automations_fn=lambda: __import__("automation_engine").get_all_automations(),
    get_automation_fn=lambda auto_id: __import__("automation_engine").get_automation(auto_id),
    get_execution_history_fn=lambda auto_id, limit: __import__("automation_engine").get_execution_history(auto_id, limit),
    get_execution_by_id_fn=lambda exec_id: __import__("automation_engine").get_execution_by_id(exec_id),
    add_automation_fn=lambda data: __import__("automation_engine").add_automation(data),
    update_automation_fn=lambda auto_id, data: __import__("automation_engine").update_automation(auto_id, data),
    delete_automation_fn=lambda auto_id: __import__("automation_engine").delete_automation(auto_id),
    set_automation_active_fn=lambda auto_id, active: __import__("automation_engine").set_automation_active(auto_id, active),
    set_automation_pause_fn=lambda auto_id, paused_until: __import__("automation_engine").set_automation_pause(auto_id, paused_until),
    check_hierarchy_permission_fn=_check_hierarchy_permission,
    ws_broadcast_fn=ws_broadcast,
    get_scheduler_fn=lambda: __import__("automation_engine").get_scheduler(),
    dispatch_webhook_fn=lambda auto_id, payload: __import__("automation_engine").dispatch_webhook(auto_id, payload),
)

_init_teams_routes(
    team_config_getter=lambda: TEAM_CONFIG,
    team_config_snapshot_fn=_team_config_snapshot,
    current_runtime_overlay_fn=lambda: _current_runtime_overlay(),
    runtime_overlay_orgchart_response_fn=lambda overlay: _runtime_overlay_orgchart_response(overlay),
    runtime_overlay_team_projects_response_fn=lambda overlay: _runtime_overlay_team_projects_response(overlay),
    runtime_overlay_teams_response_fn=lambda overlay: _runtime_overlay_teams_response(overlay),
    runtime_overlay_team_detail_fn=lambda overlay, team_id: _runtime_overlay_team_detail(overlay, team_id),
    runtime_overlay_team_context_fn=lambda overlay, agent_id: _runtime_overlay_team_context(overlay, agent_id),
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    agent_activities_getter=lambda: AGENT_ACTIVITIES,
    agent_connection_status_fn=agent_connection_status,
    team_config_lock=TEAM_CONFIG_LOCK,
    atomic_write_team_json_fn=lambda: _atomic_write_team_json(),
    utc_now_iso_fn=utc_now_iso,
    ws_broadcast_fn=ws_broadcast,
    notify_team_change_fn=_notify_team_change,
    hot_reload_team_config_fn=_hot_reload_team_config,
)

_init_execution_routes(
    is_management_agent_fn=_is_management_agent,
)

_init_git_lock_routes(
    git_locks_file=_GIT_LOCKS_FILE,
    acquire_lock_fn=_gc_acquire_lock,
    release_lock_fn=_gc_release_lock,
    load_locks_fn=_gc_load_locks,
    save_locks_fn=_gc_save_locks,
    is_management_agent_fn=_is_management_agent,
)

_init_workflows(
    get_port_fn=lambda: PORT,
    get_bridge_user_token_fn=lambda: BRIDGE_USER_TOKEN,
    get_auth_tier2_post_paths_fn=lambda: AUTH_TIER2_POST_PATHS,
    get_auth_tier3_post_paths_fn=lambda: AUTH_TIER3_POST_PATHS,
    get_auth_tier3_patterns_fn=lambda: AUTH_TIER3_PATTERNS,
    utc_now_iso_fn=utc_now_iso,
)

_init_projects(
    root_dir_fn=lambda: ROOT_DIR,
    projects_base_dir_fn=lambda: PROJECTS_BASE_DIR,
    normalize_path_fn=normalize_path,
    parse_bool_fn=parse_bool,
    is_within_directory_fn=is_within_directory,
    validate_project_path_fn=validate_project_path,
)

_init_memory(
    ensure_parent_dir_fn=ensure_parent_dir,
    normalize_path_fn=normalize_path,
    root_dir_fn=lambda: ROOT_DIR,
)

_init_metrics_routes(
    get_token_metrics_fn=token_tracker.get_token_metrics,
    get_cost_summary_fn=token_tracker.get_cost_summary,
    model_prices_fn=lambda: token_tracker.MODEL_PRICES,
    log_usage_fn=token_tracker.log_usage,
)

_init_onboarding_routes(
    strict_auth_getter=lambda: BRIDGE_STRICT_AUTH,
    ensure_buddy_frontdoor_fn=_ensure_buddy_frontdoor,
    get_buddy_frontdoor_status_fn=_get_buddy_frontdoor_status,
)

_init_system_status_routes(
    restart_state_getter=lambda: RESTART_STATE,
    restart_lock=RESTART_LOCK,
    graceful_shutdown_getter=lambda: _GRACEFUL_SHUTDOWN,
    graceful_shutdown_lock=_GRACEFUL_SHUTDOWN_LOCK,
    system_status_getter=lambda: _SYSTEM_STATUS,
    start_ts_getter=lambda: START_TS,
    team_config_getter=lambda: TEAM_CONFIG,
    registered_agents_getter=lambda: REGISTERED_AGENTS,
    agent_is_live_fn=lambda agent_id: _agent_is_live(agent_id, stale_seconds=120.0),
    root_dir_fn=lambda: ROOT_DIR,
    active_agent_ids_getter=lambda: _get_active_agent_ids(),
)

_init_server_bootstrap(
    http_request_queue_size_getter=lambda: HTTP_REQUEST_QUEUE_SIZE,
    http_server_instance_getter=lambda: _HTTP_SERVER_INSTANCE,
)

_init_server_startup(
    registered_agents=REGISTERED_AGENTS,
    agent_busy=AGENT_BUSY,
    agent_activities=AGENT_ACTIVITIES,
    agent_state_lock=AGENT_STATE_LOCK,
    tasks=TASKS,
    task_lock=TASK_LOCK,
    port_getter=lambda: PORT,
    agent_is_live_fn=_agent_is_live,
    auto_gen_watcher_fn=_auto_gen_watcher,
    agent_health_checker_fn=_agent_health_checker,
    health_monitor_loop_fn=_health_monitor_loop,
    cli_output_monitor_loop_fn=_cli_output_monitor_loop,
    rate_limit_resume_loop_fn=_rate_limit_resume_loop,
    v3_cleanup_loop_fn=_v3_cleanup_loop,
    task_timeout_loop_fn=_task_timeout_loop,
    heartbeat_prompt_loop_fn=_heartbeat_prompt_loop,
    codex_hook_loop_fn=_codex_hook_loop,
    distillation_daemon_loop_fn=_distillation_daemon_loop,
    idle_agent_task_pusher_fn=_idle_agent_task_pusher,
    idle_watchdog_auto_assign_fn=_idle_watchdog_auto_assign,
    buddy_knowledge_loop_fn=_buddy_knowledge_loop,
    run_websocket_server_fn=run_websocket_server,
    restart_wake_enabled_fn=_restart_wake_enabled,
    start_restart_wake_thread_fn=_start_restart_wake_thread,
    start_supervisor_daemon_fn=_start_supervisor_daemon,
)

_init_server_main(
    build_session_name_map_fn=_build_session_name_map,
    load_history_fn=load_history,
    load_tasks_from_disk_fn=_load_tasks_from_disk,
    load_escalation_state_from_disk_fn=_load_escalation_state_from_disk,
    load_scope_locks_from_disk_fn=_load_scope_locks_from_disk,
    load_whiteboard_from_disk_fn=_load_whiteboard_from_disk,
    event_bus_load_subscriptions_fn=event_bus.load_subscriptions,
    event_bus_load_n8n_webhooks_fn=event_bus.load_n8n_webhooks,
    load_workflow_registry_fn=_load_workflow_registry,
    restore_workflow_tools_from_registry_fn=_restore_workflow_tools_from_registry,
    tool_store_scan_fn=lambda: tool_store.scan_tools(force=True),
    init_federation_runtime_fn=_init_federation_runtime,
    start_background_services_fn=start_background_services,
    http_host_getter=lambda: HTTP_HOST,
    port_getter=lambda: PORT,
    strict_auth_getter=lambda: BRIDGE_STRICT_AUTH,
    token_config_file_getter=lambda: _TOKEN_CONFIG_FILE,
    http_request_queue_size_getter=lambda: HTTP_REQUEST_QUEUE_SIZE,
    ui_session_token_getter=lambda: _UI_SESSION_TOKEN,
    log_file_getter=lambda: LOG_FILE,
    messages_getter=lambda: MESSAGES,
    http_server_class_getter=lambda: BridgeThreadingHTTPServer,
    bridge_handler_getter=lambda: BridgeHandler,
    create_http_server_with_retry_fn=_create_http_server_with_retry,
    http_server_instance_setter=lambda instance: globals().__setitem__("_HTTP_SERVER_INSTANCE", instance),
    server_signal_handler_fn=_server_signal_handler,
    stop_federation_runtime_fn=_stop_federation_runtime,
)

if __name__ == "__main__":
    main()
