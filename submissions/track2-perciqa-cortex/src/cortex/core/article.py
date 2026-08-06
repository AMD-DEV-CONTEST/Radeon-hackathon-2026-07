from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from cortex.core.types import ArticleId


class ArticleType(StrEnum):
    FINDING = "finding"
    INSIGHT = "insight"
    PRECEDENT = "precedent"
    PROCEDURE = "procedure"
    WARNING = "warning"
    ACTIVITY = "activity"


class Scope(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    PARTNER = "partner"

    @classmethod
    def _missing_(cls, value: object) -> Scope | None:
        if isinstance(value, str) and value.startswith("partner:"):
            member = str.__new__(cls, value)
            member._value_ = value  # noqa: SLF001
            return member
        return None

    @classmethod
    def partner(cls, org_did: str) -> Scope:
        return cls(f"partner:{org_did}")


@dataclass(frozen=True)
class Provenance:
    producer_agent: str
    producer_org: str
    run_id: str
    timestamp: datetime
    computation_ref: str | None = None
    source_data_hash: str | None = None
    source_data_schema: str | None = None


_MAX_CONTENT_CHARS = 2000


@dataclass(frozen=True)
class MemoryArticle:
    id: ArticleId
    type: ArticleType
    content: str
    payload: Mapping[str, Any]
    provenance: Provenance
    scope: Scope
    agent_signature: bytes
    topic: str = "*"
    schema_version: str = "1.0"
    embedding: list[float] | None = None
    embedding_model: str | None = None
    org_signature: bytes | None = None
    cites: tuple[ArticleId, ...] = ()
    trust_score: float | None = None
    trust_expiration: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            object.__setattr__(self, "scope", Scope(self.scope))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "cites", tuple(self.cites))
        if len(self.content) > _MAX_CONTENT_CHARS:
            raise ValueError(
                f"content exceeds {_MAX_CONTENT_CHARS} chars "
                f"(got {len(self.content)})"
            )

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "payload": dict(self.payload),
            "topic": self.topic,
            "schema_version": self.schema_version,
            "scope": str(self.scope),
            "agent_signature": self.agent_signature.hex(),
            "cites": list(self.cites),
        }
        if self.embedding is not None:
            d["embedding"] = self.embedding
        if self.embedding_model is not None:
            d["embedding_model"] = self.embedding_model
        if self.org_signature is not None:
            d["org_signature"] = self.org_signature.hex()
        if self.trust_score is not None:
            d["trust_score"] = self.trust_score
        if self.trust_expiration is not None:
            d["trust_expiration"] = self.trust_expiration.isoformat()
        p = self.provenance
        d["provenance"] = {
            "producer_agent": p.producer_agent,
            "producer_org": p.producer_org,
            "run_id": p.run_id,
            "timestamp": p.timestamp.isoformat(),
        }
        if p.computation_ref is not None:
            d["provenance"]["computation_ref"] = p.computation_ref
        if p.source_data_hash is not None:
            d["provenance"]["source_data_hash"] = p.source_data_hash
        if p.source_data_schema is not None:
            d["provenance"]["source_data_schema"] = p.source_data_schema
        return d

    @staticmethod
    def from_dict(d: dict) -> MemoryArticle:
        ts = d.get("timestamp") or d.get("provenance", {}).get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        pd = d.get("provenance", d)
        prov = Provenance(
            producer_agent=pd.get("producer_agent", ""),
            producer_org=pd.get("producer_org", ""),
            run_id=pd.get("run_id", ""),
            timestamp=ts,
            computation_ref=pd.get("computation_ref"),
            source_data_hash=pd.get("source_data_hash"),
            source_data_schema=pd.get("source_data_schema"),
        )
        scope_val = d.get("scope", "private")
        scope = scope_val if isinstance(scope_val, Scope) else Scope(scope_val)
        exp = d.get("trust_expiration")
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        return MemoryArticle(
            id=d.get("id", ""),
            type=ArticleType(d.get("type", "finding")),
            content=d.get("content", ""),
            payload=d.get("payload", {}),
            provenance=prov,
            scope=scope,
            topic=d.get("topic", "*"),
            schema_version=d.get("schema_version", "1.0"),
            agent_signature=(bytes.fromhex(d["agent_signature"])
                             if d.get("agent_signature") else b""),
            embedding=d.get("embedding"),
            embedding_model=d.get("embedding_model"),
            org_signature=bytes.fromhex(d["org_signature"]) if d.get("org_signature") else None,
            cites=d.get("cites", []),
            trust_score=d.get("trust_score"),
            trust_expiration=exp,
        )
