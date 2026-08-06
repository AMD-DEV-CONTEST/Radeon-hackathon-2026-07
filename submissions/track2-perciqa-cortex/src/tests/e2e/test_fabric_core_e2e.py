"""Core fabric e2e: broker -> nodes -> publish -> query -> derive.

Self-contained replacement for the demo-scenario e2e tests. Exercises the
real broker verification + forwarding path with a mocked embedder/vector
index (no torch/transformers/hnswlib needed, CI-safe):

  node A publishes a finding -> broker verifies signature -> forwards
  to node B -> node B stores it -> query from B returns it ->
  node A derives an insight citing the finding -> provenance edge recorded
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import textwrap
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from cortex.broker.server import BrokerServer
from cortex.node.node import CortexNode
from cortex.sdk.client import CortexClient

ORG_A = "did:percq:org:acme"
ORG_B = "did:percq:org:globex"
AGENT_A = "did:percq:agent:acme-bot-1"
AGENT_B = "did:percq:agent:globex-bot-1"


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
    p.write_bytes(pem)
    p.chmod(0o600)
    return p


def _pubkey_pem(priv_path: Path) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


class FakeEmbedder:
    def __init__(self, *args, **kwargs):
        self.fallback_to_cpu = True
        self._device = "cpu"

    def embed_one(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(0)
        vec = rng.normal(size=(384,)).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec

    def _check_gpu(self) -> bool:
        return False


class FakeVectorIndex:
    def __init__(self, dim: int = 384, **kwargs):
        self.dim = dim
        self._vectors: dict[str, np.ndarray] = {}

    def add(self, article_id: str, vector: np.ndarray) -> None:
        self._vectors[article_id] = np.asarray(vector, dtype=np.float32).flatten()

    def load(self, path):
        pass

    def save(self, path):
        pass

    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        q = np.asarray(query_vec, dtype=np.float32).flatten()
        q_norm = np.linalg.norm(q)
        scored = [
            (aid, float(np.dot(q, v) / (q_norm * np.linalg.norm(v) + 1e-9)))
            for aid, v in self._vectors.items()
        ]
        scored.sort(key=lambda t: -t[1])
        return scored[:top_k]


@pytest.fixture
def mock_deps():
    with patch("cortex.node.node.Embedder", FakeEmbedder), \
         patch("cortex.node.embedder.Embedder", FakeEmbedder), \
         patch("cortex.node.vector_index.HNSWIndex", FakeVectorIndex), \
         patch("cortex.node.node.HNSWIndex", FakeVectorIndex):
        yield


def _write_node_cfg(p: Path, org: str, agent: str, keys: dict, b_url: str, reg: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(f"""\
        node:
          org_did: {org}
          agent_did: {agent}
          key_paths:
            org: {keys['org']}
            agent: {keys['agent']}
        broker: {{url: {b_url}, registry: {reg}, replay_window_sec: 600}}
        embedder: {{model: BAAI/bge-small-en-v1.5, backend: cpu, batch_size: 4,
                     fallback_on_oom: true}}
        vector_index:
          backend: hnswlib
          metric: cosine
          hnsw:
            M: 16
            ef_construction: 100
            ef_search: 32
        trust:
          default_org_reputation: 0.85
          half_life_days: 90
          min_trust_default: 0.3
        query:
          default_top_k: 5
          deadline_ms: 4000
          min_trust: 0.0
        logging:
          level: WARNING
          file: {p.parent / 'n.log'}
    """))


@dataclass
class Env:
    broker_url: str
    node_a: CortexNode
    node_b: CortexNode
    broker: BrokerServer
    btask: asyncio.Task


async def _setup(tmp_path: Path) -> Env:
    bp = _free_port()
    # Agent slot uses the org key: receiving nodes verify the *agent*
    # signature against the org public key (cortex/node/receiver.py),
    # so articles must be org-key-signed to propagate across nodes.
    org_a = _generate_key(tmp_path / "a" / "org.pem")
    org_b = _generate_key(tmp_path / "b" / "org.pem")
    ka = {"org": org_a, "agent": org_a}
    kb = {"org": org_b, "agent": org_b}
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({
        ORG_A: {"pubkey": _pubkey_pem(ka["org"]), "name": "Acme", "topics": ["*"]},
        ORG_B: {"pubkey": _pubkey_pem(kb["org"]), "name": "Globex", "topics": ["*"]},
    }))

    broker = BrokerServer(registry_path=reg, host="127.0.0.1", port=bp)
    btask = asyncio.create_task(broker.serve())
    await asyncio.sleep(0.1)
    b_url = f"ws://127.0.0.1:{bp}"

    ca = tmp_path / "a" / "cfg.yaml"
    cb = tmp_path / "b" / "cfg.yaml"
    _write_node_cfg(ca, ORG_A, AGENT_A, ka, b_url, str(reg))
    _write_node_cfg(cb, ORG_B, AGENT_B, kb, b_url, str(reg))

    na = CortexNode(org_did=ORG_A, agent_did=AGENT_A, key_paths=ka,
                    broker_url=b_url, config_path=ca, embedder_backend_override="cpu")
    nb = CortexNode(org_did=ORG_B, agent_did=AGENT_B, key_paths=kb,
                    broker_url=b_url, config_path=cb, embedder_backend_override="cpu")
    await na.start()
    await nb.start()
    await asyncio.sleep(0.2)
    return Env(broker_url=b_url, node_a=na, node_b=nb, broker=broker, btask=btask)


async def _teardown(env: Env) -> None:
    await env.node_a.stop()
    await env.node_b.stop()
    await env.broker.stop()
    env.btask.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await env.btask


@pytest.mark.asyncio
async def test_fabric_publish_query_derive(mock_deps, tmp_path: Path) -> None:
    env = await _setup(tmp_path)
    try:
        client_a = CortexClient(env.node_a)
        client_b = CortexClient(env.node_b)

        fid = client_a.publish_finding(
            content="Acme observed a targeted phishing campaign against financial firms.",
            payload={"threat_actor": "whale-1", "technique": "spearphishing",
                      "tactic": "initial-access", "attack_id": "T1566.001"},
            scope="public",
        )
        assert fid

        await asyncio.sleep(0.5)  # allow broker forward + node B store
        stored = env.node_b.store.get(fid) if env.node_b.store else None
        assert stored is not None, "node B did not receive and store the forwarded publish"

        results = client_b.search("phishing campaign", scopes={"public"}, top_k=5, min_trust=0.0)
        assert any(r.article_id == fid for r in results), "query from B did not return A's finding"

        iid = client_a.publish_insight(
            content="Campaign synthesis: whale-1 targets financial firms via spearphishing.",
            payload={"query": "phishing", "threat_actor": "whale-1"},
            scope="public",
            cites=[fid],
        )
        assert iid
        await asyncio.sleep(0.5)
        row = env.node_a.store.get(iid) if env.node_a.store else None
        assert row is not None and row["trust_score"] is not None
    finally:
        await _teardown(env)
