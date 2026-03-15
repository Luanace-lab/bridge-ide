from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bridge_watcher as watcher  # noqa: E402
import server as srv  # noqa: E402


class TestWatcherPidContract(unittest.TestCase):
    def test_watcher_pid_file_uses_backend_pid_dir(self) -> None:
        expected = os.path.join(BACKEND_DIR, "pids", "watcher.pid")
        self.assertEqual(watcher.PID_FILE, expected)

    def test_server_supervisor_uses_same_watcher_pid_file(self) -> None:
        self.assertEqual(srv._PROCESS_SUPERVISOR_STATE["watcher"]["pid_file"], watcher.PID_FILE)


class TestWrapperAndPlatformScriptContracts(unittest.TestCase):
    def _read(self, rel_path: str) -> str:
        return Path(os.path.join(BACKEND_DIR, rel_path)).read_text(encoding="utf-8")

    def test_restart_wrapper_has_singleton_pid_lock(self) -> None:
        raw = self._read("restart_wrapper.sh")
        self.assertIn('WRAPPER_PID_FILE=', raw)
        self.assertIn('_acquire_pid_lock()', raw)
        self.assertIn("trap '_forward_signal' TERM INT", raw)
        self.assertIn("trap '_release_pid_lock' EXIT", raw)

    def test_start_platform_does_not_blindly_spawn_duplicate_whatsapp_watcher(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn('WHATSAPP_SESSION="whatsapp_watcher"', raw)
        self.assertIn('if tmux has-session -t "${WHATSAPP_SESSION}"', raw)
        self.assertIn('whatsapp_watcher already running', raw)

    def test_start_platform_preflights_whatsapp_watcher_prerequisites(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn("whatsapp_watcher_preflight()", raw)
        self.assertIn('whatsapp_preflight="$(whatsapp_watcher_preflight)"', raw)
        self.assertIn('missing_db::*', raw)
        self.assertIn('missing_group::*', raw)
        self.assertIn('whatsapp_watcher skipped (db missing:', raw)
        self.assertIn('whatsapp_watcher skipped (group missing:', raw)

    def test_start_platform_preflights_telegram_watcher_prerequisites(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn("telegram_watcher_preflight()", raw)
        self.assertIn('telegram_preflight="$(telegram_watcher_preflight)"', raw)
        self.assertIn('missing_token::*', raw)
        self.assertIn('missing_watch_chats::*', raw)
        self.assertIn('telegram_watcher skipped (token missing:', raw)
        self.assertIn('telegram_watcher skipped (watch chats missing:', raw)

    def test_platform_scripts_clean_orphan_ui_server_before_managing_tmux_ui_session(self) -> None:
        start_raw = self._read("start_platform.sh")
        stop_raw = self._read("stop_platform.sh")
        self.assertIn("kill_orphans_by_pattern()", start_raw)
        self.assertIn('UI_SESSION="ui8787"', start_raw)
        self.assertIn('UI_PORT=8787', start_raw)
        self.assertIn('kill_orphans_by_pattern "python3 -m http.server ${UI_PORT}" "ui_server"', start_raw)
        self.assertIn('tmux new-session -d -s "${UI_SESSION}" "python3 -m http.server ${UI_PORT} --directory ${UI_DIR}"', start_raw)
        self.assertIn('UI_SESSION="ui8787"', stop_raw)
        self.assertIn('UI_PORT=8787', stop_raw)
        self.assertIn('kill_orphans_by_pattern "python3 -m http.server ${UI_PORT}" "ui_server"', stop_raw)

    def test_start_platform_resolves_forwarder_session_from_team_config(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn("resolve_forwarder_session()", raw)
        self.assertIn('python3 - "${BRIDGE_DIR}/team.json"', raw)
        self.assertIn('if role == "manager" or {"manager", "projektleiter", "teamlead"} & aliases:', raw)
        self.assertIn('FORWARDER_SESSION="$(resolve_forwarder_session)"', raw)
        self.assertIn('start_process output_forwarder env FORWARDER_SESSION="${FORWARDER_SESSION}" python3 -u "${BRIDGE_DIR}/output_forwarder.py"', raw)

    def test_server_uses_same_forwarder_session_resolution_for_platform_and_supervisor(self) -> None:
        raw = self._read("server.py")
        supervisor_raw = self._read("daemons/supervisor.py")
        self.assertIn("def _resolve_forwarder_session_name()", raw)
        self.assertIn('explicit = str(os.environ.get("FORWARDER_SESSION", "")).strip()', raw)
        self.assertIn('if role == "manager" or {"manager", "projektleiter", "teamlead"} & aliases:', raw)
        self.assertIn('return _tmux_session_for(agent_id)', raw)
        self.assertIn('_fwd_session = _resolve_forwarder_session_name()', raw)
        self.assertIn('forwarder_session = _resolve_forwarder_session_name_cb()', supervisor_raw)
        self.assertIn('popen_env["FORWARDER_SESSION"] = forwarder_session', supervisor_raw)
        self.assertIn('_fwd_env["FORWARDER_SESSION"] = _fwd_session', raw)
        self.assertNotIn('_fwd_session = "acw_manager"', raw)

    def test_start_platform_waits_for_stable_server_before_runtime_configure(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"', raw)
        self.assertIn('BRIDGE_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"', raw)
        self.assertIn('BRIDGE_DIR="${SCRIPT_DIR}"', raw)
        self.assertIn('PROJECT_PATH="${PROJECT_PATH:-${BRIDGE_PROJECT_ROOT}}"', raw)
        self.assertIn("wait_for_stable_server()", raw)
        self.assertIn("wait_for_configured_runtime()", raw)
        self.assertIn('RUNTIME_CONFIGURE_HTTP_TIMEOUT="${RUNTIME_CONFIGURE_HTTP_TIMEOUT:-90}"', raw)
        self.assertIn('RUNTIME_CONFIGURE_STABILIZE_SECONDS="${RUNTIME_CONFIGURE_STABILIZE_SECONDS:-30}"', raw)
        self.assertIn('SERVER_CONFIGURE_UPTIME="${SERVER_CONFIGURE_UPTIME:-5}"', raw)
        self.assertIn('SERVER_STABLE_UPTIME="${SERVER_STABLE_UPTIME:-60}"', raw)
        self.assertIn("min_uptime", raw)
        self.assertIn('wait_for_stable_server 240 0.5 3 "${SERVER_CONFIGURE_UPTIME}"', raw)
        self.assertIn("configure_runtime_once || true", raw)
        self.assertIn('if wait_for_configured_runtime 40 0.25; then', raw)
        self.assertIn('if ! wait_for_stable_server 240 0.5 3 "${SERVER_CONFIGURE_UPTIME}"; then', raw)
        self.assertIn('if ! wait_for_configured_runtime 20 0.25; then', raw)
        self.assertIn('http_timeout = float(os.environ.get("RUNTIME_CONFIGURE_HTTP_TIMEOUT", "90"))', raw)
        self.assertIn('stabilize_seconds = max(float(os.environ.get("RUNTIME_CONFIGURE_STABILIZE_SECONDS", "30")), 0.0)', raw)
        self.assertIn('"stabilize_seconds": stabilize_seconds,', raw)
        self.assertIn('with urllib.request.urlopen(req, timeout=http_timeout) as resp:', raw)
        self.assertIn("stable_count", raw)
        self.assertIn("uptime_seconds", raw)

    def test_start_platform_autostarts_local_n8n_from_shared_env_contract(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn('N8N_ENV_FILE="${N8N_ENV_FILE:-${HOME}/.config/bridge/n8n.env}"', raw)
        self.assertIn('N8N_AUTOSTART="${N8N_AUTOSTART:-1}"', raw)
        self.assertIn('N8N_START_TIMEOUT_SECONDS="${N8N_START_TIMEOUT_SECONDS:-45}"', raw)
        self.assertIn("load_n8n_base_url()", raw)
        self.assertIn("load_n8n_api_key()", raw)
        self.assertIn("load_n8n_timezone()", raw)
        self.assertIn('configured="$(load_env_file_value "${N8N_ENV_FILE}" "N8N_TIMEZONE")"', raw)
        self.assertIn('configured="$(load_env_file_value "${N8N_ENV_FILE}" "GENERIC_TIMEZONE")"', raw)
        self.assertIn('if [[ -f /etc/timezone ]]; then', raw)
        self.assertIn('tz_link="$(readlink -f /etc/localtime 2>/dev/null || true)"', raw)
        self.assertIn("resolve_local_n8n_target()", raw)
        self.assertIn("wait_for_n8n_api()", raw)
        self.assertIn("ensure_local_n8n_runtime()", raw)
        self.assertIn('timezone="$(load_n8n_timezone)"', raw)
        self.assertIn('start_process n8n env N8N_HOST="${host}" N8N_PORT="${port}" TZ="${timezone}" GENERIC_TIMEZONE="${timezone}" n8n start', raw)
        self.assertIn('n8n autostart skipped (external base URL: ${base_url})', raw)
        self.assertIn('n8n failed to start or authenticate, check ${LOG_DIR}/n8n.log', raw)
        self.assertIn("ensure_local_n8n_runtime", raw)
        self.assertLess(raw.index('if ! wait_for_configured_runtime 20 0.25; then'), raw.rindex("ensure_local_n8n_runtime"))

    def test_server_logs_websocket_request_context_on_auth_paths(self) -> None:
        raw = self._read("server.py")
        ws_raw = self._read("websocket_server.py")
        startup_raw = self._read("server_startup.py")
        self.assertIn("def _ws_request_context()", ws_raw)
        self.assertIn('headers.get("User-Agent", "")', ws_raw)
        self.assertIn('headers.get("Origin", "")', ws_raw)
        self.assertIn('headers.get("Referer", "")', ws_raw)
        self.assertIn('invalid token ({_ws_request_context()})', ws_raw)
        self.assertIn('first message not auth ({_ws_request_context()})', ws_raw)
        self.assertIn('client connected: {remote} (agent_id={ws_agent_id}, role={ws_role}, {_ws_request_context()})', ws_raw)
        self.assertIn("run_websocket_server_fn=run_websocket_server", raw)
        self.assertIn('threading.Thread(target=target, daemon=True, name=name)', startup_raw)
        self.assertIn('_start_named_thread(_RUN_WEBSOCKET_SERVER, "websocket-server")', startup_raw)

    def test_start_platform_uses_restart_wrapper_pid_for_wrapper_lifecycle(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn("start_server_supervisor()", raw)
        self.assertIn('wrapper_pid_file="${PID_DIR}/restart_wrapper.pid"', raw)
        self.assertIn('restart wrapper pid ${existing_pid} is alive but endpoint is down; restarting wrapper', raw)
        self.assertIn('WRAPPER_STOP_MARKER="/tmp/bridge_stop_requested"', raw)
        self.assertIn('local server_pid_file="${PID_DIR}/server.pid"', raw)
        self.assertIn('cleanup_stale_pid_file "${server_pid_file}"', raw)
        self.assertIn('echo "${new_pid}" > "${wrapper_pid_file}"', raw)
        restart_block = raw[raw.index('restart wrapper pid ${existing_pid} is alive but endpoint is down; restarting wrapper'):]
        self.assertIn(': > "${WRAPPER_STOP_MARKER}"', restart_block)
        self.assertLess(restart_block.index(': > "${WRAPPER_STOP_MARKER}"'), restart_block.index('stop_pid_hard "${existing_pid}"'))

    def test_start_platform_disables_wrapper_autostart_bootstrap(self) -> None:
        raw = self._read("start_platform.sh")
        self.assertIn('start_server_supervisor', raw)
        self.assertIn('env BRIDGE_SKIP_WRAPPER_AUTOSTART=1 "${BRIDGE_DIR}/restart_wrapper.sh"', raw)
        self.assertNotIn('start_process server env BRIDGE_SKIP_WRAPPER_AUTOSTART=1 "${BRIDGE_DIR}/restart_wrapper.sh"', raw)
        self.assertIn('if ! python3 -u "${BRIDGE_DIR}/start_agents.py" 2>&1 | tee -a "${LOG_DIR}/start_agents.log"; then', raw)
        self.assertIn('AUTO_START_DEGRADED=0', raw)
        self.assertIn('echo "agent auto-start degraded, check ${LOG_DIR}/start_agents.log" >&2', raw)
        auto_start_block = raw[raw.index('# --- Auto-Agent-Start'):raw.index('# --- UI Server')]
        self.assertNotIn("exit 1", auto_start_block)
        self.assertIn('if [[ "${AUTO_START_DEGRADED}" == "1" ]]; then', raw)

    def test_server_allows_whatsapp_voice_approval_action(self) -> None:
        self.assertIn("whatsapp_voice", srv.ALLOWED_APPROVAL_ACTIONS)

    def test_server_allows_telegram_send_approval_action(self) -> None:
        self.assertIn("telegram_send", srv.ALLOWED_APPROVAL_ACTIONS)

    def test_restart_wrapper_supports_external_bootstrap_mode(self) -> None:
        raw = self._read("restart_wrapper.sh")
        self.assertIn('SKIP_AUTOSTART="${BRIDGE_SKIP_WRAPPER_AUTOSTART:-0}"', raw)
        self.assertIn('Wrapper autostart disabled; waiting for external bootstrap.', raw)
        self.assertIn('if [ "$SKIP_AUTOSTART" = "1" ]; then', raw)
        self.assertIn("_should_forward_signal()", raw)
        self.assertIn("wait_for_server_exit()", raw)
        self.assertIn('SERVER_EXIT_CODE=0', raw)
        self.assertIn('if [ "$SKIP_AUTOSTART" != "1" ]; then', raw)
        self.assertIn('if [ -f "$STOP_MARKER" ] || [ -f "$RESTART_MARKER" ]; then', raw)
        self.assertIn('Signal received in external bootstrap mode without stop/restart marker. Ignoring.', raw)
        self.assertIn('Wait for server interrupted, but child is still running (pid=$SERVER_PID). Continuing to wait.', raw)
        self.assertIn('EXIT_CODE=$SERVER_EXIT_CODE', raw)
        self.assertIn('if python3 -u "$SCRIPT_DIR/start_agents.py" >> "$SCRIPT_DIR/logs/start_agents.log" 2>&1; then', raw)
        self.assertIn('log "WARN: start_agents.py failed"', raw)

    def test_stop_platform_also_stops_whatsapp_watcher_session(self) -> None:
        raw = self._read("stop_platform.sh")
        self.assertIn('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"', raw)
        self.assertIn('PID_DIR="${SCRIPT_DIR}/pids"', raw)
        self.assertIn('WHATSAPP_SESSION="whatsapp_watcher"', raw)
        self.assertIn('tmux kill-session -t "${WHATSAPP_SESSION}"', raw)

    def test_stop_platform_also_stops_telegram_watcher_session(self) -> None:
        raw = self._read("stop_platform.sh")
        self.assertIn('TELEGRAM_SESSION="telegram_watcher"', raw)
        self.assertIn('tmux kill-session -t "${TELEGRAM_SESSION}"', raw)

    def test_init_prompt_uses_tmux_buffer_paste_for_tui_clis(self) -> None:
        raw = self._read("init_agent_prompt.sh")
        self.assertIn('LOG_FILE="${LOG_DIR}/init_agent_prompt.log"', raw)
        self.assertIn('BUFFER_NAME="bridge_init_', raw)
        self.assertIn('tmux load-buffer -b "$BUFFER_NAME" -', raw)
        self.assertIn('tmux paste-buffer -b "$BUFFER_NAME" -t "$SESSION"', raw)
        self.assertNotIn('tmux send-keys -t "$SESSION" "$PROMPT"', raw)

    def test_init_prompt_uses_python_regex_matching_for_tmux_prompts(self) -> None:
        raw = self._read("init_agent_prompt.sh")
        self.assertIn('prompt_regex_matches()', raw)
        self.assertIn('RECENT_LINES="$recent_lines" PROMPT_REGEX="$PROMPT_REGEX" python3 - <<\'PY\'', raw)
        self.assertIn('re.search(pattern, line)', raw)
        self.assertNotIn('grep -Eq "$PROMPT_REGEX"', raw)

    def test_init_prompt_bootstraps_gemini_qwen_bridge_tool_approvals(self) -> None:
        raw = self._read("init_agent_prompt.sh")
        self.assertIn('ENGINE="${6:-}"', raw)
        self.assertIn('if [ "$ENGINE" = "gemini" ] || [ "$ENGINE" = "qwen" ]; then', raw)
        self.assertIn('Bypass confirmation for trusted tools', raw)
        self.assertIn('Allow execution of MCP tool "', raw)
        self.assertIn('tmux send-keys -t "$SESSION" C-y', raw)
        self.assertIn('tmux send-keys -t "$SESSION" Down', raw)

    def test_stop_hook_uses_bounded_shared_queue_polling(self) -> None:
        raw = self._read("stop_hook.sh")
        self.assertIn("bridge_task_queue(state='created', limit=50)", raw)

    def test_stop_platform_uses_process_patterns_that_match_relative_invocations(self) -> None:
        raw = self._read("stop_platform.sh")
        self.assertIn('kill_orphans_by_pattern "python3.*bridge_mcp.py" "bridge_mcp"', raw)
        self.assertIn('kill_orphans_by_pattern "python3.*bridge_watcher.py" "watcher"', raw)
        self.assertIn('kill_orphans_by_pattern "python3.*output_forwarder.py" "output_forwarder"', raw)
        self.assertIn('kill_orphans_by_pattern "n8n start" "n8n"', raw)

    def test_stop_platform_cleans_bridge_cli_orphans_by_session_identity(self) -> None:
        raw = self._read("stop_platform.sh")
        self.assertIn("bridge_proc_env_value()", raw)
        self.assertIn("tmux_session_env_value()", raw)
        self.assertIn('session_name="$(bridge_proc_env_value "${pid}" "BRIDGE_CLI_SESSION_NAME")"', raw)
        self.assertIn('proc_incarnation="$(bridge_proc_env_value "${pid}" "BRIDGE_CLI_INCARNATION_ID")"', raw)
        self.assertIn('if ! tmux has-session -t "${session_name}" 2>/dev/null; then', raw)
        self.assertIn('live_incarnation="$(tmux_session_env_value "${session_name}" "BRIDGE_CLI_INCARNATION_ID")"', raw)
        self.assertIn('kill_bridge_cli_orphans', raw)

    def test_server_imports_copy_for_task_timeout_and_deepcopy_paths(self) -> None:
        raw = self._read("server.py")
        self.assertIn("import copy", raw)

    def test_server_wires_codex_hook_to_runtime_message_lock(self) -> None:
        raw = self._read("server.py")
        self.assertIn("msg_lock=LOCK,", raw)
        self.assertNotIn("msg_lock=_MESSAGES_LOCK,", raw)

    def test_server_defines_task_lease_helpers(self) -> None:
        raw = self._read("handlers/tasks.py")
        self.assertIn("def _clear_task_lease(", raw)
        self.assertIn("def _refresh_task_lease(", raw)

    def test_server_installs_graceful_sigterm_handler(self) -> None:
        raw = self._read("server.py")
        bootstrap_raw = self._read("server_bootstrap.py")
        main_raw = self._read("server_main.py")
        self.assertIn("def _server_signal_handler(", bootstrap_raw)
        self.assertIn("server_signal_handler_fn=_server_signal_handler", raw)
        self.assertIn("signal.signal(signal.SIGTERM, _SERVER_SIGNAL_HANDLER)", main_raw)

    def test_restart_kill_phase_uses_process_wide_sigterm(self) -> None:
        raw = self._read("daemons/restart_control.py")
        self.assertIn("RESTART_STATE[\"phase\"] = \"restarting\"", raw)
        self.assertIn("os.kill(os.getpid(), signal.SIGTERM)", raw)

    def test_server_snapshots_registered_agents_for_read_paths(self) -> None:
        raw = self._read("server.py")
        agents_raw = self._read("handlers/agents.py")
        self.assertIn("def _registered_agents_snapshot(", agents_raw)
        self.assertIn("for agent_id, reg in _registered_agents_snapshot().items()", raw)
        self.assertIn("registered_agents = _registered_agents_snapshot()", raw)

    def test_server_uses_expanded_http_accept_queue(self) -> None:
        raw = self._read("server.py")
        bootstrap_raw = self._read("server_bootstrap.py")
        self.assertIn('HTTP_REQUEST_QUEUE_SIZE = max(32, int(os.environ.get("BRIDGE_HTTP_REQUEST_QUEUE_SIZE", "256")))', raw)
        self.assertIn("class BridgeThreadingHTTPServer(ThreadingHTTPServer):", bootstrap_raw)
        self.assertIn("daemon_threads = True", bootstrap_raw)
        self.assertIn("request_queue_size = 256", bootstrap_raw)

    def test_server_uses_registered_agents_snapshots_for_unlocked_reads(self) -> None:
        raw = self._read("server.py")
        agents_raw = self._read("handlers/agents.py")
        restart_raw = self._read("daemons/restart_control.py")
        self.assertIn("def _registered_agents_snapshot(", agents_raw)
        self.assertIn("for agent_id, reg in _registered_agents_snapshot().items()", raw)
        self.assertIn("for agent_id in _registered_agents_snapshot_cb().keys()", restart_raw)
        self.assertIn("def _agent_is_live(", agents_raw)

    def test_server_uses_buffered_threading_http_server(self) -> None:
        raw = self._read("server.py")
        bootstrap_raw = self._read("server_bootstrap.py")
        main_raw = self._read("server_main.py")
        self.assertIn("HTTP_REQUEST_QUEUE_SIZE =", raw)
        self.assertIn("class BridgeThreadingHTTPServer(ThreadingHTTPServer):", bootstrap_raw)
        self.assertIn("daemon_threads = True", bootstrap_raw)
        self.assertIn("request_queue_size = 256", bootstrap_raw)
        self.assertIn("def _create_http_server_with_retry(", bootstrap_raw)
        self.assertIn("create_http_server_with_retry_fn=_create_http_server_with_retry", raw)
        self.assertIn("server = _CREATE_HTTP_SERVER_WITH_RETRY(", main_raw)
        self.assertIn('os.environ.get("BRIDGE_HTTP_BIND_RETRIES", "20")', main_raw)
        self.assertIn('os.environ.get("BRIDGE_HTTP_BIND_RETRY_DELAY", "0.5")', main_raw)

    def test_bridge_mcp_task_queue_supports_limit(self) -> None:
        raw = self._read("bridge_mcp.py")
        self.assertIn("async def bridge_task_queue(", raw)
        self.assertIn("limit: int = 0", raw)

    def test_server_seeds_phantom_registration_for_manual_configured_starts(self) -> None:
        raw = self._read("server.py")
        self.assertIn("def _seed_phantom_agent_registration(", raw)
        self.assertIn("_seed_phantom_agent_registration(", raw)
        self.assertIn('if _start_agent_from_conf(agent_id):', raw)
        self.assertIn('_seed_phantom_agent_registration(agent_id, role=phantom_role)', raw)

    def test_server_cleanup_keeps_live_tmux_sessions_registered(self) -> None:
        raw = self._read("server.py")
        self.assertIn("def _auto_cleanup_agents(", raw)
        self.assertIn('if agent_id in runtime_ids or _check_tmux_session(agent_id):', raw)

    def test_agent_detail_exposes_phantom_flag(self) -> None:
        raw = self._read("server.py")
        self.assertIn('"phantom": bool(reg.get("phantom", False)) if reg else False,', raw)

    def test_server_audits_runtime_configure_requests(self) -> None:
        raw = self._read("server.py")
        self.assertIn("RUNTIME_CONFIGURE_AUDIT_LOG =", raw)
        self.assertIn("def _runtime_configure_payload_summary(", raw)
        self.assertIn("def _append_runtime_configure_audit(", raw)
        self.assertIn('_append_runtime_configure_audit("request", runtime_request_meta, runtime_payload_summary)', raw)
        self.assertIn('_append_runtime_configure_audit(', raw)
        self.assertIn('"success"', raw)


if __name__ == "__main__":
    unittest.main()
