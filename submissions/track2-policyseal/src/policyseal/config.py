from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="POLICYSEAL_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./var/policyseal.db"
    policy_dir: Path = Path("policies")
    data_dir: Path = Path("var")
    storage_dir: Path = Path("var/files")
    master_key_path: Path = Path("var/secrets/master.key")
    max_upload_bytes: int = 25 * 1024 * 1024
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = "Qwen/Qwen3-8B"
    llm_timeout_seconds: float = Field(default=30, gt=0, le=300)
    llm_max_tokens: int = Field(default=1_200, ge=128, le=8_192)
    semantic_min_confidence: float = Field(default=0.8, ge=0, le=1)
    semantic_batch_size: int = Field(default=8, ge=1, le=32)
    semantic_consistency_passes: int = Field(default=2, ge=1, le=3)
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_cache_dir: Path = Path("var/cache/fastembed")
    embedding_local_files_only: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
