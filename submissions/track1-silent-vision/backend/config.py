from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    command_backend: Literal["fake", "torch", "prototype"] = "fake"
    persistence_root: Path = Path("/workspace/persistent/silent-vision")
    capture_fps: int = Field(default=25, ge=1, le=60)
    capture_countdown_seconds: int = Field(default=3, ge=0, le=10)
    command_clip_fps: int = Field(default=25, ge=1, le=60)
    command_clip_min_seconds: float = Field(default=2.0, ge=0.2)
    command_clip_max_seconds: float = Field(default=5.0, ge=0.2)
    command_confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    command_top1_margin: float = Field(default=0.20, ge=0.0, le=1.0)
    command_classifier_checkpoint: Path | None = None
    command_phrase_probability_override: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    command_phrase_distance_override: float | None = Field(default=None, ge=0.0, le=1.0)
    prototype_feature_dim: int = Field(default=128, ge=1)
    prototype_confidence_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    prototype_top1_margin: float = Field(default=0.12, ge=0.0, le=1.0)
    prototype_prefer_personal: bool = False
    allow_global_profile_write: bool = True
    mouth_size: int = Field(default=96, ge=16)
    model_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    allowed_origins: str = "http://localhost:8000"
    log_transcripts: bool = False
    log_level: str = "INFO"
    debug_dump_windows: bool = False
    debug_window_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    enable_model_health: bool = False

    @property
    def allowed_origin_set(self) -> set[str]:
        return {
            item.strip() for item in self.allowed_origins.split(",") if item.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
