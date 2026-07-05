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

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

BACKEND_PORT="${INTERNPATH_BACKEND_PORT:-${PORT:-8787}}"
AI_PORT="${INTERNPATH_AI_PORT:-8000}"
RQ_QUEUE_NAME="${RQ_QUEUE_NAME:-internpath-default}"

if [ -z "${DATABASE_URL:-}" ]; then
    echo "Error: DATABASE_URL is required. InternPath runs on PostgreSQL + pgvector only."
    exit 1
fi

if [ -z "${REDIS_URL:-}" ]; then
    echo "Error: REDIS_URL is required for Redis/RQ background jobs."
    exit 1
fi

# 1. Detect if running with Docker Compose
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    echo "[Docker Mode Detected]"
    echo "Starting PostgreSQL pgvector and Redis containers..."
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

    if systemctl list-unit-files | grep -q "redis-server.service"; then
        echo "Ensuring Redis service is running..."
        sudo systemctl start redis-server || echo "Warning: Failed to start redis-server service. It might already be running."
    elif systemctl list-unit-files | grep -q "redis.service"; then
        echo "Ensuring Redis service is running..."
        sudo systemctl start redis || echo "Warning: Failed to start redis service. It might already be running."
    fi

    for unit in "${SERVICE_NAME}" "${SERVICE_NAME}-ai" "${SERVICE_NAME}-worker"; do
        if systemctl list-unit-files | grep -q "${unit}.service"; then
            echo "Starting ${unit} service..."
            sudo systemctl start "${unit}"
        fi
    done

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
    echo "  Logs: journalctl -u ${SERVICE_NAME} -u ${SERVICE_NAME}-ai -u ${SERVICE_NAME}-worker -f"
    echo "=============================================="
else
    # 3. Manual Local Linux Run (without systemd)
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

    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q "redis-server.service"; then
        echo "Ensuring local Redis is running..."
        sudo systemctl start redis-server || true
    elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q "redis.service"; then
        echo "Ensuring local Redis is running..."
        sudo systemctl start redis || true
    fi

    source .venv/bin/activate

    echo "Starting AI service natively..."
    pushd ai-service >/dev/null
    nohup python -m uvicorn app.main:app --host 127.0.0.1 --port "$AI_PORT" > ../logs/ai-service.log 2>&1 &
    AI_SERVICE_PID=$!
    popd >/dev/null
    echo $AI_SERVICE_PID > logs/ai-service.pid

    echo "Starting RQ worker for queue '$RQ_QUEUE_NAME'..."
    nohup python -m backend.rq_worker > logs/rq-worker.log 2>&1 &
    WORKER_PID=$!
    echo $WORKER_PID > logs/rq-worker.pid

    echo "Starting FastAPI backend natively..."
    nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" > logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > logs/backend.pid

    echo "=============================================="
    echo "  InternPath started in background."
    echo "  Backend PID: $BACKEND_PID | AI PID: $AI_SERVICE_PID | Worker PID: $WORKER_PID"
    echo "  URL: http://127.0.0.1:$BACKEND_PORT"
    echo "  Logs: tail -f logs/backend.log logs/ai-service.log logs/rq-worker.log"
    echo "=============================================="
fi
