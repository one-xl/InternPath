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
    echo "Stopping ${SERVICE_NAME} service..."
    sudo systemctl stop "${SERVICE_NAME}"
    echo "Service ${SERVICE_NAME} stopped."
fi

# 2. Stop manual running background process if PID file exists
if [ -f "logs/backend.pid" ]; then
    PID=$(cat logs/backend.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "[Manual Running Process Detected]"
        echo "Stopping background FastAPI process (PID: $PID)..."
        kill $PID
        rm logs/backend.pid
        echo "Process stopped."
    else
        rm logs/backend.pid
    fi
fi

# 3. Stop Docker Compose if active
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    echo "[Docker Mode Detected]"
    echo "Stopping Docker containers..."
    docker compose down
fi

echo "=============================================="
echo "  InternPath stopped successfully!"
echo "=============================================="
