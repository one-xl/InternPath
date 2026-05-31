#!/usr/bin/env bash
# InternPath - One-Click Start Script for Linux / Cloud Servers

set -e

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "      InternPath: Cloud/Linux Start Script    "
echo "=============================================="

# Make sure logs directory exists
mkdir -p logs

# 1. Detect if running with Docker Compose
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    echo "[Docker Mode Detected]"
    echo "Starting PostgreSQL pgvector container..."
    docker compose up -d
fi

# 2. Handle native systemd service deployment
SERVICE_NAME="internpath"
if systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then
    echo "[Systemd Service Mode Detected]"
    
    # Ensure postgresql is started
    if systemctl list-unit-files | grep -q "postgresql.service"; then
        echo "Ensuring PostgreSQL service is running..."
        sudo systemctl start postgresql || echo "Warning: Failed to start postgresql service. It might already be running."
    fi

    echo "Starting ${SERVICE_NAME} service..."
    sudo systemctl start "${SERVICE_NAME}"
    
    echo "Checking service status..."
    sudo systemctl status "${SERVICE_NAME}" --no-pager
    
    # Get active port from service configuration or environment file
    PORT=8502
    if [ -f "/etc/internpath/app.env" ]; then
        ENV_PORT=$(grep -E "^PORT=" /etc/internpath/app.env | cut -d'=' -f2 || echo "")
        if [ ! -z "$ENV_PORT" ]; then
            PORT=$ENV_PORT
        fi
    fi
    
    echo "=============================================="
    echo "  InternPath started successfully!"
    echo "  URL: http://<your-server-ip>:$PORT"
    echo "  Logs: journalctl -u ${SERVICE_NAME} -f"
    echo "=============================================="
else
    # 3. Fallback: Manual Local Linux Run (without systemd)
    echo "[Manual Running Mode Detected]"
    if [ ! -d ".venv" ]; then
        echo "Error: Virtual environment (.venv) not found. Please run deploy/server_install.sh first."
        exit 1
    fi
    
    # Start PostgreSQL if installed natively and systemctl is available
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q "postgresql.service"; then
        echo "Ensuring local PostgreSQL is running..."
        sudo systemctl start postgresql || true
    fi

    # Read port from .env if exists
    PORT=8502
    if [ -f ".env" ]; then
        ENV_PORT=$(grep -E "^PORT=" .env | cut -d'=' -f2 || echo "")
        if [ ! -z "$ENV_PORT" ]; then
            PORT=$ENV_PORT
        fi
    fi

    echo "Starting FastAPI backend natively..."
    source .venv/bin/activate
    nohup uvicorn backend.main:app --host 0.0.0.0 --port $PORT > logs/backend.log 2>&1 &
    PID=$!
    echo $PID > logs/backend.pid
    
    echo "=============================================="
    echo "  InternPath started in background (PID: $PID)!"
    echo "  URL: http://127.0.0.1:$PORT"
    echo "  Logs: tail -f logs/backend.log"
    echo "=============================================="
fi
