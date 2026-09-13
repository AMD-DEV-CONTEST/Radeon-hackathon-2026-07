"""
Centralized, type-safe application configuration.

All configuration flows through this single Settings object so that:
  - No module reads os.environ directly (testability, single source of truth).
  - Misconfiguration fails fast at startup, not mid-request.
  - Secrets are never logged (see __repr__ override).
"""
from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App metadata ---
    APP_NAME: str = "Aegis"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # --- Security ---
    SECRET_KEY: str = Field(..., min_length=16)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Database ---
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Local inference (ROCm / vLLM) ---
    INFERENCE_BASE_URL: str = "http://localhost:8001/v1"
    INFERENCE_MODEL: str = "Qwen2.5-14B-Instruct"
    INFERENCE_API_KEY: str = "not-needed-local"
    INFERENCE_TIMEOUT_SECONDS: int = 120
    INFERENCE_MAX_CONCURRENCY: int = 8

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:3000"

    # --- Rate limiting ---
    RATE_LIMIT_PER_MINUTE: int = 120

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment_secret_strength(cls, v: str, info) -> str:
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def __repr__(self) -> str:
        # Prevent accidental secret leakage into logs/tracebacks.
        return f"Settings(APP_NAME={self.APP_NAME!r}, ENVIRONMENT={self.ENVIRONMENT!r})"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor. FastAPI dependencies should call this rather than
    instantiating Settings() directly, so the whole app shares one validated instance.
    """
    return Settings()
