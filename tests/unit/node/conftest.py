import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""\
        node:
          org_did: did:percq:org:soc-alpha
          agent_did: did:percq:agent:alpha-bot-1
          key_paths:
            org: {tmp_path / 'org.pem'}
            agent: {tmp_path / 'agent.pem'}
        broker: {{url: ws://localhost:7432, registry: {tmp_path / 'reg.json'}, replay_window_sec: 600}}
        embedder: {{model: BAAI/bge-small-en-v1.5, backend: cpu, batch_size: 4, fallback_on_oom: true}}
        vector_index: {{backend: hnswlib, metric: cosine, hnsw: {{M: 16, ef_construction: 100, ef_search: 32}}}}
        trust: {{default_org_reputation: 0.85, reputation_overrides: {{}}, half_life_days: 90, min_trust_default: 0.3}}
        query: {{default_top_k: 5, deadline_ms: 400, min_trust: 0.3}}
        logging: {{level: INFO, file: {tmp_path / 'node.log'}}}
    """))
    return p
