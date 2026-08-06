from datetime import UTC, datetime
from pathlib import Path

import pytest

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.node import CortexNode
from tests.unit.node.test_node_publish import FakeBroker, make_keys  # noqa: F401


@pytest.mark.asyncio
async def test_query_returns_closest(cfg: Path, tmp_path: Path) -> None:
    keys = make_keys(tmp_path)
    broker = FakeBroker()
    node = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                     key_paths=keys, broker_url="ws://localhost:7432", config_path=cfg,
                     embedder_backend_override="cpu")
    node._broker_override = broker
    await node.start()
    contents = ["APT29 uses encoded powershell", "lateral movement via SMB admin shares",
                "kernel exploit CVE-2026-1337 read write"]
    for i, content in enumerate(contents):
        prov = Provenance(
            producer_agent="did:percq:agent:alpha-bot-1",
            producer_org="did:percq:org:soc-alpha",
            computation_ref=None, source_data_hash="h",
            source_data_schema="cve-record-v1", run_id=f"r{i}",
            timestamp=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC),
        )
        art = MemoryArticle(
            id="", type=ArticleType.FINDING, content=content,
            payload={}, embedding=None, embedding_model=None, provenance=prov,
            scope="public", agent_signature=b"", org_signature=None,
            cites=[], trust_score=None, trust_expiration=None,
        )
        node.publish(art)
    results = node.query("powershell obfuscation", topic_filter=[], scope_filter=["public"],
                         top_k=3, min_trust=0.0, deadline_ms=400)
    assert len(results) >= 1
    assert "powershell" in results[0].article.content.lower()
    await node.stop()
