#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE_DIR="${SCRIPT_DIR}"
LOG_DIR="${BRIDGE_DIR}/logs"
PID_DIR="${BRIDGE_DIR}/pids"
MESSAGE_LOG="${BRIDGE_DIR}/messages/bridge.jsonl"
SERVER_URL="${SERVER_URL:-http://127.0.0.1:9111}"
WRAPPER_STOP_MARKER="/tmp/bridge_stop_requested"
BRIDGE_STRICT_AUTH="${BRIDGE_STRICT_AUTH:-1}"
TOKEN_CONFIG_FILE="${TOKEN_CONFIG_FILE:-${HOME}/.config/bridge/tokens.json}"
N8N_ENV_FILE="${N8N_ENV_FILE:-${HOME}/.config/bridge/n8n.env}"

# E1: Credential Store encryption key (auto-generated if missing)
if [ -z "${BRIDGE_CRED_KEY:-}" ]; then
  CRED_KEY_FILE="${BRIDGE_DIR}/.cred_key"
  if [ -f "${CRED_KEY_FILE}" ]; then
    export BRIDGE_CRED_KEY="$(cat "${CRED_KEY_FILE}")"
  else
    export BRIDGE_CRED_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    echo "${BRIDGE_CRED_KEY}" > "${CRED_KEY_FILE}"
    chmod 600 "${CRED_KEY_FILE}"
    echo "[start_platform] Generated new BRIDGE_CRED_KEY → ${CRED_KEY_FILE}"
  fi
fi

PAIR_MODE="${PAIR_MODE:-codex-claude}"
AGENT_A_ENGINE="${AGENT_A_ENGINE:-}"
AGENT_B_ENGINE="${AGENT_B_ENGINE:-}"
PROJECT_PATH="${PROJECT_PATH:-${BRIDGE_PROJECT_ROOT}}"
ALLOW_PEER_AUTO="${ALLOW_PEER_AUTO:-0}"
PEER_AUTO_REQUIRE_FLAG="${PEER_AUTO_REQUIRE_FLAG:-1}"
MAX_PEER_HOPS="${MAX_PEER_HOPS:-20}"
MAX_TURNS="${MAX_TURNS:-0}"
PROCESS_ALL="${PROCESS_ALL:-0}"
KEEP_HISTORY="${KEEP_HISTORY:-0}"
TIMEOUT="${TIMEOUT:-90}"
RUNTIME_CONFIGURE_HTTP_TIMEOUT="${RUNTIME_CONFIGURE_HTTP_TIMEOUT:-90}"
RUNTIME_CONFIGURE_STABILIZE_SECONDS="${RUNTIME_CONFIGURE_STABILIZE_SECONDS:-30}"
SERVER_CONFIGURE_UPTIME="${SERVER_CONFIGURE_UPTIME:-5}"
SERVER_STABLE_UPTIME="${SERVER_STABLE_UPTIME:-60}"
N8N_AUTOSTART="${N8N_AUTOSTART:-1}"
N8N_START_TIMEOUT_SECONDS="${N8N_START_TIMEOUT_SECONDS:-45}"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

is_pid_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

stop_pid_hard() {
  local pid="$1"
  if [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    return
  fi
  if ! is_pid_running "${pid}"; then
    return
  fi
  kill "${pid}" >/dev/null 2>&1 || true
  sleep 0.5
  if is_pid_running "${pid}"; then
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
}

cleanup_stale_pid_file() {
  local pid_file="$1"
  if [[ ! -f "${pid_file}" ]]; then
    return
  fi
  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    rm -f "${pid_file}"
    return
  fi
  if ! is_pid_running "${pid}"; then
    rm -f "${pid_file}"
  fi
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

wait_for_endpoint() {
  local url="$1"
  local attempts="${2:-30}"
  local sleep_secs="${3:-0.5}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_secs}"
  done
  return 1
}

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

ensure_bridge_user_token() {
  if [[ -n "${BRIDGE_USER_TOKEN:-}" ]]; then
    return 0
  fi
  local token
  token="$(load_bridge_user_token)"
  if [[ -n "${token}" ]]; then
    export BRIDGE_USER_TOKEN="${token}"
  fi
}

load_env_file_value() {
  local env_file="$1"
  local key="$2"
  python3 - "${env_file}" "${key}" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1]).expanduser()
wanted = sys.argv[2]

try:
    lines = env_path.read_text(encoding="utf-8").splitlines()
except OSError:
    print("", end="")
    raise SystemExit(0)

for raw in lines:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    if key.strip() == wanted:
        print(value.strip(), end="")
        raise SystemExit(0)

print("", end="")
PY
}

load_n8n_base_url() {
  if [[ -n "${N8N_BASE_URL:-}" ]]; then
    printf '%s' "${N8N_BASE_URL}"
    return 0
  fi
  load_env_file_value "${N8N_ENV_FILE}" "N8N_BASE_URL"
}

load_n8n_api_key() {
  if [[ -n "${N8N_API_KEY:-}" ]]; then
    printf '%s' "${N8N_API_KEY}"
    return 0
  fi
  load_env_file_value "${N8N_ENV_FILE}" "N8N_API_KEY"
}

whatsapp_watcher_preflight() {
  python3 - "${BRIDGE_DIR}" <<'PY'
import json
import os
import sys

bridge_dir = sys.argv[1]
env_config = os.environ.get("WHATSAPP_CONFIG_PATH", "").strip()
if env_config:
    config_candidates = [os.path.expanduser(env_config)]
else:
    config_candidates = [
        os.path.expanduser("~/.config/bridge/whatsapp_config.json"),
        os.path.join(bridge_dir, "whatsapp_config.json"),
    ]

config_path = ""
config = {}
for candidate in config_candidates:
    if not candidate or not os.path.exists(candidate):
        continue
    config_path = candidate
    try:
        with open(candidate, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            config = payload
    except Exception:
        config = {}
    break

env_db = os.environ.get("WHATSAPP_DB_PATH", "").strip()
if env_db:
    db_path = os.path.expanduser(env_db)
else:
    defaults = [
        os.path.expanduser("~/.config/bridge/whatsapp-bridge/store/messages.db"),
        os.path.expanduser("~/.local/share/bridge/whatsapp-bridge/store/messages.db"),
    ]
    db_path = next((path for path in defaults if os.path.exists(path)), defaults[0])

group_jid = os.environ.get("WHATSAPP_GROUP_JID", "").strip() or str(config.get("watch_group_jid", "")).strip()

if not os.path.exists(db_path):
    print(f"missing_db::{db_path}")
elif not group_jid:
    source = config_path or "WHATSAPP_GROUP_JID"
    print(f"missing_group::{source}")
else:
    print(f"ready::{db_path}::{config_path or '-'}::{group_jid}")
PY
}

telegram_watcher_preflight() {
  python3 - "${BRIDGE_DIR}" <<'PY'
import json
import os
import sys

bridge_dir = sys.argv[1]
env_config = os.environ.get("TELEGRAM_CONFIG_PATH", "").strip()
if env_config:
    config_candidates = [os.path.expanduser(env_config)]
else:
    config_candidates = [
        os.path.expanduser("~/.config/bridge/telegram_config.json"),
        os.path.join(bridge_dir, "telegram_config.json"),
    ]

config_path = ""
config = {}
for candidate in config_candidates:
    if not candidate or not os.path.exists(candidate):
        continue
    config_path = candidate
    try:
        with open(candidate, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            config = payload
    except Exception:
        config = {}
    break

token_source = "TELEGRAM_BOT_TOKEN"
token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    token_source = os.path.expanduser("~/.config/bridge/telegram_bot_token")
    if os.path.exists(token_source):
        try:
            with open(token_source, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            token = ""

watch_source = "TELEGRAM_WATCH_CHATS"
watch_chats_env = os.environ.get("TELEGRAM_WATCH_CHATS", "").strip()
if watch_chats_env:
    watch_chats = [value.strip() for value in watch_chats_env.split(",") if value.strip()]
else:
    raw = config.get("watch_chats") or config.get("read_whitelist") or []
    watch_source = config_path or "telegram_config.json"
    if isinstance(raw, list):
        watch_chats = [str(value).strip() for value in raw if str(value).strip()]
    else:
        watch_chats = []

if not token:
    print(f"missing_token::{token_source}")
elif not watch_chats:
    print(f"missing_watch_chats::{watch_source}")
else:
    print(f"ready::{config_path or '-'}::{len(watch_chats)}")
PY
}

load_n8n_timezone() {
  if [[ -n "${N8N_TIMEZONE:-}" ]]; then
    printf '%s' "${N8N_TIMEZONE}"
    return 0
  fi

  local configured
  configured="$(load_env_file_value "${N8N_ENV_FILE}" "N8N_TIMEZONE")"
  if [[ -n "${configured}" ]]; then
    printf '%s' "${configured}"
    return 0
  fi

  configured="$(load_env_file_value "${N8N_ENV_FILE}" "GENERIC_TIMEZONE")"
  if [[ -n "${configured}" ]]; then
    printf '%s' "${configured}"
    return 0
  fi

  if [[ -n "${TZ:-}" ]]; then
    printf '%s' "${TZ}"
    return 0
  fi

  if [[ -f /etc/timezone ]]; then
    tr -d '\n' < /etc/timezone
    return 0
  fi

  local tz_link=""
  tz_link="$(readlink -f /etc/localtime 2>/dev/null || true)"
  if [[ "${tz_link}" == *"/zoneinfo/"* ]]; then
    printf '%s' "${tz_link##*/zoneinfo/}"
    return 0
  fi

  printf '%s' "UTC"
}

resolve_local_n8n_target() {
  local base_url="$1"
  python3 - "${base_url}" <<'PY'
import sys
from urllib.parse import urlparse

url = sys.argv[1].strip()
if not url:
    print("", end="")
    raise SystemExit(0)

parsed = urlparse(url)
host = (parsed.hostname or "").strip().lower()
port = parsed.port
if port is None:
    port = 443 if parsed.scheme == "https" else 80

if host in {"localhost", "127.0.0.1", "::1"}:
    print(f"{host} {port}", end="")
else:
    print("", end="")
PY
}

wait_for_n8n_api() {
  local base_url="$1"
  local api_key="$2"
  local attempts="${3:-60}"
  local sleep_secs="${4:-0.5}"
  local i
  local url="${base_url%/}/api/v1/workflows?limit=1"
  local auth_args=()

  if [[ -n "${api_key}" ]]; then
    auth_args=(-H "X-N8N-API-KEY: ${api_key}")
  fi

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "${auth_args[@]}" "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_secs}"
  done
  return 1
}

ensure_local_n8n_runtime() {
  if [[ "${N8N_AUTOSTART}" != "1" ]]; then
    echo "n8n autostart disabled"
    return 0
  fi

  local base_url
  local api_key
  local target
  local host=""
  local port=""
  local timezone=""

  base_url="$(load_n8n_base_url)"
  api_key="$(load_n8n_api_key)"
  timezone="$(load_n8n_timezone)"

  if [[ -z "${base_url}" ]]; then
    echo "n8n autostart skipped (no base URL configured)"
    return 0
  fi

  target="$(resolve_local_n8n_target "${base_url}")"
  if [[ -z "${target}" ]]; then
    echo "n8n autostart skipped (external base URL: ${base_url})"
    return 0
  fi

  read -r host port <<< "${target}"

  if [[ -z "${api_key}" ]]; then
    echo "n8n API key missing for ${base_url}; cannot verify local n8n" >&2
    return 1
  fi

  if ! command -v n8n >/dev/null 2>&1; then
    echo "n8n CLI missing for local base URL ${base_url}" >&2
    return 1
  fi

  if wait_for_n8n_api "${base_url}" "${api_key}" 4 0.5; then
    echo "n8n already reachable (${base_url})"
    return 0
  fi

  start_process n8n env N8N_HOST="${host}" N8N_PORT="${port}" TZ="${timezone}" GENERIC_TIMEZONE="${timezone}" n8n start
  if ! wait_for_n8n_api "${base_url}" "${api_key}" "$((N8N_START_TIMEOUT_SECONDS * 2))" 0.5; then
    echo "n8n failed to start or authenticate, check ${LOG_DIR}/n8n.log" >&2
    return 1
  fi

  echo "n8n ready (${base_url})"
}

wait_for_stable_server() {
  local attempts="${1:-60}"
  local sleep_secs="${2:-0.5}"
  local stable_required="${3:-4}"
  local min_uptime="${4:-0}"
  local stable_count=0
  local prev_uptime=""
  local i

  for ((i=1; i<=attempts; i++)); do
    local body=""
    body="$(curl -fsS "${SERVER_URL}/status" 2>/dev/null || true)"

    if [[ -n "${body}" ]]; then
      local parsed
      parsed="$(STATUS_JSON="${body}" python3 - <<'PY'
import json
import os

try:
    data = json.loads(os.environ["STATUS_JSON"])
    uptime = float(data.get("uptime_seconds", -1))
    running = data.get("status") == "running"
    if running and uptime >= 0:
        print(f"1 {uptime}")
    else:
        print("0 -1")
except Exception:
    print("0 -1")
PY
)"
      local ok="${parsed%% *}"
      local uptime="${parsed#* }"

      if [[ "${ok}" == "1" ]] && UPTIME_CUR="${uptime}" UPTIME_MIN="${min_uptime}" python3 - <<'PY' >/dev/null 2>&1
import os
import sys

cur = float(os.environ["UPTIME_CUR"])
min_uptime = float(os.environ["UPTIME_MIN"])
sys.exit(0 if cur >= min_uptime else 1)
PY
      then
        if [[ -n "${prev_uptime}" ]] && UPTIME_CUR="${uptime}" UPTIME_PREV="${prev_uptime}" python3 - <<'PY' >/dev/null 2>&1
import os
import sys

cur = float(os.environ["UPTIME_CUR"])
prev = float(os.environ["UPTIME_PREV"])
sys.exit(0 if cur >= prev else 1)
PY
        then
          stable_count=$((stable_count + 1))
        else
          stable_count=1
        fi

        prev_uptime="${uptime}"
        if (( stable_count >= stable_required )); then
          return 0
        fi
      else
        stable_count=0
        prev_uptime=""
      fi
    else
      stable_count=0
      prev_uptime=""
    fi

    sleep "${sleep_secs}"
  done

  return 1
}

wait_for_configured_runtime() {
  local attempts="${1:-40}"
  local sleep_secs="${2:-0.25}"
  local i

  for ((i=1; i<=attempts; i++)); do
    local body=""
    body="$(curl -fsS "${SERVER_URL}/runtime" 2>/dev/null || true)"
    if [[ -n "${body}" ]] && RUNTIME_JSON="${body}" python3 - <<'PY' >/dev/null 2>&1
import json
import os
import sys

try:
    data = json.loads(os.environ["RUNTIME_JSON"])
except Exception:
    sys.exit(1)

sys.exit(0 if data.get("configured") is True else 1)
PY
    then
      return 0
    fi
    sleep "${sleep_secs}"
  done

  return 1
}

start_process() {
  local name="$1"
  shift
  local pid_file="${PID_DIR}/${name}.pid"
  local log_file="${LOG_DIR}/${name}.log"

  cleanup_stale_pid_file "${pid_file}"

  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}")"
    if [[ -n "${pid}" ]] && is_pid_running "${pid}"; then
      echo "${name} already running (pid=${pid})"
      return
    fi
  fi

  echo "starting ${name} ..."
  : > "${log_file}"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >"${log_file}" 2>&1 < /dev/null &
  else
    nohup "$@" >"${log_file}" 2>&1 < /dev/null &
  fi
  local new_pid=$!
  echo "${new_pid}" >"${pid_file}"
  echo "${name} started (pid=${new_pid})"

  sleep 0.2
  if ! is_pid_running "${new_pid}"; then
    echo "${name} failed to stay alive, check ${log_file}" >&2
    return 1
  fi
}

start_server_supervisor() {
  local wrapper_pid_file="${PID_DIR}/restart_wrapper.pid"
  local server_pid_file="${PID_DIR}/server.pid"
  local log_file="${LOG_DIR}/server.log"

  cleanup_stale_pid_file "${wrapper_pid_file}"
  cleanup_stale_pid_file "${server_pid_file}"

  if [[ -f "${wrapper_pid_file}" ]]; then
    local pid
    pid="$(cat "${wrapper_pid_file}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && is_pid_running "${pid}"; then
      echo "server supervisor already running (pid=${pid})"
      return
    fi
  fi

  echo "starting server supervisor ..."
  : > "${log_file}"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid env BRIDGE_SKIP_WRAPPER_AUTOSTART=1 "${BRIDGE_DIR}/restart_wrapper.sh" >"${log_file}" 2>&1 < /dev/null &
  else
    nohup env BRIDGE_SKIP_WRAPPER_AUTOSTART=1 "${BRIDGE_DIR}/restart_wrapper.sh" >"${log_file}" 2>&1 < /dev/null &
  fi
  local new_pid=$!
  echo "${new_pid}" > "${wrapper_pid_file}"
  echo "server supervisor started (pid=${new_pid})"

  sleep 0.2
  if ! is_pid_running "${new_pid}"; then
    echo "server supervisor failed to stay alive, check ${log_file}" >&2
    return 1
  fi
}

if ! curl -fsS "${SERVER_URL}/status" >/dev/null 2>&1; then
  wrapper_pid_file="${PID_DIR}/restart_wrapper.pid"
  cleanup_stale_pid_file "${wrapper_pid_file}"
  if [[ -f "${wrapper_pid_file}" ]]; then
    existing_pid="$(cat "${wrapper_pid_file}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && is_pid_running "${existing_pid}"; then
      echo "restart wrapper pid ${existing_pid} is alive but endpoint is down; restarting wrapper"
      : > "${WRAPPER_STOP_MARKER}"
      stop_pid_hard "${existing_pid}"
      rm -f "${wrapper_pid_file}"
    fi
  fi
  start_server_supervisor
  wait_for_stable_server 240 0.5 3 "${SERVER_CONFIGURE_UPTIME}" || true
fi

if ! wait_for_stable_server 240 0.5 3 "${SERVER_CONFIGURE_UPTIME}"; then
  echo "server failed to start, check ${LOG_DIR}/server.log" >&2
  tail -n 40 "${LOG_DIR}/server.log" 2>/dev/null || true
  exit 1
fi

ensure_bridge_user_token

# Capability Library: rebuild if stale (>24h) or missing
CAP_LIB="${BRIDGE_PROJECT_ROOT}/config/capability_library.json"
CAP_BUILDER="${SCRIPT_DIR}/build_capability_library.py"
if [ -f "${CAP_BUILDER}" ]; then
  if [ ! -f "${CAP_LIB}" ] || [ "$(find "${CAP_LIB}" -mmin +1440 2>/dev/null)" ]; then
    echo "[start_platform] Rebuilding capability library (stale or missing)..."
    python3 "${CAP_BUILDER}" --output "${CAP_LIB}" 2>&1 | tail -5 || echo "[start_platform] WARNING: capability library build failed (non-fatal)"
  else
    echo "[start_platform] Capability library is fresh, skipping rebuild."
  fi
fi

resolve_forwarder_session() {
  if [[ -n "${FORWARDER_SESSION:-}" ]]; then
    printf '%s' "${FORWARDER_SESSION}"
    return 0
  fi

  python3 - "${BRIDGE_DIR}/team.json" <<'PY'
import json
import sys
from pathlib import Path


def _session_for(agent_id: str) -> str:
    return f"acw_{agent_id.strip()}"


def _aliases(agent: dict) -> set[str]:
    values = set()
    for raw in agent.get("aliases", []):
        alias = str(raw).strip().lower()
        if alias:
            values.add(alias)
    return values


team_path = Path(sys.argv[1])
fallback = "acw_manager"

try:
    payload = json.loads(team_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print(fallback, end="")
    raise SystemExit(0)

agents = payload.get("agents", [])

# Collect ALL active agents with auto_start (or manager/level<=1)
sessions = []
for agent in agents:
    if not bool(agent.get("active", False)):
        continue
    agent_id = str(agent.get("id", "")).strip()
    if not agent_id or agent_id == "user":
        continue
    auto_start = bool(agent.get("auto_start", False))
    role = str(agent.get("role", "")).strip().lower()
    aliases = _aliases(agent)
    is_manager = role == "manager" or {"manager", "projektleiter", "teamlead"} & aliases
    level = agent.get("level", 99)
    try:
        level_value = int(level)
    except (TypeError, ValueError):
        level_value = 99
    if auto_start or is_manager or level_value <= 1:
        sessions.append(_session_for(agent_id))

if sessions:
    print(",".join(sessions), end="")
else:
    print(fallback, end="")
PY
}

kickoff=""
if [[ "${FORCE_KICKOFF_ON_START:-0}" == "1" || ! -s "${MESSAGE_LOG}" ]]; then
  if [[ -f "${ROOT_DIR}/Auftrag.md" ]]; then
    kickoff="$(cat "${ROOT_DIR}/Auftrag.md")"
  fi
fi

export SERVER_URL PAIR_MODE AGENT_A_ENGINE AGENT_B_ENGINE PROJECT_PATH ALLOW_PEER_AUTO PEER_AUTO_REQUIRE_FLAG
export MAX_PEER_HOPS MAX_TURNS PROCESS_ALL KEEP_HISTORY TIMEOUT RUNTIME_CONFIGURE_HTTP_TIMEOUT
export RUNTIME_CONFIGURE_STABILIZE_SECONDS kickoff BRIDGE_DIR

configure_runtime_once() {
python3 - <<'PY'
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.environ["BRIDGE_DIR"])
from start_platform_runtime import build_runtime_configure_payload

server_url = os.environ["SERVER_URL"].rstrip("/")
pair_mode = os.environ["PAIR_MODE"]
agent_a_engine = os.environ.get("AGENT_A_ENGINE", "").strip().lower()
agent_b_engine = os.environ.get("AGENT_B_ENGINE", "").strip().lower()
project_path = os.environ["PROJECT_PATH"]
http_timeout = float(os.environ.get("RUNTIME_CONFIGURE_HTTP_TIMEOUT", "90"))
stabilize_seconds = max(float(os.environ.get("RUNTIME_CONFIGURE_STABILIZE_SECONDS", "30")), 0.0)
user_token = os.environ.get("BRIDGE_USER_TOKEN", "").strip()

def to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

payload = build_runtime_configure_payload(
    team_path=os.path.join(os.environ["BRIDGE_DIR"], "team.json"),
    pair_mode=pair_mode,
    agent_a_engine=agent_a_engine,
    agent_b_engine=agent_b_engine,
    project_path=project_path,
    allow_peer_auto=to_bool(os.environ.get("ALLOW_PEER_AUTO", "0")),
    peer_auto_require_flag=to_bool(os.environ.get("PEER_AUTO_REQUIRE_FLAG", "1")),
    max_peer_hops=int(os.environ.get("MAX_PEER_HOPS", "20")),
    max_turns=int(os.environ.get("MAX_TURNS", "0")),
    process_all=to_bool(os.environ.get("PROCESS_ALL", "0")),
    keep_history=to_bool(os.environ.get("KEEP_HISTORY", "0")),
    timeout=int(os.environ.get("TIMEOUT", "90")),
    stabilize_seconds=stabilize_seconds,
)

kickoff = os.environ.get("kickoff", "").strip()
if kickoff:
    payload["kickoff"] = kickoff
    payload["kickoff_from"] = "codex"

req = urllib.request.Request(
    f"{server_url}/runtime/configure",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        **({"X-Bridge-Token": user_token} if user_token else {}),
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=http_timeout) as resp:
        body = resp.read().decode("utf-8")
except Exception as exc:  # noqa: BLE001
    print(f"runtime configure failed: {exc}", file=sys.stderr)
    sys.exit(1)

print(body)
PY
}

configured=0
for attempt in 1 2 3; do
  configure_runtime_once || true
  if wait_for_configured_runtime 40 0.25; then
    configured=1
    break
  fi
  echo "runtime configure attempt ${attempt} did not produce configured runtime, retrying ..." >&2
  curl -fsS "${SERVER_URL}/runtime" >&2 || true
  wait_for_stable_server 240 0.5 3 "${SERVER_CONFIGURE_UPTIME}" || true
  sleep 1
done

if [[ "${configured}" != "1" ]]; then
  echo "runtime configure failed after retries" >&2
  exit 1
fi

if ! wait_for_configured_runtime 20 0.25; then
  echo "runtime endpoint is not configured after configure" >&2
  curl -fsS "${SERVER_URL}/runtime" >&2 || true
  tail -n 40 "${LOG_DIR}/server.log" 2>/dev/null || true
  exit 1
fi

ensure_local_n8n_runtime

echo

# --- Watcher (bridge_watcher.py) ---
# Watcher MUST start before agents (monitors context, coordinates agents)
start_process watcher python3 -u "${BRIDGE_DIR}/bridge_watcher.py"
sleep 1
if ! is_pid_running "$(cat "${PID_DIR}/watcher.pid" 2>/dev/null)"; then
  echo "WATCHER FAILED - keine Agents ohne Watcher" >&2
  exit 1
fi

# --- Output Forwarder (captures manager terminal output -> Bridge UI) ---
FORWARDER_SESSION="$(resolve_forwarder_session)"
if tmux has-session -t "${FORWARDER_SESSION}" 2>/dev/null; then
  start_process output_forwarder env FORWARDER_SESSION="${FORWARDER_SESSION}" python3 -u "${BRIDGE_DIR}/output_forwarder.py"
else
  echo "output_forwarder skipped (no ${FORWARDER_SESSION} session)"
fi

# --- WhatsApp Watcher (whatsapp_watcher.py) ---
WHATSAPP_SESSION="whatsapp_watcher"
if [[ -f "${BRIDGE_DIR}/whatsapp_watcher.py" ]]; then
  if tmux has-session -t "${WHATSAPP_SESSION}" 2>/dev/null; then
    echo "whatsapp_watcher already running (tmux session: ${WHATSAPP_SESSION})"
  else
    whatsapp_preflight="$(whatsapp_watcher_preflight)"
    case "${whatsapp_preflight}" in
      ready::*)
        echo "starting whatsapp watcher ..."
        tmux new-session -d -s "${WHATSAPP_SESSION}" "cd ${BRIDGE_DIR} && python3 -u whatsapp_watcher.py 2>&1 | tee -a logs/whatsapp_watcher.log"
        echo "whatsapp_watcher started (tmux session: ${WHATSAPP_SESSION})"
        ;;
      missing_db::*)
        echo "whatsapp_watcher skipped (db missing: ${whatsapp_preflight#missing_db::})"
        ;;
      missing_group::*)
        echo "whatsapp_watcher skipped (group missing: ${whatsapp_preflight#missing_group::})"
        ;;
      *)
        echo "whatsapp_watcher skipped (preflight failed: ${whatsapp_preflight})"
        ;;
    esac
  fi
else
  echo "whatsapp_watcher skipped (whatsapp_watcher.py not found)"
fi

# --- Telegram Watcher (telegram_watcher.py) ---
TELEGRAM_SESSION="telegram_watcher"
if [[ -f "${BRIDGE_DIR}/telegram_watcher.py" ]]; then
  if tmux has-session -t "${TELEGRAM_SESSION}" 2>/dev/null; then
    echo "telegram_watcher already running (tmux session: ${TELEGRAM_SESSION})"
  else
    telegram_preflight="$(telegram_watcher_preflight)"
    case "${telegram_preflight}" in
      ready::*)
        echo "starting telegram watcher ..."
        tmux new-session -d -s "${TELEGRAM_SESSION}" "cd ${BRIDGE_DIR} && python3 -u telegram_watcher.py 2>&1 | tee -a logs/telegram_watcher.log"
        echo "telegram_watcher started (tmux session: ${TELEGRAM_SESSION})"
        ;;
      missing_token::*)
        echo "telegram_watcher skipped (token missing: ${telegram_preflight#missing_token::})"
        ;;
      missing_watch_chats::*)
        echo "telegram_watcher skipped (watch chats missing: ${telegram_preflight#missing_watch_chats::})"
        ;;
      *)
        echo "telegram_watcher skipped (preflight failed: ${telegram_preflight})"
        ;;
    esac
  fi
else
  echo "telegram_watcher skipped (telegram_watcher.py not found)"
fi

# --- Auto-Agent-Start (from team.json via start_agents.py) ---
AUTO_START_AGENTS="${AUTO_START_AGENTS:-1}"
AUTO_START_DEGRADED=0
if [[ "${AUTO_START_AGENTS}" == "1" && -f "${BRIDGE_DIR}/start_agents.py" ]]; then
  echo "starting agents from team.json (active=true, auto_start=true) ..."
  if ! python3 -u "${BRIDGE_DIR}/start_agents.py" 2>&1 | tee -a "${LOG_DIR}/start_agents.log"; then
    echo "agent auto-start degraded, check ${LOG_DIR}/start_agents.log" >&2
    AUTO_START_DEGRADED=1
  fi
else
  echo "auto-start agents disabled (set AUTO_START_AGENTS=1 to enable)"
fi

# --- UI Server (port 8787) --- DISABLED
# UI is served by the Bridge server on port 9111 with token injection.
# A separate HTTP server on 8787 cannot inject auth tokens, causing 401 errors
# on all API calls. Users must access the UI via http://127.0.0.1:9111/
echo "UI served by Bridge server on ${SERVER_URL}/ (no separate UI server needed)"

echo "Platform is running."
echo "Status: ${SERVER_URL}/status"
echo "Runtime: ${SERVER_URL}/runtime"
echo "UI: ${SERVER_URL}/"
echo "Pair mode: ${PAIR_MODE}"
if [[ -n "${AGENT_A_ENGINE}" || -n "${AGENT_B_ENGINE}" ]]; then
  echo "Agent A/B engines: ${AGENT_A_ENGINE:-auto}/${AGENT_B_ENGINE:-auto}"
fi
if [[ "${AUTO_START_DEGRADED}" == "1" ]]; then
  echo "Agent auto-start: degraded"
fi
echo "Project path: ${PROJECT_PATH}"
echo "Peer auto: ${ALLOW_PEER_AUTO}"
echo "Logs: ${LOG_DIR}"
