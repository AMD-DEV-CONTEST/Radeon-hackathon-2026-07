"""
Config model - Pydantic validation, no hardcoding
"""

from pydantic import BaseSettings, Field


class AppConfig(BaseSettings):
    """Application config - environment variable driven"""

    # Model endpoints
    model_small_url: str = Field(default="", env="MODEL_SMALL_URL")
    model_large_url: str = Field(default="", env="MODEL_LARGE_URL")

    # Performance
    max_concurrent: int = Field(default=100, env="MAX_CONCURRENT")
    cache_size: int = Field(default=1000, env="CACHE_SIZE")

    # OOM protection
    max_context_length: int = Field(default=128000, env="MAX_CONTEXT_LENGTH")

    class Config:
        env_file = ".env"
