#!/bin/bash
# Start Chrome with CDP (Chrome DevTools Protocol) enabled
# Agents can then connect via bridge_cdp_connect()
#
# Usage: ./start_chrome_cdp.sh [port] [--force]
# Default port: 9222
# --force: kill all Chrome processes and restart

PORT="${1:-9222}"
FORCE="${2:-}"

# Check if Chrome is already running with CDP
if curl -s --connect-timeout 1 "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
    echo "Chrome CDP already running on port $PORT"
    curl -s "http://localhost:$PORT/json/version" | python3 -m json.tool
    exit 0
fi

# Check if Chrome is running without CDP
if pgrep -x chrome > /dev/null 2>&1; then
    if [ "$FORCE" = "--force" ]; then
        echo "Force-killing all Chrome processes..."
        pkill -9 -x chrome 2>/dev/null
        pkill -9 -f chrome_crashpad 2>/dev/null
        # Wait until all Chrome processes are gone
        for i in $(seq 1 10); do
            if ! pgrep -x chrome > /dev/null 2>&1; then
                echo "All Chrome processes terminated."
                break
            fi
            sleep 1
        done
        if pgrep -x chrome > /dev/null 2>&1; then
            echo "ERROR: Could not kill all Chrome processes."
            exit 1
        fi
    else
        echo "WARNING: Chrome is running WITHOUT CDP flag."
        echo ""
        echo "Options:"
        echo "  1. Run: ./start_chrome_cdp.sh $PORT --force"
        echo "     (kills Chrome and restarts with CDP)"
        echo "  2. Close Chrome manually, then run this script again."
        exit 1
    fi
fi

# Start Chrome with CDP
echo "Starting Chrome with CDP on port $PORT..."
nohup google-chrome \
    --remote-debugging-port="$PORT" \
    --set-remote-debugging-enabled \
    --no-first-run \
    --restore-last-session \
    > /dev/null 2>&1 &
CHROME_PID=$!
echo "Chrome started with PID $CHROME_PID"

# Wait for CDP to be ready
for i in $(seq 1 15); do
    if curl -s --connect-timeout 1 "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
        echo "CDP ready on port $PORT"
        curl -s "http://localhost:$PORT/json/version" | python3 -m json.tool
        exit 0
    fi
    sleep 1
done

echo "ERROR: CDP port $PORT not responding after 15s."
echo "Check: ss -tlnp | grep $PORT"
