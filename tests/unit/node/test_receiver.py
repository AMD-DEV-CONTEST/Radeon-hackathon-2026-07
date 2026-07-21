from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.core.errors import CanonicalMismatchError, SignatureVerificationError
from cortex.node.receiver import receive_publish_envelope


class RegistryStub:
    def __init__(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.agent_priv = Ed25519PrivateKey.generate()
        self.org_priv = Ed25519PrivateKey.generate()
        self.agent_pub_pem = self.agent_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.org_pub_pem = self.org_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def lookup(self, did: str) -> bytes:
        return self.org_pub_pem


def make_registry() -> RegistryStub:
    return RegistryStub()


def test_tampered_canonical_raises_canonical_mismatch(tmp_path: Path) -> None:
    reg = make_registry()
    from cryptography.hazmat.primitives import serialization

    from cortex.core.canonical import article_canonical_bytes, compute_article_id
    from cortex.core.crypto import sign
    priv = reg.agent_priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    prov = Provenance(producer_agent="did:percq:agent:x", producer_org="did:percq:org:other",
                      computation_ref=None, source_data_hash="h",
                      source_data_schema=None, run_id="r",
                      timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
    art = MemoryArticle(id="", type=ArticleType.FINDING, content="hello",
                       payload={"k": "v"}, embedding=None, embedding_model=None,
                       provenance=prov, scope="public", agent_signature=b"",
                       org_signature=None, cites=[], trust_score=None, trust_expiration=None)
    canonical = article_canonical_bytes(art)
    from dataclasses import replace
    priv_str = priv.decode("utf-8")
    art = replace(art, agent_signature=sign(canonical, priv_str), id=compute_article_id(canonical))
    tampered = replace(art, content="hello world")
    store = SimpleNamespace(event_log_append=lambda *_: None, set_state=lambda *_, **__: None, put=lambda *_, **__: None)
    with pytest.raises((CanonicalMismatchError, SignatureVerificationError)):
        receive_publish_envelope(tampered, canonical, reg, store)
