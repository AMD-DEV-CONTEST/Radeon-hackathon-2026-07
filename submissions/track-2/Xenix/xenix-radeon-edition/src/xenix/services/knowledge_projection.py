from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


RETRIEVAL_PROJECTION_VERSION = 3
CORPUS_FINGERPRINT_SCHEMA = 3

_PROJECTION_FINGERPRINT_DOMAIN = "xenix.knowledge-projection/v3"
_CORPUS_FINGERPRINT_DOMAIN = "xenix.knowledge-corpus/v3"
_UNIT_ID_DOMAIN = "xenix.knowledge-unit/v3"


@dataclass(frozen=True)
class KnowledgeProjectionMetadata:
    document_id: str
    retrieval_generation_id: str
    projection_version: int
    content_fingerprint: str
    unit_count: int


@dataclass(frozen=True)
class KnowledgeProjectionUnit:
    id: str
    document_id: str
    canonical_generation_id: str
    ordinal: int
    text: str


@dataclass(frozen=True)
class KnowledgeProjectionIdentity:
    """Bounded authority for one exact retrieval corpus revision."""

    metadata: tuple[KnowledgeProjectionMetadata, ...]

    @property
    def corpus_fingerprint(self) -> str:
        return corpus_fingerprint(self.metadata)

    @property
    def unit_count(self) -> int:
        return sum(item.unit_count for item in self.metadata)

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(
            knowledge_unit_id(
                document_id=item.document_id,
                canonical_generation_id=item.retrieval_generation_id,
                ordinal=ordinal,
                projection_version=item.projection_version,
            )
            for item in sorted(self.metadata, key=lambda value: value.document_id)
            for ordinal in range(item.unit_count)
        )


@dataclass(frozen=True)
class KnowledgeProjectionSnapshot:
    """One frozen SQLite view used throughout a vector build."""

    identity: KnowledgeProjectionIdentity
    units: tuple[KnowledgeProjectionUnit, ...]

    def __post_init__(self) -> None:
        actual_ids = tuple(unit.id for unit in self.units)
        if actual_ids != self.identity.unit_ids:
            raise ValueError("Knowledge projection units do not match their identity.")


def knowledge_unit_id(
    *,
    document_id: str,
    canonical_generation_id: str,
    ordinal: int,
    projection_version: int = RETRIEVAL_PROJECTION_VERSION,
) -> str:
    """Derive row identity from the retrieval projection authority."""

    payload = json.dumps(
        {
            "canonical_generation_id": canonical_generation_id,
            "document_id": document_id,
            "ordinal": int(ordinal),
            "projection_version": int(projection_version),
            "schema": _UNIT_ID_DOMAIN,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ku_" + hashlib.sha256(payload).hexdigest()


def retrieval_content_fingerprint(
    units: Iterable[tuple[int, str, Mapping[str, object]]],
) -> str:
    """Fingerprint one derived text projection without depending on row ids."""

    digest = hashlib.sha256()
    digest.update(_PROJECTION_FINGERPRINT_DOMAIN.encode("ascii"))
    for ordinal, text, locator in units:
        payload = {
            "locator": dict(locator),
            "ordinal": int(ordinal),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def corpus_fingerprint(metadata: Sequence[KnowledgeProjectionMetadata]) -> str:
    """Fingerprint current corpus state using bounded per-document metadata only."""

    payload = {
        "schema": _CORPUS_FINGERPRINT_DOMAIN,
        "documents": [
            {
                "content_fingerprint": item.content_fingerprint,
                "document_id": item.document_id,
                "projection_version": item.projection_version,
                "retrieval_generation_id": item.retrieval_generation_id,
                "unit_count": item.unit_count,
            }
            for item in sorted(metadata, key=lambda value: value.document_id)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CORPUS_FINGERPRINT_SCHEMA",
    "KnowledgeProjectionIdentity",
    "KnowledgeProjectionMetadata",
    "KnowledgeProjectionSnapshot",
    "KnowledgeProjectionUnit",
    "RETRIEVAL_PROJECTION_VERSION",
    "corpus_fingerprint",
    "knowledge_unit_id",
    "retrieval_content_fingerprint",
]
