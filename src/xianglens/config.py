"""Environment-driven application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration with safe, non-secret defaults."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="XIANG_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "XiangLens"
    app_env: Literal["development", "test", "production"] = "development"
    deployment_mode: Literal["development-remote", "submission-local"] = "development-remote"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    auth_enabled: bool = False
    app_api_key: SecretStr = SecretStr("")

    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "xianglens-qwen3.6-35b-a3b-fable5-q6k"
    llm_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    llm_probe_on_start: bool = False

    sqlite_path: Path = PROJECT_ROOT / "runtime/xianglens.sqlite3"
    milvus_uri: Path = PROJECT_ROOT / "runtime/xianglens_milvus.db"
    upload_dir: Path = PROJECT_ROOT / "runtime/uploads"
    export_dir: Path = PROJECT_ROOT / "runtime/exports"
    image_retention: Literal["memory_only", "session", "history"] = "session"
    session_ttl_minutes: int = Field(default=60, ge=5, le=1440)

    embedding_provider: Literal["hash", "fastembed"] = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = Field(default=384, ge=64, le=4096)
    rag_top_k: int = Field(default=4, ge=1, le=10)

    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=24_000_000, ge=1_000_000)
    allowed_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]

    @field_validator("sqlite_path", "milvus_uri", "upload_dir", "export_dir", mode="before")
    @classmethod
    def resolve_project_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def model_configured(self) -> bool:
        return bool(self.llm_base_url.strip())

    @property
    def submission_topology_compliant(self) -> bool:
        if self.deployment_mode != "submission-local":
            return False
        normalized = self.llm_base_url.lower()
        return normalized.startswith("http://127.0.0.1") or normalized.startswith(
            "http://localhost"
        )

    def ensure_runtime_directories(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.milvus_uri.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
