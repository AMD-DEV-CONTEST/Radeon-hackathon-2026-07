import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.node import CortexNode


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def connect(self) -> None: pass
    async def stop(self) -> None: pass
    async def publish_envelope(self, env: dict) -> None:
        self.published.append(env)
    async def query_fanout(self, env: dict) -> dict:
        return {"type": "query_result", "results": []}


def make_keys(tmp_path: Path) -> dict[str, Path]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    out = {}
    for label in ("org", "agent"):
        k = Ed25519PrivateKey.generate()
        pem = k.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        p = tmp_path / f"{label}.pem"
        p.write_bytes(pem); p.chmod(0o600)
        out[label] = p
    return out


@pytest.mark.asyncio
async def test_publish_public_persists_and_sends_envelope(cfg: Path, tmp_path: Path) -> None:
    keys = make_keys(tmp_path)
    broker = FakeBroker()
    node = CortexNode(
        org_did="did:percq:org:soc-alpha",
        agent_did="did:percq:agent:alpha-bot-1",
        key_paths=keys,
        broker_url="ws://localhost:7432",
        config_path=cfg,
        embedder_backend_override="cpu",
    )
    node._broker_override = broker
    await node.start()
    prov = Provenance(
        producer_agent="did:percq:agent:alpha-bot-1",
        producer_org="did:percq:org:soc-alpha",
        computation_ref=None, source_data_hash="h",
        source_data_schema="cve-record-v1", run_id="r1",
        timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )
    art = MemoryArticle(
        id="", type=ArticleType.FINDING, content="APT29 uses encoded PowerShell T1059.001",
        payload={"attack_id": "T1059.001"}, embedding=None, embedding_model=None,
        provenance=prov, scope="public",
        agent_signature=b"", org_signature=None,
        cites=[], trust_score=None, trust_expiration=None,
    )
    art_id = node.publish(art)
    assert art_id
    await asyncio.sleep(0.05)
    row = node.store.get(art_id)
    assert row["state"] == "published"
    assert row["scope"] == "public"
    assert len(broker.published) == 1
    assert broker.published[0]["type"] == "publish"
    await node.stop()


@pytest.mark.asyncio
async def test_publish_private_never_sends_envelope(cfg: Path, tmp_path: Path) -> None:
    keys = make_keys(tmp_path)
    broker = FakeBroker()
    node = CortexNode(
        org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
        key_paths=keys, broker_url="ws://localhost:7432", config_path=cfg,
        embedder_backend_override="cpu",
    )
    node._broker_override = broker
    await node.start()
    prov = Provenance(
        producer_agent="did:percq:agent:alpha-bot-1", producer_org="did:percq:org:soc-alpha",
        computation_ref=None, source_data_hash=None, source_data_schema=None, run_id="r",
        timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )
    art = MemoryArticle(
        id="", type=ArticleType.FINDING, content="private finding",
        payload={}, embedding=None, embedding_model=None, provenance=prov,
        scope="private", agent_signature=b"", org_signature=None,
        cites=[], trust_score=None, trust_expiration=None,
    )
    art_id = node.publish(art)
    row = node.store.get(art_id)
    assert row["state"] == "indexed"
    assert broker.published == []
    await node.stop()
