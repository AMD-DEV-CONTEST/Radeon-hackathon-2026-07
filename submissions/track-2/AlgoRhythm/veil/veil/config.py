"""VEIL configuration.

Every tunable lives here so the fallback ladder (Part 3, §5.1) is a one-line
edit at hour 20 rather than a code hunt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class InferenceConfig:
    # vLLM is bound to loopback deliberately: only the app port is tunnelled.
    base_url: str = os.getenv("VEIL_VLLM_URL", "http://127.0.0.1:8000/v1")
    model: str = os.getenv("VEIL_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")
    api_key: str = "not-used-but-openai-client-requires-one"
    max_tokens: int = 1024
    temperature: float = 0.2          # low: we want recall, not creativity
    request_timeout_s: float = 180.0


@dataclass
class OrchestratorConfig:
    # Persona count is set from the measured concurrency knee, not a guess.
    # See bench/benchmark.py --sweep.
    max_concurrent_personas: int = 5
    max_iterations: int = 3
    per_persona_tool_call_budget: int = 2


@dataclass
class StorageConfig:
    db_path: str = os.getenv("VEIL_DB", "veil_state.db")
    qdrant_path: str = os.getenv("VEIL_QDRANT", "./qdrant_data")
    collection: str = "auxiliary_corpus"
    embedding_model: str = os.getenv(
        "VEIL_EMBEDDING_MODEL",
        os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bge-small-en-v1.5-local"))
    )


@dataclass
class SecurityConfig:
    # Hard egress allowlist. Anything not on this list raises. See
    # security/egress.py — this is the structural guarantee, not a promise.
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    session_ttl_minutes: int = 120
    purge_on_session_end: bool = True


@dataclass
class Config:
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    app_port: int = int(os.getenv("VEIL_PORT", "7860"))


CONFIG = Config()
