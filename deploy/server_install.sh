#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/internpath}"
APP_PORT="${APP_PORT:-8502}"
AI_PORT="${AI_PORT:-8000}"
SERVICE_NAME="${SERVICE_NAME:-internpath}"
APP_USER="${APP_USER:-internpath}"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$APP_DIR/requirements.server.txt}"
APP_ENV_FILE="${APP_ENV_FILE:-$APP_DIR/.env}"
PERSISTENT_ENV_DIR="${PERSISTENT_ENV_DIR:-/etc/internpath}"
PERSISTENT_ENV_FILE="${PERSISTENT_ENV_FILE:-$PERSISTENT_ENV_DIR/app.env}"

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "Requirements file not found: $REQUIREMENTS_FILE"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y python3 python3-venv python3-pip wget curl redis-server
apt-get install -y libreoffice-writer poppler-utils fontconfig fonts-noto-cjk

echo "Checking DOCX visual audit runtime dependencies..."
if command -v soffice >/dev/null 2>&1; then
  echo "LibreOffice detected: $(command -v soffice)"
elif command -v libreoffice >/dev/null 2>&1; then
  echo "LibreOffice detected: $(command -v libreoffice)"
else
  echo "Warning: LibreOffice was not detected. DOCX visual audit will be skipped, but DOCX template structure guard still works."
fi
if command -v pdftoppm >/dev/null 2>&1; then
  echo "Poppler pdftoppm detected: $(command -v pdftoppm)"
else
  echo "Warning: Poppler pdftoppm was not detected. DOCX visual audit will be skipped, but DOCX template structure guard still works."
fi

# PostgreSQL & pgvector automatic installation on cloud server
if command -v apt-get >/dev/null 2>&1; then
  echo "=========================================================="
  echo "  Cloud Server: Installing PostgreSQL & pgvector Extension"
  echo "=========================================================="

  # 1. Install PostgreSQL if not present (defaulting to PostgreSQL 16)
  if ! command -v psql >/dev/null 2>&1; then
    echo "PostgreSQL is not installed. Importing PostgreSQL APT repository..."
    # Import repo
    lsb_dist=$(lsb_release -cs 2>/dev/null || echo "debian")
    sh -c "echo \"deb http://apt.postgresql.org/pub/repos/apt ${lsb_dist}-pgdg main\" > /etc/apt/sources.list.d/pgdg.list" || true
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - || true
    apt-get update
    echo "Installing PostgreSQL 16..."
    apt-get install -y postgresql-16 postgresql-contrib-16
  fi

  # 2. Get the installed PostgreSQL major version
  PG_VERSION=$(psql --version | grep -oE '[0-9]+' | head -n 1)
  echo "PostgreSQL version detected: $PG_VERSION"

  # 3. Install the matching pgvector package
  echo "Installing postgresql-${PG_VERSION}-pgvector..."
  if apt-get install -y "postgresql-${PG_VERSION}-pgvector" 2>/dev/null; then
    echo "postgresql-${PG_VERSION}-pgvector installed successfully via APT."
  else
    echo "Warning: apt package postgresql-${PG_VERSION}-pgvector not found. Building pgvector from source..."
    # Install compiling dependencies
    apt-get install -y git build-essential postgresql-server-dev-${PG_VERSION}
    TEMP_SRC_DIR=$(mktemp -d)
    git clone --branch v0.8.2 https://github.com/pgvector/pgvector.git "$TEMP_SRC_DIR"
    (cd "$TEMP_SRC_DIR" && make && make install)
    rm -rf "$TEMP_SRC_DIR"
    echo "pgvector compiled and installed from source successfully."
  fi
  echo "pgvector extension is deployed and ready on the cloud server!"

  # 4. Ensure PostgreSQL is enabled and running
  echo "Starting and enabling PostgreSQL service..."
  systemctl daemon-reload || true
  systemctl enable postgresql || true
  systemctl start postgresql || true

  # 5. Check and Create Database 'job_dashboard' on native PostgreSQL
  echo "Checking PostgreSQL database 'job_dashboard'..."
  if sudo -u postgres psql -lqt 2>/dev/null | grep -qw "job_dashboard"; then
    echo "Database 'job_dashboard' already exists."
  else
    echo "Creating database 'job_dashboard'..."
    sudo -u postgres createdb job_dashboard || echo "Warning: Failed to create job_dashboard database automatically."
  fi
  echo "=========================================================="
fi

echo "Starting and enabling Redis service..."
systemctl daemon-reload || true
systemctl enable redis-server || true
systemctl start redis-server || true

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Installing Node.js and npm..."
  apt-get install -y nodejs npm || apt-get install -y nodejs
else
  echo "Node.js ($(node -v)) and npm ($(npm -v)) are already installed. Skipping installation."
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$REQUIREMENTS_FILE"

if [[ -f "$APP_DIR/frontend/package.json" ]]; then
  (cd "$APP_DIR/frontend" && npm install && npm run build)
fi

mkdir -p "$PERSISTENT_ENV_DIR"
chmod 700 "$PERSISTENT_ENV_DIR"

if [[ ! -f "$PERSISTENT_ENV_FILE" ]]; then
  if [[ -f "$APP_ENV_FILE" ]]; then
    cp "$APP_ENV_FILE" "$PERSISTENT_ENV_FILE"
    echo "Copied runtime environment from $APP_ENV_FILE to $PERSISTENT_ENV_FILE."
  else
    cp "$APP_DIR/deploy/.env.server.example" "$PERSISTENT_ENV_FILE"
    echo "Created $PERSISTENT_ENV_FILE from example. Edit it before using the AI features."
  fi
fi

# Automatically add local PostgreSQL DATABASE_URL to persistent env if not present
if ! grep -q "^DATABASE_URL=" "$PERSISTENT_ENV_FILE" 2>/dev/null; then
  echo "DATABASE_URL=postgresql://postgres@localhost:5432/job_dashboard" >> "$PERSISTENT_ENV_FILE"
  echo "Automatically added local PostgreSQL DATABASE_URL to $PERSISTENT_ENV_FILE."
fi
if ! grep -q "^REDIS_URL=" "$PERSISTENT_ENV_FILE" 2>/dev/null; then
  echo "REDIS_URL=redis://127.0.0.1:6379/0" >> "$PERSISTENT_ENV_FILE"
  echo "Automatically added local Redis REDIS_URL to $PERSISTENT_ENV_FILE."
fi
if ! grep -q "^RQ_QUEUE_NAME=" "$PERSISTENT_ENV_FILE" 2>/dev/null; then
  echo "RQ_QUEUE_NAME=internpath-default" >> "$PERSISTENT_ENV_FILE"
fi
if ! grep -q "^RQ_JOB_TIMEOUT_SECONDS=" "$PERSISTENT_ENV_FILE" 2>/dev/null; then
  echo "RQ_JOB_TIMEOUT_SECONDS=1800" >> "$PERSISTENT_ENV_FILE"
fi
if ! grep -q "^RQ_RESULT_TTL_SECONDS=" "$PERSISTENT_ENV_FILE" 2>/dev/null; then
  echo "RQ_RESULT_TTL_SECONDS=86400" >> "$PERSISTENT_ENV_FILE"
fi

mkdir -p "$APP_DIR/.cache"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"
chmod 700 "$APP_DIR/.cache"
chmod 600 "$PERSISTENT_ENV_FILE"

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=InternPath FastAPI Service
After=network.target postgresql.service redis-server.service ${SERVICE_NAME}-ai.service ${SERVICE_NAME}-worker.service
Wants=postgresql.service redis-server.service ${SERVICE_NAME}-ai.service ${SERVICE_NAME}-worker.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${PERSISTENT_ENV_FILE}
Environment=HOME=${APP_DIR}
Environment=XDG_CACHE_HOME=${APP_DIR}/.cache
ExecStart=${APP_DIR}/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${APP_PORT}
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
LockPersonality=true
RestrictRealtime=true
ReadWritePaths=${APP_DIR}
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/${SERVICE_NAME}-ai.service <<EOF
[Unit]
Description=InternPath AI Service
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/ai-service
EnvironmentFile=${PERSISTENT_ENV_FILE}
Environment=HOME=${APP_DIR}
Environment=XDG_CACHE_HOME=${APP_DIR}/.cache
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${AI_PORT}
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
LockPersonality=true
RestrictRealtime=true
ReadWritePaths=${APP_DIR}
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/${SERVICE_NAME}-worker.service <<EOF
[Unit]
Description=InternPath RQ Worker
After=network.target postgresql.service redis-server.service ${SERVICE_NAME}-ai.service
Wants=postgresql.service redis-server.service ${SERVICE_NAME}-ai.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${PERSISTENT_ENV_FILE}
Environment=HOME=${APP_DIR}
Environment=XDG_CACHE_HOME=${APP_DIR}/.cache
ExecStart=${APP_DIR}/.venv/bin/python -m backend.rq_worker
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
LockPersonality=true
RestrictRealtime=true
ReadWritePaths=${APP_DIR}
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl enable "${SERVICE_NAME}-ai"
systemctl enable "${SERVICE_NAME}-worker"
# Always restart so new code from deploy is picked up (enable --now does not restart a running unit).
systemctl restart "${SERVICE_NAME}-ai"
systemctl restart "${SERVICE_NAME}-worker"
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}-ai"
systemctl --no-pager --full status "${SERVICE_NAME}-worker"

echo
echo "InternPath is expected on port ${APP_PORT}."
echo "InternPath AI service is expected on 127.0.0.1:${AI_PORT}."
echo "Make sure your cloud firewall/security group allows inbound TCP ${APP_PORT}."
echo "Installed dependencies from ${REQUIREMENTS_FILE}."
