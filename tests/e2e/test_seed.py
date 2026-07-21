import asyncio
import contextlib
import json
import socket
import textwrap
from pathlib import Path

import pytest

from cortex.broker.server import BrokerServer
from cortex.node.node import CortexNode
from cortex.sdk.client import CortexClient


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _generate_key(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p.write_bytes(pem); p.chmod(0o600)
    return p


def _write_node_cfg(p, org, agent, keys, b_url, reg):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"""\
node:
  org_did: {org}
  agent_did: {agent}
  key_paths:
    org: {keys['org']}
    agent: {keys['agent']}
broker: {{url: {b_url}, registry: {reg}, replay_window_sec: 600}}
embedder: {{model: BAAI/bge-small-en-v1.5, backend: cpu, batch_size: 4, fallback_on_oom: true}}
vector_index: {{backend: hnswlib, metric: cosine, hnsw: {{M: 16, ef_construction: 100, ef_search: 32}}}}
trust: {{default_org_reputation: 0.85, reputation_overrides: {{}}, half_life_days: 90, min_trust_default: 0.3}}
query: {{default_top_k: 5, deadline_ms: 4000, min_trust: 0.0}}
logging: {{level: WARNING, file: {p.parent / 'n.log'}}}
""")


@pytest.mark.asyncio
async def test_seed_publishes_ten_findings(tmp_path):
    from scenarios.soc_consortium.seed import seed_articles

    bp = _free_port()
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({
        "did:percq:org:soc-alpha": {"pubkey": "A", "name": "Alpha", "topics": ["*"]},
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta", "topics": ["*"]},
    }))
    broker = BrokerServer(registry_path=reg, host="127.0.0.1", port=bp)
    btask = asyncio.create_task(broker.serve())
    await asyncio.sleep(0.05)
    b_url = f"ws://127.0.0.1:{bp}"

    ka = {"org": _generate_key(tmp_path / "alpha" / "org.pem"),
          "agent": _generate_key(tmp_path / "alpha" / "agent.pem")}
    kb = {"org": _generate_key(tmp_path / "beta" / "org.pem"),
          "agent": _generate_key(tmp_path / "beta" / "agent.pem")}
    ca = tmp_path / "a" / "cfg.yaml"
    cb = tmp_path / "b" / "cfg.yaml"
    _write_node_cfg(ca, "did:percq:org:soc-alpha", "did:percq:agent:alpha-bot-1", ka, b_url, reg)
    _write_node_cfg(cb, "did:percq:org:soc-beta", "did:percq:agent:beta-bot-1", kb, b_url, reg)

    na = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                    key_paths=ka, broker_url=b_url, config_path=ca,
                    embedder_backend_override="cpu")
    nb = CortexNode(org_did="did:percq:org:soc-beta", agent_did="did:percq:agent:beta-bot-1",
                    key_paths=kb, broker_url=b_url, config_path=cb,
                    embedder_backend_override="cpu")
    await na.start()
    await nb.start()
    await asyncio.sleep(0.05)

    try:
        ids = seed_articles(na, nb)
        assert len(ids) == 10, f"expected 10 new article_ids, got {len(ids)}"

        all_results = []
        for n in (na, nb):
            client = CortexClient(n)
            results = client.search("", scopes={"public"}, top_k=20, min_trust=0.0)
            all_results.extend(results)
        seen = {r.article_id for r in all_results}
        assert len(seen) == 10, f"saw {len(seen)} unique articles across both nodes"
    finally:
        await na.stop()
        await nb.stop()
        await broker.stop()
        btask.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await btask
