import os
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "your_api_key_here")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    
    DB_PATH: str = os.path.join(BASE_DIR, "career_path.db")
    
    PRACTICE_APP_PATH: str = os.getenv("PRACTICE_APP_PATH", r"C:\YourAppPath\PracticeApp.exe")
    TEMP_SKILLPKG_PATH: str = os.path.join(BASE_DIR, "temp_practice.skillpkg")
    
    CRAWLER_DELAY_MIN: float = 1.0
    CRAWLER_DELAY_MAX: float = 3.0
    
    BILIBILI_SEARCH_URL: str = "https://search.bilibili.com/all"
    
    RANK_RELEVANCE_WEIGHT: float = 0.4
    RANK_QUALITY_WEIGHT: float = 0.4
    RANK_TIMELINESS_WEIGHT: float = 0.2
    
    TOP_COURSES_PER_SKILL: int = 3
