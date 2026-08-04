"""
THEMIS Configuration
Team: Alchemy | AMD AI DevMaster Hackathon 2026
Loads all settings from environment variables with safe defaults.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────
    app_name: str = "THEMIS"
    app_version: str = "1.0.0"
    debug: bool = False
    api_key: str = Field(default="themis-dev-key-change-in-prod", env="THEMIS_API_KEY")

    # ── vLLM Inference Server (AMD Radeon W7900D) ─────────────
    vllm_base_url: str = Field(default="http://localhost:8000/v1", env="VLLM_BASE_URL")
    vllm_model_name: str = Field(default="themis-coder", env="VLLM_MODEL_NAME")
    vllm_timeout: int = Field(default=120, env="VLLM_TIMEOUT")

    # LLM params — security analysis (deterministic)
    security_temperature: float = 0.1
    security_top_p: float = 0.9
    security_max_tokens: int = 2048
    security_seed: int = 42

    # LLM params — fix generation (slightly creative)
    fix_temperature: float = 0.3
    fix_top_p: float = 0.95
    fix_max_tokens: int = 4096

    # ── GitHub ────────────────────────────────────────────────
    github_token: str = Field(default="", env="GITHUB_TOKEN")
    github_max_files: int = 280          # Buffer below 300-file API limit
    github_rate_limit_pause: int = 60    # Seconds to wait on 403/429

    # ── RAG / Qdrant ─────────────────────────────────────────
    qdrant_url: str = Field(default="http://localhost:6333", env="QDRANT_URL")
    qdrant_collection: str = "themis_knowledge"
    qdrant_top_k: int = 20              # Candidates before reranking
    qdrant_top_n: int = 5               # Final chunks after reranking
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ── Docker Sandbox ────────────────────────────────────────
    sandbox_mem_limit: str = "512m"
    sandbox_cpu_quota: int = 50000      # 0.5 CPU max
    sandbox_timeout: int = 30           # Hard 30s timeout
    sandbox_network: str = "none"       # No network egress

    # ── Agent Safety ─────────────────────────────────────────
    agent_recursion_limit: int = 30
    confidence_threshold: float = 0.7   # Filter findings below this

    # ── WebSocket ─────────────────────────────────────────────
    ws_heartbeat_interval: int = 15

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
