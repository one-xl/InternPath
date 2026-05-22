"""Environment-driven configuration for InternPath AI service."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVICE_ROOT.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_dotenv(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key and key not in os.environ:
            os.environ[key] = value


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        parts = list(lexer)
    except ValueError:
        parts = [value.strip()]
    return key, " ".join(parts)


class Settings:
    load_dotenv()

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    VECTOR_STORE_TYPE: str = os.getenv("VECTOR_STORE_TYPE", "bm25")
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    AI_SERVICE_PORT: int = int(os.getenv("AI_SERVICE_PORT", "8000") or "8000")
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60") or "60")
