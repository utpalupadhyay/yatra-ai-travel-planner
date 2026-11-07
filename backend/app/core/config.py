"""
Yatra AI - Core Configuration
Loads all settings from environment variables with performance optimizations.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === App Settings ===
    APP_NAME: str = "Yatra AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://localhost:8000",
        "https://yatra-ai-gprf.vercel.app",
        "*",
    ]

    # === Gemini / Gemma API Keys ===
    GEMMA_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    # === AI Model Configuration ===
    # Primary model: gemini-2.5-flash for fastest latency, instant TTFT, and high quality
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMMA_MODEL: str = "gemini-2.5-flash"
    GEMMA_MODEL_FALLBACK: str = "gemini-flash-latest"
    
    # Priority order for model selection
    PREFERRED_MODELS: list[str] = [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
        "gemma-4-31b-it",
    ]

    # Generation parameters
    GEMMA_MAX_TOKENS: int = 4096
    GEMMA_TEMPERATURE: float = 0.7
    API_TIMEOUT_SECONDS: float = 25.0

    # === In-Memory Caching ===
    ENABLE_CACHE: bool = True
    CACHE_TTL_SECONDS: int = 3600  # 1 hour
    CACHE_MAX_ENTRIES: int = 500

    # === Database (optional - SQLite by default) ===
    DATABASE_URL: str = "sqlite:///./yatra_ai.db"

    # === Rate limiting ===
    MAX_TRIPS_PER_DAY: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
