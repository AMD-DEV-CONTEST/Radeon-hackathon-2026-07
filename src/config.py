from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]

# Radeon Cloud official persistent volume (2026-07 notice).
# Mutable runtime data (vector store / memory / uploads / workflows / exports)
# lives under this tree when present; sample docs stay in the git checkout.
DEFAULT_PERSISTENCE_BASE = Path("/workspace/persistence")
DEFAULT_CLOUD_DATA_ROOT = DEFAULT_PERSISTENCE_BASE / "PrivateLocalAgent"

# Paths that must stay with the repository (seed content).
_REPO_BOUND_PREFIXES = ("data/sample_docs",)


def detect_data_root() -> Path:
    """Return writable data root (cloud persistence or local repo)."""
    env = os.getenv("PLA_DATA_ROOT", "").strip()
    if env:
        root = Path(env).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root
    if DEFAULT_PERSISTENCE_BASE.is_dir():
        root = DEFAULT_CLOUD_DATA_ROOT
        root.mkdir(parents=True, exist_ok=True)
        return root
    return ROOT


def is_repo_bound_path(relative: str) -> bool:
    rel = relative.replace("\\", "/").lstrip("./")
    return any(rel == p or rel.startswith(p + "/") for p in _REPO_BOUND_PREFIXES)


def resolve_data_path(relative: str) -> Path:
    """Resolve a project-relative data path against PLA_DATA_ROOT / persistence."""
    path = Path(relative)
    if path.is_absolute():
        return path
    if is_repo_bound_path(str(relative)):
        return ROOT / path
    return detect_data_root() / path


class AppConfig(BaseModel):
    name: str = "PrivateLocalAgent"
    team: str = "说干就干"
    track: int = 2
    host: str = "0.0.0.0"
    port: int = 7860


class LLMConfig(BaseModel):
    backend: str = "openai_compatible"
    base_url: str = "https://developer.amd.com.cn/radeon/api/v1"
    api_key_env: str = "RADEON_API_KEY"
    model: str = "Qwen3.6-35B-A3B"
    temperature: float = 0.2
    max_tokens: int = 2048
    local_model_id: str = "Qwen/Qwen2.5-7B-Instruct"
    device: str = "cuda"
    dtype: str = "float16"

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, os.getenv("OPENAI_API_KEY", "EMPTY"))


class RAGConfig(BaseModel):
    persist_dir: str = "data/vector_store"
    collection: str = "private_kb"
    chunk_size: int = 500
    chunk_overlap: int = 80
    top_k: int = 4
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


class AgentConfig(BaseModel):
    max_steps: int = 6
    enable_tools: bool = True
    enable_memory: bool = True
    memory_path: str = "data/memory/session.json"


class PathsConfig(BaseModel):
    upload_dir: str = "data/uploads"
    sample_docs: str = "data/sample_docs"
    generated_projects: str = "data/generated_projects"


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    def resolve(self, relative: str) -> Path:
        return resolve_data_path(relative)

    def data_root(self) -> Path:
        return detect_data_root()


def load_settings(config_path: str | Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    # Optional cloud overlay: configs/radeon_cloud.yaml (paths still relative; root via PLA_DATA_ROOT)
    path = Path(config_path) if config_path else ROOT / "configs" / "default.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    overlay = os.getenv("PLA_CONFIG_OVERLAY", "").strip()
    if not overlay and DEFAULT_PERSISTENCE_BASE.is_dir():
        candidate = ROOT / "configs" / "radeon_cloud.yaml"
        if candidate.exists():
            overlay = str(candidate)
    if overlay:
        op = Path(overlay).expanduser().resolve()
        configs_root = (ROOT / "configs").resolve()
        try:
            op.relative_to(configs_root)
        except ValueError:
            print(f"[config] ignoring overlay outside configs/: {op}", flush=True)
            op = Path()
        if op.exists() and op.is_file():
            with op.open("r", encoding="utf-8") as f:
                extra = yaml.safe_load(f) or {}
            data = _deep_merge(data, extra)
    return Settings.model_validate(data)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out
