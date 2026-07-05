# Debian Deployment

InternPath runs as a FastAPI backend, a separate AI service, and an RQ worker backed by PostgreSQL/pgvector and Redis.

## 1. Prepare the target host

- Linux distribution: Debian or compatible
- Python 3.9+
- Node.js and npm
- PostgreSQL + pgvector
- Redis
- Open inbound TCP for the app port you choose, for example `8502`

## 2. Upload the project

### Option A: use `remote_deploy.py`

```powershell
$env:INTERNPATH_SSH_HOST = "your.server.example"
$env:INTERNPATH_SSH_USER = "root"
$env:INTERNPATH_SSH_PASSWORD = "your_password"
python deploy/remote_deploy.py
```

Optional override:

```powershell
$env:INTERNPATH_APP_PORT = "8502"
```

### Option B: upload manually

```bash
mkdir -p /opt/internpath
```

Then copy the project files to `/opt/internpath`.

## 3. Install and start

On the server:

```bash
cd /opt/internpath
chmod +x deploy/server_install.sh
APP_DIR=/opt/internpath APP_PORT=8502 SERVICE_NAME=internpath REQUIREMENTS_FILE=/opt/internpath/requirements.server.txt ./deploy/server_install.sh
```

The installer creates a Python virtualenv, installs backend dependencies, installs/starts PostgreSQL + pgvector and Redis, runs `npm install && npm run build` in `frontend`, and starts three systemd services: `internpath`, `internpath-ai`, and `internpath-worker`.

## 4. Configure `.env`

Create or edit `/opt/internpath/.env`:

```env
DATABASE_URL=postgresql://postgres@localhost:5432/job_dashboard
REDIS_URL=redis://127.0.0.1:6379/0
RQ_QUEUE_NAME=internpath-default
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
PRACTICE_APP_PATH=
```

## 5. Verify

```bash
systemctl status internpath
systemctl status internpath-ai
systemctl status internpath-worker
journalctl -u internpath -u internpath-ai -u internpath-worker -n 100 --no-pager
ss -ltnp | grep 8502
```

Open:

`http://your.server.example:8502`
