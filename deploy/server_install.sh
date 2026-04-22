#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/internpath}"
APP_PORT="${APP_PORT:-8502}"
SERVICE_NAME="${SERVICE_NAME:-internpath}"
APP_USER="${APP_USER:-internpath}"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$APP_DIR/requirements.server.txt}"

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "Requirements file not found: $REQUIREMENTS_FILE"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y python3 python3-venv python3-pip

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$REQUIREMENTS_FILE"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/deploy/.env.server.example" "$APP_DIR/.env"
  echo "Created $APP_DIR/.env from example. Edit it before using the AI features."
fi

mkdir -p "$APP_DIR/.cache"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"
chmod 700 "$APP_DIR/.cache"
chmod 600 "$APP_DIR/.env"

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=InternPath Streamlit Service
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment=HOME=${APP_DIR}
Environment=XDG_CACHE_HOME=${APP_DIR}/.cache
ExecStart=${APP_DIR}/.venv/bin/streamlit run ${APP_DIR}/app.py --server.address 0.0.0.0 --server.port ${APP_PORT} --browser.gatherUsageStats false
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
# Always restart so new code from deploy is picked up (enable --now does not restart a running unit).
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}"

echo
echo "InternPath is expected on port ${APP_PORT}."
echo "Make sure your cloud firewall/security group allows inbound TCP ${APP_PORT}."
echo "Installed dependencies from ${REQUIREMENTS_FILE}."
