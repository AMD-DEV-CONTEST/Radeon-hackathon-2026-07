"""
LaunchKart AI 2.0 — Application Configuration

Centralized settings management using Pydantic Settings.
All configuration is loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_name: str = "LaunchKart AI 2.0"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"

    # ---- Security ----
    jwt_secret_key: str = "change-this-to-a-random-64-char-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///./launchkart_db.sqlite"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 3600

    # ---- ChromaDB ----
    chroma_persist_directory: str = "./chroma_data"
    chroma_collection_name: str = "launchkart_memory"

    # ---- Ollama (Local AI Inference) ----
    ollama_base_url: str = "http://localhost:11434"
    ollama_vision_model: str = "llava:13b"
    ollama_text_model: str = "llama3.1"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_request_timeout: int = 120
    ollama_max_concurrent: int = 4

    # ---- AMD GPU / ROCm ----
    rocm_enabled: bool = True
    gpu_monitor_interval: int = 5
    hsa_override_gfx_version: str = ""

    # ---- File Storage ----
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    allowed_image_types: str = "image/jpeg,image/png,image/webp,image/bmp"

    # ---- Rate Limiting ----
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ---- CORS ----
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ---- Computed properties ----

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def allowed_image_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_image_types.split(",")]

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if v == "change-this-to-a-random-64-char-string":
            import warnings
            warnings.warn(
                "JWT_SECRET_KEY is using default value. Set a secure random key in production!",
                UserWarning,
                stacklevel=2,
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
