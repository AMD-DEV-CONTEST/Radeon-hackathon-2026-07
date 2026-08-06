"""Configuration loader for RepositoryAnalysisAgent.

Loads config.yaml and provides typed access to all settings.
Handles model path resolution and ROCm environment setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class LLMConfig:
    backend: str = "vllm"
    model: str = "Qwen/Qwen2.5-Coder-14B-Instruct"
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = "not-needed"
    dtype: str = "float16"
    max_model_len: int = 16384
    kv_cache_dtype: str = "fp16"
    gpu_memory_utilization: float = 0.88
    enforce_eager: bool = True
    temperature: float = 0.3
    top_p: float = 0.9
    vllm_version: str = "0.6.x"


@dataclass
class EmbeddingConfig:
    model: str = "BAAI/bge-m3"
    device: str = "cpu"
    batch_size: int = 16


@dataclass
class RerankerConfig:
    model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cuda"
    candidate_count: int = 20
    final_count: int = 15


@dataclass
class IndexConfig:
    vector_store: str = "chromadb"
    persist_dir: str = ".raa/index"
    supported_extensions: list[str] = field(default_factory=lambda: [".py"])
    exclude_dirs: list[str] = field(
        default_factory=lambda: [
            ".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".raa"
        ]
    )
    sensitive_patterns: list[str] = field(
        default_factory=lambda: ["*.env", "*.key", "*.pem", ".env*", "credentials*", "secrets*"]
    )


@dataclass
class AgentConfig:
    max_iterations: int = 8
    context_budget: int = 16384
    temperature: float = 0.3
    top_p: float = 0.9


@dataclass
class SessionConfig:
    persist: bool = True
    persist_dir: str = ".raa/sessions"
    max_recent: int = 10


@dataclass
class SecurityConfig:
    run_tests_enabled: bool = False
    test_commands: list[str] = field(default_factory=lambda: ["pytest", "python -m pytest"])
    max_test_timeout: int = 60


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    rocm_env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls(
            server=ServerConfig(**data.get("server", {})),
            llm=LLMConfig(**data.get("llm", {})),
            embedding=EmbeddingConfig(**data.get("embedding", {})),
            reranker=RerankerConfig(**data.get("reranker", {})),
            index=IndexConfig(**data.get("index", {})),
            agent=AgentConfig(**data.get("agent", {})),
            session=SessionConfig(**data.get("session", {})),
            security=SecurityConfig(**data.get("security", {})),
            rocm_env=data.get("rocm_env", {}),
        )

    def apply_rocm_env(self) -> None:
        """Set ROCm stability environment variables."""
        for key, val in self.rocm_env.items():
            os.environ.setdefault(key, str(val))

    @property
    def repo_root(self) -> Path:
        """The workspace root being analyzed (set at runtime)."""
        return Path(getattr(self, "_repo_root", ".")).resolve()

    @repo_root.setter
    def repo_root(self, value: str | Path) -> None:
        object.__setattr__(self, "_repo_root", str(value))


_config: Config | None = None


def get_config(config_path: str | Path | None = None) -> Config:
    """Get or create the global Config singleton."""
    global _config
    if _config is None:
        if config_path is None:
            config_path = Path(os.environ.get("REPOAGENT_CONFIG", "config.yaml"))
        _config = Config.from_yaml(config_path)
        _config.apply_rocm_env()
    return _config


def reset_config() -> None:
    """Reset the config singleton (for testing)."""
    global _config
    _config = None
