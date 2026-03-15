#!/bin/bash
# restart_wrapper.sh — Server-Loop mit Auto-Restart + Exponential Backoff
#
# Logik: Server wird IMMER neu gestartet (default).
# Stopp NUR bei /tmp/bridge_stop_requested.
# Geplanter Restart via /tmp/bridge_restart_requested (resettet Backoff).
#
# Verwendung: ./restart_wrapper.sh (statt direkt python3 server.py)

STOP_MARKER="/tmp/bridge_stop_requested"
RESTART_MARKER="/tmp/bridge_restart_requested"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"
LOG_FILE="$SCRIPT_DIR/logs/restart_wrapper.log"
WRAPPER_PID_FILE="$SCRIPT_DIR/pids/restart_wrapper.pid"
PORT=9111
SKIP_AUTOSTART="${BRIDGE_SKIP_WRAPPER_AUTOSTART:-0}"
WAKE_ON_START=0

# Backoff state
BACKOFF=2
MAX_BACKOFF=30
STABLE_THRESHOLD=60  # seconds — if server ran longer than this, reset backoff
CRASH_COUNT=0
MAX_CRASHES=10  # safety net — exit after this many consecutive fast crashes

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$WRAPPER_PID_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

_release_pid_lock() {
    if [ -f "$WRAPPER_PID_FILE" ]; then
        local stored_pid
        stored_pid="$(cat "$WRAPPER_PID_FILE" 2>/dev/null || true)"
        if [ "$stored_pid" = "$$" ]; then
            rm -f "$WRAPPER_PID_FILE"
        fi
    fi
}

_acquire_pid_lock() {
    if [ -f "$WRAPPER_PID_FILE" ]; then
        local old_pid
        old_pid="$(cat "$WRAPPER_PID_FILE" 2>/dev/null || true)"
        if [ -n "$old_pid" ] && [ "$old_pid" != "$$" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
            log "Another restart wrapper is already running (pid=$old_pid). Exiting."
            exit 1
        fi
        rm -f "$WRAPPER_PID_FILE"
    fi
    echo "$$" > "$WRAPPER_PID_FILE"
}

wait_for_port_free() {
    local max_wait=30
    for i in $(seq 1 "$max_wait"); do
        if ! ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
            return 0
        fi
        if [ "$i" -eq "$max_wait" ]; then
            log "Port $PORT still occupied after ${max_wait}s. Killing old process..."
            fuser -k "${PORT}/tcp" 2>/dev/null || true
            sleep 1
        fi
        sleep 1
    done
}

# Clean up stale markers on start
rm -f "$STOP_MARKER"
_acquire_pid_lock

# SIGTERM/SIGINT: Forward to server child, do NOT exit wrapper.
# Wrapper stays alive and restarts the server.
SERVER_PID=""
SERVER_EXIT_CODE=0
_should_forward_signal() {
    if [ "$SKIP_AUTOSTART" != "1" ]; then
        return 0
    fi
    if [ -f "$STOP_MARKER" ] || [ -f "$RESTART_MARKER" ]; then
        return 0
    fi
    return 1
}

wait_for_server_exit() {
    while true; do
        wait "$SERVER_PID"
        SERVER_EXIT_CODE=$?
        if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
            log "Wait for server interrupted, but child is still running (pid=$SERVER_PID). Continuing to wait."
            continue
        fi
        return 0
    done
}

_forward_signal() {
    if ! _should_forward_signal; then
        log "Signal received in external bootstrap mode without stop/restart marker. Ignoring."
        return
    fi
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        log "Signal received. Forwarding SIGTERM to server (pid=$SERVER_PID) ..."
        kill -TERM "$SERVER_PID" 2>/dev/null || true
    else
        log "Signal received but no server child running."
    fi
}
trap '_forward_signal' TERM INT
trap '_release_pid_lock' EXIT

log "Wrapper started. Auto-restart enabled. Stop via: touch $STOP_MARKER"

while true; do
    # Check stop marker BEFORE starting
    if [ -f "$STOP_MARKER" ]; then
        rm -f "$STOP_MARKER"
        log "Stop marker found. Exiting wrapper."
        break
    fi

    # Ensure port is free
    wait_for_port_free

    log "Starting server.py ..."
    START_TIME=$(date +%s)
    env BRIDGE_SERVER_WAKE_ON_START="$WAKE_ON_START" python3 -u "$SERVER" &
    SERVER_PID=$!
    WAKE_ON_START=0
    echo "$SERVER_PID" > "$SCRIPT_DIR/pids/server.pid"

    # Wait for server to be healthy before starting agents
    _healthy=0
    for _i in $(seq 1 60); do
        if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            _healthy=1
            break
        fi
        # Check if server process died
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    if [ "$_healthy" = "1" ]; then
        if [ "$SKIP_AUTOSTART" = "1" ]; then
            log "Server healthy. Wrapper autostart disabled; waiting for external bootstrap."
            wait_for_server_exit
            EXIT_CODE=$SERVER_EXIT_CODE
            END_TIME=$(date +%s)
            RUN_DURATION=$((END_TIME - START_TIME))
            log "Server exited with code $EXIT_CODE (ran for ${RUN_DURATION}s)"
            if [ -f "$STOP_MARKER" ]; then
                rm -f "$STOP_MARKER"
                log "Stop marker found after exit. Exiting wrapper."
                break
            fi
            if [ -f "$RESTART_MARKER" ]; then
                REASON=$(cat "$RESTART_MARKER" 2>/dev/null || echo "unknown")
                rm -f "$RESTART_MARKER"
                log "Planned restart (reason: $REASON). Resetting backoff."
                BACKOFF=2
                WAKE_ON_START=1
                wait_for_port_free
                continue
            fi
            if [ "$RUN_DURATION" -ge "$STABLE_THRESHOLD" ]; then
                BACKOFF=2
                CRASH_COUNT=0
                log "Server was stable (${RUN_DURATION}s). Restarting immediately..."
                WAKE_ON_START=1
            else
                CRASH_COUNT=$((CRASH_COUNT + 1))
                log "Fast crash (${RUN_DURATION}s < ${STABLE_THRESHOLD}s). Backoff: ${BACKOFF}s (crash ${CRASH_COUNT}/${MAX_CRASHES})"
                if [ "$CRASH_COUNT" -ge "$MAX_CRASHES" ]; then
                    log "FATAL: ${MAX_CRASHES} consecutive crashes. Exiting wrapper. Manual intervention required."
                    break
                fi
                sleep "$BACKOFF"
                WAKE_ON_START=1
                BACKOFF=$((BACKOFF * 2))
                if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
                    BACKOFF=$MAX_BACKOFF
                fi
            fi
            continue
        fi
        log "Server healthy. Starting watcher + agents ..."
        # Start watcher if not running
        if [ -f "$SCRIPT_DIR/bridge_watcher.py" ]; then
            _watcher_pid=""
            if [ -f "$SCRIPT_DIR/pids/watcher.pid" ]; then
                _watcher_pid="$(cat "$SCRIPT_DIR/pids/watcher.pid" 2>/dev/null || true)"
            fi
            if [ -z "$_watcher_pid" ] || ! kill -0 "$_watcher_pid" 2>/dev/null; then
                nohup python3 -u "$SCRIPT_DIR/bridge_watcher.py" > "$SCRIPT_DIR/logs/watcher.log" 2>&1 &
                echo "$!" > "$SCRIPT_DIR/pids/watcher.pid"
                log "Watcher started (pid=$!)"
            fi
        fi
        # Auto-start agents from team.json (active=true, auto_start=true)
        if [ -f "$SCRIPT_DIR/start_agents.py" ]; then
            sleep 3  # Give watcher time to initialize
            log "Running start_agents.py (team.json) ..."
            if python3 -u "$SCRIPT_DIR/start_agents.py" >> "$SCRIPT_DIR/logs/start_agents.log" 2>&1; then
                log "Agent auto-start complete."
            else
                log "WARN: start_agents.py failed"
            fi
        fi
    else
        log "Server not healthy after 60s — skipping agent start."
    fi

    # Wait for server process to exit
    wait_for_server_exit
    EXIT_CODE=$SERVER_EXIT_CODE
    END_TIME=$(date +%s)
    RUN_DURATION=$((END_TIME - START_TIME))
    log "Server exited with code $EXIT_CODE (ran for ${RUN_DURATION}s)"

    # Check stop marker AFTER exit
    if [ -f "$STOP_MARKER" ]; then
        rm -f "$STOP_MARKER"
        log "Stop marker found after exit. Exiting wrapper."
        break
    fi

    # Check for planned restart (resets backoff)
    if [ -f "$RESTART_MARKER" ]; then
        REASON=$(cat "$RESTART_MARKER" 2>/dev/null || echo "unknown")
        rm -f "$RESTART_MARKER"
        log "Planned restart (reason: $REASON). Resetting backoff."
        BACKOFF=2
        WAKE_ON_START=1
        wait_for_port_free
        continue
    fi

    # Crash recovery with backoff
    if [ "$RUN_DURATION" -ge "$STABLE_THRESHOLD" ]; then
        # Server ran long enough — reset backoff and crash counter
        BACKOFF=2
        CRASH_COUNT=0
        log "Server was stable (${RUN_DURATION}s). Restarting immediately..."
        WAKE_ON_START=1
    else
        # Fast crash — apply backoff
        CRASH_COUNT=$((CRASH_COUNT + 1))
        log "Fast crash (${RUN_DURATION}s < ${STABLE_THRESHOLD}s). Backoff: ${BACKOFF}s (crash ${CRASH_COUNT}/${MAX_CRASHES})"
        if [ "$CRASH_COUNT" -ge "$MAX_CRASHES" ]; then
            log "FATAL: ${MAX_CRASHES} consecutive crashes. Exiting wrapper. Manual intervention required."
            break
        fi
        sleep "$BACKOFF"
        WAKE_ON_START=1
        # Exponential backoff: 2 -> 4 -> 8 -> 16 -> 30 (capped)
        BACKOFF=$((BACKOFF * 2))
        if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
            BACKOFF=$MAX_BACKOFF
        fi
    fi
done

log "Wrapper exited."
