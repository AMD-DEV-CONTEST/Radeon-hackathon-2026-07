"""Application settings loaded from environment variables / ``.env``."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration for the AgentVox API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "AgentVox"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"]
    )

    # Database
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/agentvox"

    # Security
    secret_key: str = "change-me-to-a-long-random-secret"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # Paths / logging
    upload_dir: str = "uploads"
    log_dir: str = "logs"
    log_level: str = "INFO"

    # Future OpenAI / LLM integration (disabled by default)
    llm_enabled: bool = False
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None

    # WebSocket realtime
    ws_heartbeat_interval_seconds: int = 30
    ws_heartbeat_timeout_seconds: int = 90

    # Future Redis
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # Future Celery
    celery_enabled: bool = False
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Future AMD APIs
    amd_api_enabled: bool = False
    amd_api_base_url: str | None = None
    amd_api_key: str | None = None

    # Future LangSmith
    langsmith_enabled: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "agentvox"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
