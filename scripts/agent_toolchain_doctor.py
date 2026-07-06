from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


PROJECT_ENV = {
    **load_env_file(ROOT / ".env.example"),
    **load_env_file(ROOT / ".env"),
}


def env_value(name: str) -> str:
    return os.environ.get(name) or PROJECT_ENV.get(name, "")


def run_command(args: list[str], cwd: Path = ROOT, timeout: int = 8) -> tuple[bool, str]:
    resolved_args = list(args)
    executable = shutil.which(resolved_args[0])
    if executable:
        resolved_args[0] = executable
    try:
        result = subprocess.run(
            resolved_args,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output.splitlines()[0] if output else ""


def port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def encode_redis_command(parts: list[str]) -> bytes:
    payload = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        encoded = part.encode("utf-8")
        payload.append(f"${len(encoded)}\r\n".encode("utf-8"))
        payload.append(encoded + b"\r\n")
    return b"".join(payload)


def send_redis_command(sock: socket.socket, parts: list[str]) -> str:
    sock.sendall(encode_redis_command(parts))
    return sock.recv(512).decode("utf-8", errors="replace").strip()


def check_path(path: str, *, directory: bool = False) -> dict[str, str]:
    target = ROOT / path
    exists = target.is_dir() if directory else target.exists()
    return {
        "name": path,
        "status": "ok" if exists else "missing",
        "detail": str(target),
    }


def check_env_var(name: str, *, required: bool = False) -> dict[str, str]:
    value = env_value(name)
    if value:
        source = "process" if os.environ.get(name) else ".env"
        detail = "set"
        if "KEY" in name or "SECRET" in name or "PASSWORD" in name:
            detail = f"set ({len(value)} chars)"
        return {"name": name, "status": "ok", "detail": f"{detail} via {source}"}
    return {
        "name": name,
        "status": "missing" if required else "optional",
        "detail": "not set",
    }


def check_database_url() -> dict[str, str]:
    url = env_value("DATABASE_URL")
    if not url:
        return {"name": "DATABASE_URL connectivity", "status": "skipped", "detail": "DATABASE_URL is not set"}
    parsed = urlparse(url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        return {"name": "DATABASE_URL connectivity", "status": "fail", "detail": f"unsupported scheme: {parsed.scheme}"}
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    if not port_open(host, port):
        return {"name": "DATABASE_URL connectivity", "status": "fail", "detail": f"{host}:{port} is not reachable"}
    try:
        import psycopg2
    except ModuleNotFoundError:
        return {
            "name": "DATABASE_URL connectivity",
            "status": "ok",
            "detail": f"{host}:{port} tcp reachable; psycopg2 not installed for {Path(sys.executable).name}",
        }
    try:
        conn = psycopg2.connect(url, connect_timeout=2)
        conn.close()
        return {"name": "DATABASE_URL connectivity", "status": "ok", "detail": f"{host}:{port}"}
    except Exception as exc:
        return {"name": "DATABASE_URL connectivity", "status": "fail", "detail": str(exc).splitlines()[0]}


def check_redis_url() -> dict[str, str]:
    url = env_value("REDIS_URL")
    if not url:
        return {"name": "REDIS_URL connectivity", "status": "skipped", "detail": "REDIS_URL is not set"}
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    if not port_open(host, port):
        return {"name": "REDIS_URL connectivity", "status": "fail", "detail": f"{host}:{port} is not reachable"}
    try:
        with socket.create_connection((host, port), timeout=2) as sock:
            sock.settimeout(2)
            if parsed.password:
                password = unquote(parsed.password)
                if parsed.username:
                    auth_reply = send_redis_command(sock, ["AUTH", unquote(parsed.username), password])
                else:
                    auth_reply = send_redis_command(sock, ["AUTH", password])
                if auth_reply.startswith("-"):
                    return {"name": "REDIS_URL connectivity", "status": "fail", "detail": auth_reply}
            db_name = parsed.path.lstrip("/").split("/", 1)[0]
            if db_name and db_name != "0":
                select_reply = send_redis_command(sock, ["SELECT", db_name])
                if select_reply.startswith("-"):
                    return {"name": "REDIS_URL connectivity", "status": "fail", "detail": select_reply}
            ping_reply = send_redis_command(sock, ["PING"])
            if not ping_reply.startswith("+PONG"):
                return {"name": "REDIS_URL connectivity", "status": "fail", "detail": ping_reply or "PING failed"}
        return {"name": "REDIS_URL connectivity", "status": "ok", "detail": f"{host}:{port}"}
    except Exception as exc:
        return {"name": "REDIS_URL connectivity", "status": "fail", "detail": str(exc).splitlines()[0]}


def count_project_files() -> dict[str, str]:
    ignored = {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".codegraph",
        ".reasonix",
        ".test_dbs",
        ".vscode",
        "logs",
        "scratch",
        "user_data",
    }
    paths = []
    for path in ROOT.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            paths.append(path)
    return {"name": "project files", "status": "ok", "detail": f"{len(paths)} files scanned"}


def check_docker_daemon() -> dict[str, str]:
    if not shutil.which("docker"):
        return {"name": "docker daemon", "status": "missing", "detail": "docker CLI is not installed"}
    ok, output = run_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=6)
    if ok:
        return {"name": "docker daemon", "status": "ok", "detail": output}
    return {"name": "docker daemon", "status": "fail", "detail": output or "docker daemon is not reachable"}


def main() -> int:
    checks: list[dict[str, str]] = []
    checks.extend([
        check_path("backend", directory=True),
        check_path("frontend", directory=True),
        check_path("ai-service", directory=True),
        check_path("tests", directory=True),
        check_path("backend/main.py"),
        check_path("frontend/package.json"),
        check_path("requirements.txt"),
    ])

    py_ok, py_version = run_command([sys.executable, "--version"])
    node_ok, node_version = run_command(["node", "--version"])
    npm_ok, npm_version = run_command(["npm", "--version"])
    checks.extend([
        {"name": "python", "status": "ok" if py_ok else "fail", "detail": py_version},
        {"name": "node", "status": "ok" if node_ok else "fail", "detail": node_version},
        {"name": "npm", "status": "ok" if npm_ok else "fail", "detail": npm_version},
        check_env_var("DATABASE_URL", required=True),
        check_env_var("REDIS_URL", required=True),
        check_env_var("GEMINI_API_KEY"),
        check_env_var("LLM_API_KEY"),
        check_database_url(),
        check_redis_url(),
        check_docker_daemon(),
        {"name": "frontend port 5173", "status": "open" if port_open("127.0.0.1", 5173) else "closed", "detail": "Vite dev server"},
        {"name": "backend port 8787", "status": "open" if port_open("127.0.0.1", 8787) else "closed", "detail": "FastAPI backend"},
        {"name": "ai-service port 8000", "status": "open" if port_open("127.0.0.1", 8000) else "closed", "detail": "AI service"},
        count_project_files(),
    ])

    print(json.dumps({
        "root": str(ROOT),
        "envFiles": {
            ".env": str((ROOT / ".env").exists()).lower(),
            ".env.example": str((ROOT / ".env.example").exists()).lower(),
        },
        "checks": checks,
        "recommendedCommands": [
            "npm run agent:compile",
            "npm run frontend:build",
            "npm run agent:test",
            ".\\start_internpath.cmd",
        ],
    }, ensure_ascii=False, indent=2))

    hard_fail = any(item["status"] in {"fail", "missing"} for item in checks if item["name"] in {"python", "node", "npm", "backend", "frontend"})
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
