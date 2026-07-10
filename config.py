import os

from dotenv import load_dotenv

# Load variables from .env when present.
load_dotenv()


def get_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    value = raw_value.strip()
    if not value:
        return default

    return float(value)


def get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    value = raw_value.strip()
    if not value:
        return default

    return int(value)


def get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    value = raw_value.strip().lower()
    if not value:
        return default

    return value in {"1", "true", "yes", "on"}


class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    IS_WINDOWS: bool = os.name == "nt"
    NODE_ENV: str = os.getenv("NODE_ENV", "development").strip().lower()
    IS_PRODUCTION: bool = NODE_ENV == "production"
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "").strip()

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "your_api_key_here")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    LLM_TIMEOUT: float = get_float_env("LLM_TIMEOUT", 300.0)
    OPENAI_PROMPT_CACHE_ENABLED: bool = get_bool_env("OPENAI_PROMPT_CACHE_ENABLED", True)
    OPENAI_PROMPT_CACHE_KEY_PREFIX: str = os.getenv("OPENAI_PROMPT_CACHE_KEY_PREFIX", "internpath").strip() or "internpath"
    OPENAI_PROMPT_CACHE_RETENTION: str = os.getenv("OPENAI_PROMPT_CACHE_RETENTION", "24h").strip()
    OPENAI_PROMPT_CACHE_STABLE_PREFIX_ENABLED: bool = get_bool_env("OPENAI_PROMPT_CACHE_STABLE_PREFIX_ENABLED", True)
    AGENT_HR_CRITIC_MAX_RETRIES_AUTO: int = get_int_env("AGENT_HR_CRITIC_MAX_RETRIES_AUTO", 0)
    AGENT_HR_CRITIC_MAX_RETRIES_COPILOT: int = get_int_env("AGENT_HR_CRITIC_MAX_RETRIES_COPILOT", 1)
    AGENT_LLM_FACT_GUARD_ON_LOCAL_PASS: bool = get_bool_env("AGENT_LLM_FACT_GUARD_ON_LOCAL_PASS", False)
    AI_SERVICE_BASE_URL: str = os.getenv("AI_SERVICE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_BASE_URL: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DATABASE_SCHEMA: str = os.getenv("DATABASE_SCHEMA", "public").strip() or "public"
    REDIS_URL: str = os.getenv("REDIS_URL", "").strip()
    RQ_QUEUE_NAME: str = os.getenv("RQ_QUEUE_NAME", "internpath-default").strip() or "internpath-default"
    RQ_JOB_TIMEOUT_SECONDS: int = get_int_env("RQ_JOB_TIMEOUT_SECONDS", 1800)
    RQ_RESULT_TTL_SECONDS: int = get_int_env("RQ_RESULT_TTL_SECONDS", 86400)
    LANGGRAPH_CHECKPOINTER: str = os.getenv("LANGGRAPH_CHECKPOINTER", "postgres").strip().lower() or "postgres"
    LANGGRAPH_POSTGRES_SETUP: bool = get_bool_env("LANGGRAPH_POSTGRES_SETUP", True)
    AGENT_CACHE_STORE: str = os.getenv("AGENT_CACHE_STORE", "file").strip() or "file"
    AGENT_CACHE_TTL_SECONDS: int = get_int_env("AGENT_CACHE_TTL_SECONDS", 86400 * 14)
    AGENT_CACHE_LOCK_TIMEOUT_SECONDS: int = get_int_env("AGENT_CACHE_LOCK_TIMEOUT_SECONDS", 10)
    PGVECTOR_REQUIRED: bool = get_bool_env("PGVECTOR_REQUIRED", True)

    DOCX_BOUNDARY_REGION_RATIO: float = get_float_env("DOCX_BOUNDARY_REGION_RATIO", 0.12)
    DOCX_BOUNDARY_EDGE_BAND_RATIO: float = get_float_env("DOCX_BOUNDARY_EDGE_BAND_RATIO", 0.04)
    DOCX_BOUNDARY_DARK_PIXEL_THRESHOLD: int = get_int_env("DOCX_BOUNDARY_DARK_PIXEL_THRESHOLD", 225)
    DOCX_BOUNDARY_MIN_EDGE_DARK_PIXELS: int = get_int_env("DOCX_BOUNDARY_MIN_EDGE_DARK_PIXELS", 12)
    DOCX_BOUNDARY_MIN_EDGE_DARK_RATIO: float = get_float_env("DOCX_BOUNDARY_MIN_EDGE_DARK_RATIO", 0.0007)
    DOCX_BOUNDARY_HORIZONTAL_LINE_WIDTH_RATIO: float = get_float_env("DOCX_BOUNDARY_HORIZONTAL_LINE_WIDTH_RATIO", 0.32)
    DOCX_BOUNDARY_VERTICAL_LINE_HEIGHT_RATIO: float = get_float_env("DOCX_BOUNDARY_VERTICAL_LINE_HEIGHT_RATIO", 0.65)
    DOCX_BOUNDARY_MIN_VERTICAL_EDGE_LINES: int = get_int_env("DOCX_BOUNDARY_MIN_VERTICAL_EDGE_LINES", 2)
    DOCX_BOUNDARY_SAVE_EVIDENCE: bool = get_bool_env("DOCX_BOUNDARY_SAVE_EVIDENCE", True)
    DOCX_BOUNDARY_EVIDENCE_DIR: str = os.getenv("DOCX_BOUNDARY_EVIDENCE_DIR", "").strip()
    DOCX_BOUNDARY_LLM_ENABLED: bool = get_bool_env("DOCX_BOUNDARY_LLM_ENABLED", True)
    DOCX_BOUNDARY_LLM_REQUIRED: bool = get_bool_env("DOCX_BOUNDARY_LLM_REQUIRED", False)
    DOCX_BOUNDARY_LLM_MODEL: str = os.getenv("DOCX_BOUNDARY_LLM_MODEL", "gemini-1.5-flash").strip()
    DOCX_BOUNDARY_LLM_BASE_URL: str = os.getenv("DOCX_BOUNDARY_LLM_BASE_URL", "").strip()
    DOCX_BOUNDARY_LLM_API_KEY: str = os.getenv("DOCX_BOUNDARY_LLM_API_KEY", "").strip()
    DOCX_BOUNDARY_LLM_TEMPERATURE: float = get_float_env("DOCX_BOUNDARY_LLM_TEMPERATURE", 0.0)
    DOCX_BOUNDARY_LLM_TIMEOUT: float = get_float_env("DOCX_BOUNDARY_LLM_TIMEOUT", 120.0)

    EMAIL_VERIFICATION_REQUIRED: bool = get_bool_env("EMAIL_VERIFICATION_REQUIRED", True)
    EMAIL_CODE_TTL_MINUTES: int = get_int_env("EMAIL_CODE_TTL_MINUTES", 10)
    EMAIL_CODE_MAX_ATTEMPTS: int = get_int_env("EMAIL_CODE_MAX_ATTEMPTS", 5)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT: int = get_int_env("SMTP_PORT", 587)
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS: bool = get_bool_env("SMTP_USE_TLS", True)
    MAIL_FROM: str = os.getenv("MAIL_FROM", "InternPath <noreply@internpath.local>").strip()

    DB_PATH: str = os.path.join(BASE_DIR, "career_path.db")
    USER_DB_DIR: str = os.path.join(BASE_DIR, "user_data")
    INITIAL_ADMIN_USERNAME: str = os.getenv("INTERNPATH_ADMIN_USERNAME", "").strip()
    INITIAL_ADMIN_PASSWORD: str = os.getenv("INTERNPATH_ADMIN_PASSWORD", "")

    DEFAULT_PRACTICE_APP_PATH: str = (
        r"C:\Path\To\AiSmartDrill.App.exe"
        if IS_WINDOWS
        else ""
    )
    PRACTICE_APP_PATH: str = os.getenv("PRACTICE_APP_PATH", DEFAULT_PRACTICE_APP_PATH)
    TEMP_SKILLPKG_PATH: str = os.path.join(BASE_DIR, "temp_practice.skillpkg")

    CRAWLER_DELAY_MIN: float = 1.0
    CRAWLER_DELAY_MAX: float = 3.0

    BILIBILI_SEARCH_URL: str = "https://search.bilibili.com/all"

    RANK_RELEVANCE_WEIGHT: float = 0.4
    RANK_QUALITY_WEIGHT: float = 0.4
    RANK_TIMELINESS_WEIGHT: float = 0.2

    TOP_COURSES_PER_SKILL: int = 3
