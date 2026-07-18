from __future__ import annotations

from typing import Any

from cortex.core.canonical import article_canonical_bytes, compute_article_id
from cortex.core.crypto import verify
from cortex.core.errors import CanonicalMismatchError, SignatureVerificationError


def receive_publish_envelope(article: Any, expected_canonical: bytes, registry: Any, store: Any) -> str:
    canonical = article_canonical_bytes(article)
    if canonical != expected_canonical:
        art_id = getattr(article, "id", None) or compute_article_id(canonical)
        event = {"reason": "canonical_mismatch", "article_id": art_id}
        if hasattr(store, "put"):
            store.put(article, state="quarantined")
        if hasattr(store, "event_log_append"):
            store.event_log_append("broker.scope_violation", art_id, event)
        raise CanonicalMismatchError(f"canonical bytes do not match for {art_id}")
    pub_pem = registry.lookup(article.provenance.producer_org)
    if isinstance(pub_pem, bytes):
        pub_pem = pub_pem.decode("utf-8")
    if not verify(canonical, article.agent_signature, pub_pem):
        store.put(article, state="quarantined")
        store.event_log_append("broker.scope_violation", article.id, {"reason": "bad_signature"})
        raise SignatureVerificationError(f"agent signature invalid for {article.id}")
    store.put(article, state="signed")
    store.set_state(article.id, "indexed")
    return article.id
