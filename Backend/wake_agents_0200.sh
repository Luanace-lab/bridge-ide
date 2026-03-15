#!/usr/bin/env bash
set -euo pipefail

BRIDGE_URL="${BRIDGE_URL:-http://127.0.0.1:9111}"
AGENTS_CONF="${AGENTS_CONF:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agents.conf}"
LOG_FILE="${LOG_FILE:-/tmp/bridge_wake_0200.log}"
LOCK_FILE="${LOCK_FILE:-/tmp/bridge_wake_0200.lock}"

TARGET_DATE="${1:-}"
CRON_MARKER="${2:-}"
RUN_MODE="${3:-wake}"

exec >>"$LOG_FILE" 2>&1
echo "[$(date -Is)] wake_agents_0200 start"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Is)] another wake run is already active; exit"
  exit 0
fi

if [[ -n "$TARGET_DATE" && "$(date +%F)" != "$TARGET_DATE" ]]; then
  echo "[$(date -Is)] date guard mismatch (today=$(date +%F), target=$TARGET_DATE); skip"
  exit 0
fi

if [[ "$RUN_MODE" != "wake" && "$RUN_MODE" != "verify" ]]; then
  echo "[$(date -Is)] invalid run mode: $RUN_MODE (expected: wake|verify)"
  exit 1
fi

post_json() {
  local url="$1"
  local payload="$2"
  local out
  if out="$(curl -fsS --max-time 12 --retry 2 --retry-delay 2 \
    -H "Content-Type: application/json" \
    -X POST "$url" \
    -d "$payload" 2>&1)"; then
    echo "[$(date -Is)] POST $url ok: $out"
    return 0
  fi
  echo "[$(date -Is)] POST $url failed: $out"
  return 1
}

send_bridge_message() {
  local recipient="$1"
  local content="$2"
  local payload
  payload=$(printf '{"from":"system","to":"%s","content":"%s"}' \
    "$recipient" "$(printf '%s' "$content" | sed 's/\\/\\\\/g; s/"/\\"/g')")
  post_json "$BRIDGE_URL/send" "$payload" || true
}

start_agent() {
  local agent_id="$1"
  local payload
  payload=$(printf '{"from":"system"}')
  post_json "$BRIDGE_URL/agents/$agent_id/start" "$payload" || true
}

extract_status_summary() {
  local snapshot_file="$1"
  python3 - "$snapshot_file" <<'PY'
import json
import sys

path = sys.argv[1]
targets = ["ordo", "viktor", "nova", "frontend", "codex", "backend", "security", "lucy", "stellexa"]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    print("status_parse_failed")
    raise SystemExit(0)

status = {a.get("agent_id", ""): a.get("status", "unknown") for a in data.get("agents", [])}
parts = [f"{t}={status.get(t, 'not_registered')}" for t in targets]
print(", ".join(parts))
PY
}

is_agent_running() {
  local snapshot_file="$1"
  local agent_id="$2"
  python3 - "$snapshot_file" "$agent_id" <<'PY'
import json
import sys

path, aid = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    raise SystemExit(1)

for agent in data.get("agents", []):
    if agent.get("agent_id") == aid and agent.get("status") == "running":
        raise SystemExit(0)

raise SystemExit(1)
PY
}

collect_targets() {
  awk -F: '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    NF >= 1 { gsub(/[[:space:]]+/, "", $1); if ($1 != "") print $1 }
  ' "$AGENTS_CONF"
}

declare -A target_map=()
while IFS= read -r agent; do
  [[ -n "$agent" ]] && target_map["$agent"]=1
done < <(collect_targets)

# Explicitly include known agents that may be temporarily unregistered.
# NOTE: codex is intentionally excluded from auto-start to avoid spawning a second codex session.
for extra in backend security lucy stellexa; do
  target_map["$extra"]=1
done
target_map["codex"]=1

if [[ "$RUN_MODE" == "wake" ]]; then
  wake_text="02:00 Berlin-Wakeup: Bitte sofort registrieren (bridge_register), dann bridge_receive() aufrufen und alle aufgestauten Nachrichten abarbeiten. Danach kurz Status an Leo melden."

  precheck_ok=0
  if curl -fsS --max-time 8 "$BRIDGE_URL/agents" >/tmp/bridge_agents_0200_precheck.json 2>/tmp/bridge_agents_0200_precheck.err; then
    precheck_ok=1
    echo "[$(date -Is)] precheck snapshot saved: /tmp/bridge_agents_0200_precheck.json"
  else
    echo "[$(date -Is)] precheck snapshot failed: $(cat /tmp/bridge_agents_0200_precheck.err 2>/dev/null || true)"
  fi

  for agent in "${!target_map[@]}"; do
    if [[ "$precheck_ok" -eq 1 ]] && is_agent_running /tmp/bridge_agents_0200_precheck.json "$agent"; then
      echo "[$(date -Is)] skip start (already running): $agent"
      continue
    fi
    start_agent "$agent"
  done

  send_bridge_message "all" "$wake_text"
  for agent in "${!target_map[@]}"; do
    send_bridge_message "$agent" "$wake_text"
  done

  send_bridge_message "viktor" "02:00 Berlin-Wakeup Auftrag von Leo: Mit Codex sofort Systemhaertung starten und unabhaengig verifizieren. Erst backlog lesen (bridge_receive), dann harte Fixes umsetzen und Status berichten. Handover priorisiert: IDs #10977 und #10983 lesen."
  send_bridge_message "codex" "02:00 Berlin-Wakeup Pflichtauftrag von Leo an DICH persoenlich: In DEINER bestehenden tmux-Session als agent_id=codex arbeiten, via MCP bridge_register + bridge_receive ausfuehren, dann nahtlos mit Viktor Systemhaertung treiben. Keine zweite codex-Session starten. Pflichtlese-Handover: IDs #10977 und #10983."
  send_bridge_message "ordo" "02:00 Berlin-Wakeup Koordination: Bitte Agenten-Status pruefen, offene Nachrichten flushen und Engpaesse sofort eskalieren."

  if curl -fsS --max-time 8 "$BRIDGE_URL/agents" >/tmp/bridge_agents_0200_snapshot.json 2>/tmp/bridge_agents_0200_snapshot.err; then
    echo "[$(date -Is)] agents snapshot saved: /tmp/bridge_agents_0200_snapshot.json"
    summary="$(extract_status_summary /tmp/bridge_agents_0200_snapshot.json)"
    send_bridge_message "user" "02:00 Status-Snapshot: $summary"
  else
    echo "[$(date -Is)] failed to fetch /agents snapshot: $(cat /tmp/bridge_agents_0200_snapshot.err 2>/dev/null || true)"
  fi
fi

if [[ "$RUN_MODE" == "verify" ]]; then
  if curl -fsS --max-time 8 "$BRIDGE_URL/agents" >/tmp/bridge_agents_0203_verify_pre.json 2>/tmp/bridge_agents_0203_verify_pre.err; then
    verify_summary="$(extract_status_summary /tmp/bridge_agents_0203_verify_pre.json)"
    send_bridge_message "user" "02:03 Verifikation: $verify_summary"

    restarted=()
    for agent in "${!target_map[@]}"; do
      if ! is_agent_running /tmp/bridge_agents_0203_verify_pre.json "$agent"; then
        start_agent "$agent"
        restarted+=("$agent")
      fi
    done

    if [[ "${#restarted[@]}" -gt 0 ]]; then
      send_bridge_message "user" "02:03 Aktion: bei Bedarf nachgestartet: ${restarted[*]}"
      sleep 20
      if curl -fsS --max-time 8 "$BRIDGE_URL/agents" >/tmp/bridge_agents_0203_verify_post.json 2>/tmp/bridge_agents_0203_verify_post.err; then
        post_summary="$(extract_status_summary /tmp/bridge_agents_0203_verify_post.json)"
        send_bridge_message "user" "02:03:20 Post-Check: $post_summary"
      fi
    else
      send_bridge_message "user" "02:03 Aktion: keine Nachstarts noetig."
    fi

    if ! is_agent_running /tmp/bridge_agents_0203_verify_pre.json viktor; then
      send_bridge_message "ordo" "ALERT 02:03: viktor war nicht running. Bitte sofort nachfassen."
    fi
    if ! is_agent_running /tmp/bridge_agents_0203_verify_pre.json codex; then
      send_bridge_message "viktor" "Hinweis 02:03: codex war nicht running. Bitte direkten Bridge-Kontakt nutzen und Handover #10977/#10983 aktiv nachziehen."
    fi
  else
    echo "[$(date -Is)] failed to fetch verify precheck: $(cat /tmp/bridge_agents_0203_verify_pre.err 2>/dev/null || true)"
  fi
fi

if [[ -n "$CRON_MARKER" ]]; then
  tmp_cron="$(mktemp)"
  crontab -l 2>/dev/null | grep -Fv "$CRON_MARKER" >"$tmp_cron" || true
  crontab "$tmp_cron"
  rm -f "$tmp_cron"
  echo "[$(date -Is)] removed one-shot cron marker: $CRON_MARKER"
fi

echo "[$(date -Is)] wake_agents_0200 done"
