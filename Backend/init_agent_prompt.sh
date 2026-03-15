#!/bin/bash
# init_agent_prompt.sh — Wartet bis ein CLI-Agent bereit ist, sendet dann den Initial-Prompt.
#
# Wird von create_agent_session() als detachter Subprocess gestartet.
# Laeuft unabhaengig vom aufrufenden Prozess weiter.
#
# Usage: init_agent_prompt.sh <session_name> <prompt> [max_wait_seconds] [prompt_regex] [enter_count] [engine]

SESSION="$1"
PROMPT="$2"
MAX_WAIT="${3:-30}"
PROMPT_REGEX="${4:->}"
ENTER_COUNT="${5:-2}"
ENGINE="${6:-}"
POLL_INTERVAL=2
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/init_agent_prompt.log"

mkdir -p "${LOG_DIR}"

log_init_prompt() {
    printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "${LOG_FILE}"
}

prompt_regex_matches() {
    local recent_lines="$1"
    RECENT_LINES="$recent_lines" PROMPT_REGEX="$PROMPT_REGEX" python3 - <<'PY'
import re
import os
import sys

pattern = os.environ.get("PROMPT_REGEX", "")
text = os.environ.get("RECENT_LINES", "")
lines = [line for line in text.splitlines() if line.strip()]
try:
    matched = any(re.search(pattern, line) for line in lines)
except re.error:
    matched = False
sys.exit(0 if matched else 1)
PY
}

if [ -z "$SESSION" ] || [ -z "$PROMPT" ]; then
    log_init_prompt "ERROR missing args session='${SESSION}' engine='${ENGINE}'"
    echo "[init_agent_prompt] ERROR: session und prompt sind Pflichtargumente" >&2
    exit 1
fi

SANITIZED_SESSION=$(printf '%s' "$SESSION" | tr -c 'A-Za-z0-9_' '_')
BUFFER_NAME="bridge_init_${SANITIZED_SESSION}_$$"

cleanup() {
    tmux delete-buffer -b "$BUFFER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log_init_prompt "START session='${SESSION}' engine='${ENGINE}' max_wait='${MAX_WAIT}' enter_count='${ENTER_COUNT}'"

# Warte bis der CLI-Prompt sichtbar ist (engine-spezifisch via Regex)
ITERATIONS=$((MAX_WAIT / POLL_INTERVAL))
READY_MATCHED=0
for i in $(seq 1 "$ITERATIONS"); do
    sleep "$POLL_INTERVAL"
    RECENT_LINES=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -v '^$' | tail -12 | sed 's/^[[:space:]│]*//')
    if prompt_regex_matches "$RECENT_LINES"; then
        READY_MATCHED=1
        log_init_prompt "READY session='${SESSION}' matched_regex='${PROMPT_REGEX}' iteration='${i}'"
        break
    fi
done
if [ "${READY_MATCHED}" != "1" ]; then
    log_init_prompt "READY_TIMEOUT session='${SESSION}' regex='${PROMPT_REGEX}'"
fi

# Prompt senden — Buffer-Paste ist fuer TUI-CLIs deutlich robuster als send-keys.
if ! printf '%s' "$PROMPT" | tmux load-buffer -b "$BUFFER_NAME" -; then
    log_init_prompt "ERROR load-buffer failed session='${SESSION}'"
    echo "[init_agent_prompt] ERROR: load-buffer fehlgeschlagen fuer $SESSION" >&2
    exit 1
fi
if ! tmux paste-buffer -b "$BUFFER_NAME" -t "$SESSION"; then
    log_init_prompt "ERROR paste-buffer failed session='${SESSION}'"
    echo "[init_agent_prompt] ERROR: paste-buffer fehlgeschlagen fuer $SESSION" >&2
    exit 1
fi
sleep 0.5
log_init_prompt "PASTED session='${SESSION}'"

# Claude nutzt 2x Enter (TUI-Workaround), Codex 1x Enter (verifiziert).
for i in $(seq 1 "$ENTER_COUNT"); do
    tmux send-keys -t "$SESSION" Enter
    log_init_prompt "ENTER session='${SESSION}' index='${i}'"
    if [ "$i" -lt "$ENTER_COUNT" ]; then
        sleep 2
    fi
done

if [ "$ENGINE" = "gemini" ] || [ "$ENGINE" = "qwen" ]; then
    AUTO_ITERS=$((60 / POLL_INTERVAL))
    for i in $(seq 1 "$AUTO_ITERS"); do
        sleep "$POLL_INTERVAL"
        CAPTURE=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || true)
        if echo "$CAPTURE" | grep -Fq "Bypass confirmation for trusted tools"; then
            tmux send-keys -t "$SESSION" C-y
            log_init_prompt "AUTO_APPROVE session='${SESSION}' type='trusted_tools'"
            sleep 1
            continue
        fi
        if echo "$CAPTURE" | grep -Fq 'Allow execution of MCP tool "' && echo "$CAPTURE" | grep -Fq 'server "bridge"'; then
            tmux send-keys -t "$SESSION" Down
            sleep 0.2
            tmux send-keys -t "$SESSION" Down
            sleep 0.2
            tmux send-keys -t "$SESSION" Enter
            log_init_prompt "AUTO_APPROVE session='${SESSION}' type='bridge_mcp'"
            sleep 1
            continue
        fi
    done
fi

log_init_prompt "DONE session='${SESSION}' engine='${ENGINE}'"
echo "[init_agent_prompt] Prompt gesendet an $SESSION" >&2
