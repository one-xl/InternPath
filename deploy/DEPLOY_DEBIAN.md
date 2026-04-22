# Debian Deployment

This project runs as a Streamlit app and can be deployed behind a custom port or a reverse proxy.

## 1. Prepare the target host

- Linux distribution: Debian or compatible
- Python 3.9+
- Open inbound TCP for the app port you choose, for example `8502`

## 2. Upload the project

### Option A: use `remote_deploy.py`

Set the SSH target explicitly:

```powershell
$env:INTERNPATH_SSH_HOST = "your.server.example"
$env:INTERNPATH_SSH_USER = "root"
$env:INTERNPATH_SSH_PASSWORD = "your_password"
python deploy/remote_deploy.py
```

Or with a private key:

```powershell
$env:INTERNPATH_SSH_HOST = "your.server.example"
$env:INTERNPATH_SSH_USER = "root"
$env:INTERNPATH_SSH_KEY = "$HOME\.ssh\id_ed25519"
python deploy/remote_deploy.py
```

Optional overrides:

```powershell
$env:INTERNPATH_APP_PORT = "8502"
```

### Option B: upload manually

```bash
mkdir -p /opt/internpath
```

Then copy the project files to `/opt/internpath`.

## 3. Install and start the service

On the server:

```bash
cd /opt/internpath
chmod +x deploy/server_install.sh
APP_DIR=/opt/internpath APP_PORT=8502 SERVICE_NAME=internpath REQUIREMENTS_FILE=/opt/internpath/requirements.server.txt ./deploy/server_install.sh
```

## 4. Configure `.env`

Create or edit `/opt/internpath/.env`:

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
APP_PASSWORD_HASH=your_pbkdf2_hash
PRACTICE_APP_PATH=
```

Notes:

- Prefer `APP_PASSWORD_HASH` over plain `APP_PASSWORD`
- Keep `PRACTICE_APP_PATH=` empty on Linux
- The web app can still generate `aismartdrill://` links for client machines

## 5. Verify

```bash
systemctl status internpath
journalctl -u internpath -n 100 --no-pager
ss -ltnp | grep 8502
```

Open:

`http://your.server.example:8502`
