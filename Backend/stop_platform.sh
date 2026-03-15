#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="${SCRIPT_DIR}/pids"
SERVER_URL="${SERVER_URL:-http://127.0.0.1:9111}"
TOKEN_CONFIG_FILE="${TOKEN_CONFIG_FILE:-${HOME}/.config/bridge/tokens.json}"

load_bridge_user_token() {
  if [[ -n "${BRIDGE_USER_TOKEN:-}" ]]; then
    printf '%s' "${BRIDGE_USER_TOKEN}"
    return 0
  fi

  python3 - "${TOKEN_CONFIG_FILE}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print("", end="")
else:
    print(str(payload.get("user_token", "")).strip(), end="")
PY
}

BRIDGE_USER_TOKEN="${BRIDGE_USER_TOKEN:-$(load_bridge_user_token)}"
CURL_AUTH_ARGS=()
if [[ -n "${BRIDGE_USER_TOKEN}" ]]; then
  CURL_AUTH_ARGS=(-H "X-Bridge-Token: ${BRIDGE_USER_TOKEN}")
fi

# Signal restart_wrapper to NOT restart after we kill the server
touch /tmp/bridge_stop_requested

if curl -fsS "${SERVER_URL}/status" >/dev/null 2>&1; then
  curl -fsS -X POST "${SERVER_URL}/runtime/stop" "${CURL_AUTH_ARGS[@]}" >/dev/null 2>&1 || true
fi

stop_pid_file() {
  local pid_file="$1"
  local name
  name="$(basename "${pid_file}" .pid)"
  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"

  if [[ -z "${pid}" ]]; then
    rm -f "${pid_file}"
    return
  fi

  if kill -0 "${pid}" >/dev/null 2>&1; then
    echo "stopping ${name} (pid=${pid})"
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 0.5
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  else
    echo "${name} already stopped"
  fi

  rm -f "${pid_file}"
}

kill_orphans_by_pattern() {
  local pattern="$1"
  local name="$2"
  local pids
  pids="$(pgrep -f "${pattern}" || true)"
  if [[ -z "${pids}" ]]; then
    return
  fi

  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    if kill -0 "${pid}" >/dev/null 2>&1; then
      echo "stopping orphan ${name} (pid=${pid})"
      kill "${pid}" >/dev/null 2>&1 || true
      sleep 0.2
      if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -9 "${pid}" >/dev/null 2>&1 || true
      fi
    fi
  done <<< "${pids}"
}

bridge_proc_env_value() {
  local pid="$1"
  local key="$2"
  if [[ -z "${pid}" || -z "${key}" || ! -r "/proc/${pid}/environ" ]]; then
    return 0
  fi
  tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | awk -F= -v wanted="${key}" '$1 == wanted { print substr($0, index($0, "=") + 1); exit }'
}

tmux_session_env_value() {
  local session_name="$1"
  local key="$2"
  if [[ -z "${session_name}" || -z "${key}" ]]; then
    return 0
  fi
  tmux show-environment -t "${session_name}" "${key}" 2>/dev/null | sed -e "s/^${key}=//" -e '/^-.*$/d'
}

kill_bridge_cli_orphans() {
  local pids
  pids="$(pgrep -f "claude|codex" || true)"
  if [[ -z "${pids}" ]]; then
    return
  fi

  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    [[ ! -d "/proc/${pid}" ]] && continue

    local session_name
    local proc_incarnation
    local live_incarnation

    session_name="$(bridge_proc_env_value "${pid}" "BRIDGE_CLI_SESSION_NAME")"
    [[ -z "${session_name}" ]] && continue
    proc_incarnation="$(bridge_proc_env_value "${pid}" "BRIDGE_CLI_INCARNATION_ID")"

    if ! tmux has-session -t "${session_name}" 2>/dev/null; then
      echo "stopping orphan bridge_cli (pid=${pid} session=${session_name})"
      kill "${pid}" >/dev/null 2>&1 || true
      sleep 0.2
      if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -9 "${pid}" >/dev/null 2>&1 || true
      fi
      continue
    fi

    live_incarnation="$(tmux_session_env_value "${session_name}" "BRIDGE_CLI_INCARNATION_ID")"
    if [[ -n "${proc_incarnation}" && -n "${live_incarnation}" && "${proc_incarnation}" != "${live_incarnation}" ]]; then
      echo "stopping stale bridge_cli (pid=${pid} session=${session_name} incarnation=${proc_incarnation} live=${live_incarnation})"
      kill "${pid}" >/dev/null 2>&1 || true
      sleep 0.2
      if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -9 "${pid}" >/dev/null 2>&1 || true
      fi
    fi
  done <<< "${pids}"
}

shopt -s nullglob
pid_files=()
if [[ -d "${PID_DIR}" ]]; then
  pid_files=("${PID_DIR}"/*.pid)
else
  echo "pid dir missing — continuing with orphan cleanup"
fi

if [[ ${#pid_files[@]} -eq 0 ]]; then
  echo "no pid files found — continuing with orphan cleanup"
fi

# Graceful shutdown: warn agents before killing
echo "60" > /tmp/bridge_restart_warn
curl -fsS -X POST "${SERVER_URL}/send" \
  "${CURL_AUTH_ARGS[@]}" \
  -H "Content-Type: application/json" \
  -d '{"from":"system","to":"all","content":"[RESTART WARN] Server-Restart in 60s. PFLICHT: Kontext sichern!"}' \
  >/dev/null 2>&1 || true
echo "restart warning sent — waiting 60s for agents to save context..."
sleep 60
rm -f /tmp/bridge_restart_warn

for pid_file in "${pid_files[@]}"; do
  stop_pid_file "${pid_file}"
done

kill_orphans_by_pattern "python3.*bridge_mcp.py" "bridge_mcp"
kill_orphans_by_pattern "python3.*server.py" "server"
kill_orphans_by_pattern "python3.*agent_client.py" "agent_client"
kill_orphans_by_pattern "python3.*output_forwarder.py" "output_forwarder"
kill_orphans_by_pattern "python3.*bridge_watcher.py" "watcher"
kill_orphans_by_pattern "n8n start" "n8n"
kill_bridge_cli_orphans

# --- UI Server (port 8787) --- REMOVED
# UI is now served exclusively by the Bridge server on port 9111.
# Clean up any leftover 8787 sessions from previous runs.
if tmux has-session -t "ui8787" 2>/dev/null; then
  tmux kill-session -t "ui8787" 2>/dev/null || true
fi
kill_orphans_by_pattern "python3 -m http.server 8787" "ui_server_legacy"

WHATSAPP_SESSION="whatsapp_watcher"
if tmux has-session -t "${WHATSAPP_SESSION}" 2>/dev/null; then
  echo "stopping whatsapp watcher (tmux session: ${WHATSAPP_SESSION})"
  tmux kill-session -t "${WHATSAPP_SESSION}" 2>/dev/null || true
else
  echo "whatsapp watcher already stopped"
fi

TELEGRAM_SESSION="telegram_watcher"
if tmux has-session -t "${TELEGRAM_SESSION}" 2>/dev/null; then
  echo "stopping telegram watcher (tmux session: ${TELEGRAM_SESSION})"
  tmux kill-session -t "${TELEGRAM_SESSION}" 2>/dev/null || true
else
  echo "telegram watcher already stopped"
fi

rm -f "${PID_DIR}/"*.pid 2>/dev/null || true

echo "platform stopped"
