from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class NodeSection:
    org_did: str = ""
    agent_did: str = ""
    key_paths: dict[str, str] = field(default_factory=dict)


@dataclass
class BrokerSection:
    url: str = ""
    registry: str = ""
    replay_window_sec: int = 600


@dataclass
class EmbedderSection:
    model: str = "BAAI/bge-small-en-v1.5"
    backend: str = "auto"
    batch_size: int = 16
    fallback_on_oom: bool = True


@dataclass
class HnswSection:
    M: int = 32
    ef_construction: int = 200
    ef_search: int = 64


@dataclass
class VectorIndexSection:
    backend: str = "faiss-gpu"
    metric: str = "cosine"
    hnsw: HnswSection = field(default_factory=HnswSection)


@dataclass
class TrustSection:
    default_org_reputation: float = 0.5
    reputation_overrides: dict[str, float] = field(default_factory=dict)
    half_life_days: int = 90
    min_trust_default: float = 0.3


@dataclass
class QuerySection:
    default_top_k: int = 5
    deadline_ms: int = 400
    min_trust: float = 0.3


@dataclass
class LoggingSection:
    level: str = "INFO"
    file: str = "./logs/node.log"


@dataclass
class NodeConfig:
    node: NodeSection = field(default_factory=NodeSection)
    broker: BrokerSection = field(default_factory=BrokerSection)
    embedder: EmbedderSection = field(default_factory=EmbedderSection)
    vector_index: VectorIndexSection = field(default_factory=VectorIndexSection)
    trust: TrustSection = field(default_factory=TrustSection)
    query: QuerySection = field(default_factory=QuerySection)
    logging: LoggingSection = field(default_factory=LoggingSection)
    bench_enabled: bool = False


def _merge(target: Any, src: dict[str, Any]) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and hasattr(target, k):
            child = getattr(target, k)
            if isinstance(child, dict):
                child.update(v)
            else:
                _merge(child, v)
        elif hasattr(target, k):
            setattr(target, k, v)


def load_config(path: Path) -> NodeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = NodeConfig()
    _merge(cfg, raw)
    if (v := os.environ.get("CORTEX_BROKER_URL")):
        cfg.broker.url = v
    if (v := os.environ.get("CORTEX_EMBED_BACKEND")):
        cfg.embedder.backend = v
    if (v := os.environ.get("CORTEX_LOG_LEVEL")):
        cfg.logging.level = v
    if (v := os.environ.get("CORTEX_BENCH_ENABLED")):
        cfg.bench_enabled = v not in ("", "0", "false", "False")
    return cfg
