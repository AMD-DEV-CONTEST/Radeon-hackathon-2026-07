from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, TypeAlias

ArticleId: TypeAlias = str
AgentDID: TypeAlias = str
OrgDID: TypeAlias = str


class ArticleType(StrEnum):
    FINDING = "finding"
    INSIGHT = "insight"
    PRECEDENT = "precedent"
    PROCEDURE = "procedure"
    WARNING = "warning"


@dataclass(frozen=True)
class Scope:
    value: str

    PRIVATE: ClassVar[str] = "private"
    PUBLIC: ClassVar[str] = "public"

    @classmethod
    def partner(cls, org_did: str) -> Scope:
        return cls(value=f"partner:{org_did}")

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Scope):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)

    def __str__(self) -> str:
        return self.value


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
    payload: dict
    provenance: Provenance
    scope: Scope
    agent_signature: bytes
    schema_version: str = "1.0"
    embedding: list[float] | None = None
    embedding_model: str | None = None
    org_signature: bytes | None = None
    cites: list[ArticleId] = None  # type: ignore[assignment]
    trust_score: float | None = None
    trust_expiration: datetime | None = None

    def __post_init__(self) -> None:
        if self.cites is None:
            object.__setattr__(self, "cites", [])
        if len(self.content) > _MAX_CONTENT_CHARS:
            raise ValueError(
                f"content exceeds {_MAX_CONTENT_CHARS} chars "
                f"(got {len(self.content)})"
            )
