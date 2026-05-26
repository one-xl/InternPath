#!/usr/bin/env python3
"""
One-shot deploy to Debian over SSH+SFTP (password auth).

Usage (PowerShell, password):
  $env:INTERNPATH_SSH_PASSWORD = 'your_root_password'
  python deploy/remote_deploy.py

Or SSH private key (recommended):
  $env:INTERNPATH_SSH_KEY = "$HOME/.ssh/id_ed25519"
  python deploy/remote_deploy.py

Requires: pip install paramiko
"""

from __future__ import annotations

import io
import os
import shlex
import stat
import sys
import tarfile
from pathlib import Path

HOST = os.getenv("INTERNPATH_SSH_HOST", "").strip()
SSH_PORT = int(os.getenv("INTERNPATH_SSH_PORT", "22"))
USER = os.getenv("INTERNPATH_SSH_USER", "root")
REMOTE_TAR = "/tmp/internpath_deploy.tgz"
APP_DIR = "/opt/internpath"
APP_PORT = os.getenv("INTERNPATH_APP_PORT", "8502")
INITIAL_ADMIN_USERNAME = os.getenv("INTERNPATH_ADMIN_USERNAME", "").strip()
INITIAL_ADMIN_PASSWORD = os.getenv("INTERNPATH_ADMIN_PASSWORD", "")

EXCLUDE_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".idea",
    ".cursor",
    "logs",
    "user_data",
    ".test_dbs",
}
EXCLUDE_FILES = {
    "career_path.db",
}
EXCLUDE_SUFFIXES = (".pyc",)
ALLOWED_ENV_FILES = {
    Path(".env.example"),
    Path("deploy/.env.server.example"),
}


def should_skip(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_NAMES for p in parts):
        return True
    if rel.name.startswith(".env") and rel not in ALLOWED_ENV_FILES:
        return True
    if rel.name in EXCLUDE_FILES:
        return True
    if rel.name.endswith(EXCLUDE_SUFFIXES):
        return True
    return False


def build_tar_bytes(root: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if should_skip(rel):
                continue
            tar.add(path, arcname=str(rel).replace("\\", "/"))
    return buf.getvalue()


def main() -> int:
    password = os.environ.get("INTERNPATH_SSH_PASSWORD", "").strip()
    key_path = os.environ.get("INTERNPATH_SSH_KEY", "").strip()

    if not HOST:
        print("Set INTERNPATH_SSH_HOST before running this script.", file=sys.stderr)
        return 1

    if not password and not key_path:
        print(
            "Set INTERNPATH_SSH_PASSWORD or INTERNPATH_SSH_KEY (path to private key).",
            file=sys.stderr,
        )
        return 1

    root = Path(__file__).resolve().parents[1]
    data = build_tar_bytes(root)
    print(f"Packed {len(data)} bytes from {root}")

    try:
        import paramiko
    except ImportError:
        print("Install paramiko: pip install paramiko", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if key_path:
        key_file = Path(key_path).expanduser()
        if not key_file.is_file():
            print(f"Key not found: {key_file}", file=sys.stderr)
            return 1
        key_pass = password if password else None
        for KeyCls in (
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
        ):
            try:
                pkey = KeyCls.from_private_key_file(str(key_file), password=key_pass)
                break
            except Exception:
                continue
        if pkey is None:
            print("Could not load private key (wrong format or passphrase?).", file=sys.stderr)
            return 1

    connect_kw: dict = {
        "hostname": HOST,
        "port": SSH_PORT,
        "username": USER,
        "timeout": 60,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if pkey is not None:
        connect_kw["pkey"] = pkey
    if password and not key_path:
        connect_kw["password"] = password

    client.connect(**connect_kw)
    try:
        sftp = client.open_sftp()
        with sftp.file(REMOTE_TAR, "wb") as rf:
            rf.write(data)
        sftp.chmod(REMOTE_TAR, stat.S_IRUSR | stat.S_IWUSR)
        sftp.close()

        # Dynamically load local .env variables to sync LLM settings to the server
        local_env_path = root / ".env"
        local_llm_keys = {}
        if local_env_path.is_file():
            with open(local_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        if key.startswith("LLM_"):
                            local_llm_keys[key] = val.strip()

        llm_env_script = ""
        if local_llm_keys:
            llm_env_script = "touch /etc/internpath/app.env\n"
            for k, v in local_llm_keys.items():
                v_escaped = shlex.quote(f"{k}={v}")
                # Escape single quotes in value for sed
                v_sed = v.replace("'", "'\\''")
                # Update if exist, append if not
                llm_env_script += f"grep -q '^{k}=' /etc/internpath/app.env && sed -i 's|^{k}=.*|{k}={v_sed}|' /etc/internpath/app.env || printf '%s\\n' {v_escaped} >> /etc/internpath/app.env\n"

        admin_env_script = ""
        if INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD:
            admin_username = shlex.quote(f"INTERNPATH_ADMIN_USERNAME={INITIAL_ADMIN_USERNAME}")
            admin_password = shlex.quote(f"INTERNPATH_ADMIN_PASSWORD={INITIAL_ADMIN_PASSWORD}")
            admin_env_script = f"""
touch /etc/internpath/app.env
grep -q '^INTERNPATH_ADMIN_USERNAME=' /etc/internpath/app.env || printf '%s\\n' {admin_username} >> /etc/internpath/app.env
grep -q '^INTERNPATH_ADMIN_PASSWORD=' /etc/internpath/app.env || printf '%s\\n' {admin_password} >> /etc/internpath/app.env
chmod 600 /etc/internpath/app.env
"""

        script = f"""set -euo pipefail
mkdir -p {APP_DIR}
tar -xzf {REMOTE_TAR} -C {APP_DIR}
rm -f {REMOTE_TAR}
find {APP_DIR} -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null || true
find {APP_DIR} -name '*.pyc' -delete 2>/dev/null || true
cd {APP_DIR}
chmod +x deploy/server_install.sh
systemctl stop internpath || true
rm -rf .venv
APP_DIR={APP_DIR} APP_PORT={APP_PORT} SERVICE_NAME=internpath REQUIREMENTS_FILE={APP_DIR}/requirements.server.txt ./deploy/server_install.sh
{llm_env_script}
{admin_env_script}
chmod 600 /etc/internpath/app.env
systemctl restart internpath
command -v ufw >/dev/null 2>&1 && ufw allow {APP_PORT}/tcp comment internpath || true
"""
        stdin, stdout, stderr = client.exec_command(script, timeout=600)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if out:
            sys.stdout.write(out.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
            sys.stdout.flush()
        if err:
            sys.stderr.write(err.encode(sys.stderr.encoding or "utf-8", errors="replace").decode(sys.stderr.encoding or "utf-8"))
            sys.stderr.flush()
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
