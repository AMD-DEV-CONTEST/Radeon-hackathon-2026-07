import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cortex.core.article import (
    ArticleType,
    MemoryArticle,
    Provenance,
    Scope,
)
from cortex.core.canonical import (
    article_canonical_bytes,
    compute_article_id,
)
from cortex.core.crypto import (
    did_for_agent,
    did_for_org,
    generate_agent_keypair,
    generate_org_keypair,
    sign,
    verify,
)


def test_full_core_roundtrip():
    agent_priv, agent_pub = generate_agent_keypair()
    org_priv, org_pub = generate_org_keypair()

    agent_did = did_for_agent("00000000-0000-4000-8000-000000000000")
    org_did = did_for_org("soc-alpha")

    prov = Provenance(
        producer_agent=agent_did,
        producer_org=org_did,
        computation_ref="run://42",
        source_data_hash="aa" * 32,
        source_data_schema="sensor.v1",
        run_id="run-1",
        timestamp=datetime(2026, 7, 15, 12, 34, 56, 789012, tzinfo=UTC),
    )

    draft = MemoryArticle(
        id="",  # not yet known
        type=ArticleType.FINDING,
        content="Anomalous temperature spike detected in sector 7.",
        payload={"sector": 7, "delta_c": 4.3},
        provenance=prov,
        scope=Scope.PUBLIC,
        agent_signature=b"",
    )

    canonical = article_canonical_bytes(draft)
    article_id = compute_article_id(canonical)
    assert len(article_id) == 64

    agent_sig = sign(canonical, agent_priv)
    org_sig = sign(canonical, org_priv)

    signed = MemoryArticle(
        id=article_id,
        type=draft.type,
        content=draft.content,
        payload=draft.payload,
        provenance=draft.provenance,
        scope=draft.scope,
        agent_signature=agent_sig,
        org_signature=org_sig,
        cites=[],
    )

    verified_canonical = article_canonical_bytes(signed)
    assert verified_canonical == canonical, "canonical must be stable post-signing"
    assert compute_article_id(verified_canonical) == article_id, "id must be stable"

    assert verify(verified_canonical, signed.agent_signature, agent_pub) is True
    assert verify(verified_canonical, signed.org_signature, org_pub) is True

    bad = bytearray(agent_sig)
    bad[0] ^= 0xFF
    assert verify(verified_canonical, bytes(bad), agent_pub) is False

    assert "agent_signature" not in verified_canonical.decode("utf-8")
    assert "org_signature" not in verified_canonical.decode("utf-8")
    assert '"id"' not in verified_canonical.decode("utf-8")
