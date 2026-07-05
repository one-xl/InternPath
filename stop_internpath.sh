#!/usr/bin/env bash
# InternPath - One-Click Stop Script for Linux / Cloud Servers

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "      InternPath: Cloud/Linux Stop Script     "
echo "=============================================="

# 1. Stop systemd service if present
SERVICE_NAME="internpath"
if systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then
    echo "[Systemd Service Mode Detected]"
    for unit in "${SERVICE_NAME}-worker" "${SERVICE_NAME}-ai" "${SERVICE_NAME}"; do
        if systemctl list-unit-files | grep -q "${unit}.service"; then
            echo "Stopping ${unit} service..."
            sudo systemctl stop "${unit}"
        fi
    done
fi

# 2. Stop manual running background process if PID file exists
stop_pid_file() {
    local pid_file="$1"
    local label="$2"
    if [ ! -f "$pid_file" ]; then
        return
    fi
    PID=$(cat "$pid_file")
    if kill -0 $PID 2>/dev/null; then
        echo "[Manual Running Process Detected]"
        echo "Stopping $label process (PID: $PID)..."
        kill $PID
        rm "$pid_file"
        echo "Process stopped."
    else
        rm "$pid_file"
    fi
}

stop_pid_file "logs/rq-worker.pid" "RQ worker"
stop_pid_file "logs/backend.pid" "FastAPI backend"
stop_pid_file "logs/ai-service.pid" "AI service"

# 3. Stop Docker Compose if active
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    echo "[Docker Mode Detected]"
    echo "Stopping Docker containers..."
    docker compose down
fi

echo "=============================================="
echo "  InternPath stopped successfully!"
echo "=============================================="
