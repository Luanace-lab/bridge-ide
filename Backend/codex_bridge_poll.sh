#!/bin/bash
# codex_bridge_poll.sh — Persistent bridge_receive polling for Codex agents.
#
# Codex CLI is execution-based: it processes one prompt, then waits at the
# interactive prompt (›). Without this daemon, Codex agents go idle after
# their initial prompt and never check for new bridge messages.
#
# This daemon is the Codex equivalent of Claude Code's stop_hook: it keeps
# the agent in a persistent communication loop.
#
# Usage: codex_bridge_poll.sh <session_name> <poll_interval_seconds> [prompt_regex]

SESSION="$1"
POLL_INTERVAL="${2:-30}"
PROMPT_REGEX="${3:-[>›]}"
INITIAL_WAIT=60  # Wait for initial prompt to complete before starting poll

if [ -z "$SESSION" ]; then
    echo "[codex_poll] ERROR: session is required" >&2
    exit 1
fi

# Wait for the initial prompt to complete
sleep "$INITIAL_WAIT"

echo "[codex_poll] Starting bridge poll for $SESSION (interval=${POLL_INTERVAL}s)" >&2

while true; do
    sleep "$POLL_INTERVAL"

    # Check if session is still alive
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "[codex_poll] Session $SESSION is dead. Exiting." >&2
        exit 0
    fi

    # Check if agent is at the ready prompt (not busy processing)
    LAST_LINE=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -v "^$" | tail -1)
    if ! echo "$LAST_LINE" | grep -Eq "$PROMPT_REGEX"; then
        # Agent is busy — skip this poll cycle
        continue
    fi

    # Inject bridge_receive prompt
    tmux send-keys -t "$SESSION" "Call bridge_receive(). If messages, process and respond. Then call bridge_task_queue(state='acked', agent_id='${SESSION#acw_}', limit=3). If you have acked tasks, CONTINUE working on them. Then call bridge_task_queue(state='created', limit=5). If new tasks match your role, claim and work on them. If no messages and no tasks, do nothing." Enter
done
