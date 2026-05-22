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


class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    IS_WINDOWS: bool = os.name == "nt"
    NODE_ENV: str = os.getenv("NODE_ENV", "development").strip().lower()
    IS_PRODUCTION: bool = NODE_ENV == "production"
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "").strip()

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "your_api_key_here")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    LLM_TIMEOUT: float = get_float_env("LLM_TIMEOUT", 120.0)
    AI_SERVICE_BASE_URL: str = os.getenv("AI_SERVICE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_BASE_URL: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

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
