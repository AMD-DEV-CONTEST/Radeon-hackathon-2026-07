from datetime import UTC, datetime
from pathlib import Path

import pytest

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.node import CortexNode
from tests.unit.node.test_node_publish import FakeBroker, make_keys  # noqa: F401


@pytest.mark.asyncio
async def test_private_never_emits_envelope(cfg: Path, tmp_path: Path) -> None:
    keys = make_keys(tmp_path); broker = FakeBroker()
    node = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                      key_paths=keys, broker_url="ws://localhost:7432", config_path=cfg,
                      embedder_backend_override="cpu")
    node._broker_override = broker
    await node.start()
    prov = Provenance(producer_agent="did:percq:agent:alpha-bot-1",
                      producer_org="did:percq:org:soc-alpha",
                      computation_ref=None, source_data_hash=None,
                      source_data_schema=None, run_id="r",
                      timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
    art = MemoryArticle(id="", type=ArticleType.FINDING, content="secret",
                       payload={}, embedding=None, embedding_model=None, provenance=prov,
                       scope="private", agent_signature=b"", org_signature=None,
                       cites=[], trust_score=None, trust_expiration=None)
    node.publish(art)
    assert broker.published == []
    await node.stop()


def test_load_keys_refuses_world_readable(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from cortex.node.keys import load_keys
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(encoding=serialization.Encoding.PEM,
                          format=serialization.PrivateFormat.PKCS8,
                          encryption_algorithm=serialization.NoEncryption())
    p = tmp_path / "k.pem"; p.write_bytes(pem)
    try:
        p.chmod(0o644)
    except PermissionError:
        pytest.skip("cannot set world-readable on this FS")
    with pytest.raises(PermissionError):
        load_keys(p, p)
