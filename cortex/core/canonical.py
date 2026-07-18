from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

_UTF8 = "utf-8"


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=UTC)
        obj = obj.astimezone(UTC)
        return obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    raise TypeError(f"Object of type {type(obj).__name__} is not canonicalizable")


def canonical_bytes(signed_fields: dict) -> bytes:
    """JCS-like (RFC 8785-ish) canonical JSON bytes.

    Sorted keys (UTF-8 byte order), no insignificant whitespace,
    shortest round-trippable floats, datetimes as UTC ISO-8601 with Z.
    """
    return (
        json.dumps(
            signed_fields,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        )
        .encode(_UTF8)
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_article_id(canonical: bytes) -> str:
    return sha256_hex(canonical)


def article_canonical_bytes(article) -> bytes:
    """Serialize ONLY the signed fields of a MemoryArticle.

    Excluded (derived/unsigned): id, embedding, embedding_model,
    agent_signature, org_signature, trust_score, trust_expiration.
    Included: schema_version, type, content, payload, provenance,
    scope, cites.
    """
    p = article.provenance
    signed = {
        "schema_version": article.schema_version,
        "type": article.type.value,
        "content": article.content,
        "payload": article.payload,
        "provenance": {
            "producer_agent": p.producer_agent,
            "producer_org": p.producer_org,
            "computation_ref": p.computation_ref,
            "source_data_hash": p.source_data_hash,
            "source_data_schema": p.source_data_schema,
            "run_id": p.run_id,
            "timestamp": p.timestamp,
        },
        "scope": article.scope.value
        if hasattr(article.scope, "value")
        else str(article.scope),
        "cites": list(article.cites),
    }
    return canonical_bytes(signed)
