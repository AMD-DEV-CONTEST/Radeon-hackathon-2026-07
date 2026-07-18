import textwrap
from pathlib import Path

from cortex.node.config import NodeConfig, load_config


def test_load_config_yaml_round_trip(tmp_path: Path) -> None:
    yaml = textwrap.dedent("""\
        node:
          org_did: did:percq:org:soc-alpha
          agent_did: did:percq:agent:alpha-bot-1
          key_paths:
            org: ./keys/org_ed25519.pem
            agent: ./keys/agent_ed25519.pem
        broker:
          url: wss://broker.local:7432
          registry: ./registry/org_registry.json
          replay_window_sec: 600
        embedder:
          model: BAAI/bge-small-en-v1.5
          backend: auto
          batch_size: 16
          fallback_on_oom: true
        vector_index:
          backend: faiss-gpu
          metric: cosine
          hnsw:
            M: 32
            ef_construction: 200
            ef_search: 64
        trust:
          default_org_reputation: 0.5
          reputation_overrides:
            did:percq:org:soc-alpha: 0.85
            did:percq:org:soc-beta: 0.78
          half_life_days: 90
          min_trust_default: 0.3
        query:
          default_top_k: 5
          deadline_ms: 400
          min_trust: 0.3
        logging:
          level: INFO
          file: ./logs/node.log
    """)
    p = tmp_path / "config.yaml"
    p.write_text(yaml)
    cfg = load_config(p)
    assert isinstance(cfg, NodeConfig)
    assert cfg.node.org_did == "did:percq:org:soc-alpha"
    assert cfg.embedder.backend == "auto"
    assert cfg.embedder.batch_size == 16
    assert cfg.trust.reputation_overrides["did:percq:org:soc-alpha"] == 0.85
    assert cfg.vector_index.hnsw.M == 32


def test_env_override_embed_backend_cpu(tmp_path: Path, monkeypatch) -> None:
    yaml = textwrap.dedent("""\
        node:
          org_did: did:percq:org:soc-alpha
          agent_did: did:percq:agent:alpha-bot-1
          key_paths: {org: ./o.pem, agent: ./a.pem}
        broker: {url: wss://b.local:7432, registry: ./r.json, replay_window_sec: 600}
        embedder: {model: bge-small-en-v1.5, backend: auto, batch_size: 16, fallback_on_oom: true}
        vector_index: {backend: faiss-gpu, metric: cosine, hnsw: {M: 32, ef_construction: 200, ef_search: 64}}
        trust: {default_org_reputation: 0.5, reputation_overrides: {}, half_life_days: 90, min_trust_default: 0.3}
        query: {default_top_k: 5, deadline_ms: 400, min_trust: 0.3}
        logging: {level: INFO, file: ./logs/node.log}
    """)
    p = tmp_path / "config.yaml"
    p.write_text(yaml)
    monkeypatch.setenv("CORTEX_EMBED_BACKEND", "cpu")
    monkeypatch.setenv("CORTEX_BROKER_URL", "wss://override.local:9000")
    monkeypatch.setenv("CORTEX_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CORTEX_BENCH_ENABLED", "1")
    cfg = load_config(p)
    assert cfg.embedder.backend == "cpu"
    assert cfg.broker.url == "wss://override.local:9000"
    assert cfg.logging.level == "DEBUG"
    assert cfg.bench_enabled is True
