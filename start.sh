#!/bin/bash
# sovereign_guardian.sh
# Self-healing boot loop with hang detection and clean port recovery.

PORT=${SOV_PORT:-8002}
HEALTH_URL="http://127.0.0.1:${PORT}/api/health"

echo "======================================================="
echo "  [SOVEREIGN] Guardian Boot Sequence Initiated"
echo "  Protocol: Kill → Verify → Launch → Watch"
echo "======================================================="

cd "$(dirname "$0")" || exit 1

nuke_port() {
    local pid
    pid=$(ss -tlnp | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | head -1)
    if [ -n "$pid" ]; then
        echo "[GUARDIAN] Force-killing zombie PID ${pid} on port ${PORT}..."
        kill -9 "$pid" 2>/dev/null
    fi
    sleep 1
}

wait_healthy() {
    # Poll health endpoint for up to 10s after spawn
    local attempts=0
    while [ $attempts -lt 20 ]; do
        if curl -sf --max-time 1 "${HEALTH_URL}" > /dev/null 2>&1; then
            echo "[GUARDIAN] Backend healthy ✓"
            return 0
        fi
        sleep 0.5
        attempts=$((attempts + 1))
    done
    echo "[GUARDIAN] Backend failed health check after 10s — killing and restarting."
    return 1
}

watch_health() {
    # Background watchdog: if health endpoint stops responding, kill uvicorn so loop restarts it
    local uvicorn_pid=$1
    while kill -0 "$uvicorn_pid" 2>/dev/null; do
        sleep 20
        if ! curl -sf --max-time 15 "${HEALTH_URL}" > /dev/null 2>&1; then
            echo "[GUARDIAN] !! Health check FAILED — backend hung. Killing PID ${uvicorn_pid}..."
            kill -9 "$uvicorn_pid" 2>/dev/null
            return
        fi
    done
}

while true; do
    nuke_port

    echo "[GUARDIAN] Launching backend on port ${PORT}..."
    python3 -m uvicorn main:app --host 0.0.0.0 --port ${PORT} --reload &
    UVICORN_PID=$!

    # Start background health watchdog
    watch_health $UVICORN_PID &
    WATCHDOG_PID=$!

    # Wait for it to come up healthy
    if ! wait_healthy; then
        kill -9 $UVICORN_PID 2>/dev/null
        kill $WATCHDOG_PID 2>/dev/null
        echo "[GUARDIAN] Retrying in 2s..."
        sleep 2
        continue
    fi

    # Block until uvicorn exits (crashed, killed by watchdog, etc.)
    wait $UVICORN_PID
    EXIT_CODE=$?
    kill $WATCHDOG_PID 2>/dev/null

    echo ""
    echo "[GUARDIAN] !! Backend exited (code: ${EXIT_CODE}) — resurrecting in 2s..."
    echo "======================================================="
    sleep 2
done
