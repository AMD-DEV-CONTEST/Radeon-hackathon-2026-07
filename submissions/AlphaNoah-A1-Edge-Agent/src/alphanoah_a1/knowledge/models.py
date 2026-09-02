"""Data-only knowledge objects and bounded analysis context."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Self

_DOCUMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_CONTEXT_VERSION = "knowledge-context-v1"
_RETRIEVAL_METADATA_LIMITS = {
    "event_types": 300,
    "asset_ids": 300,
    "asset_types": 300,
    "locations": 300,
    "keywords": 100,
}


class KnowledgeDocumentType(StrEnum):
    """Stable first-version classification for enterprise knowledge."""

    SOP = "SOP"
    EQUIPMENT_MANUAL = "EQUIPMENT_MANUAL"
    HISTORICAL_CASE = "HISTORICAL_CASE"
    RULE = "RULE"
    OTHER = "OTHER"


class KnowledgeDocumentStatus(StrEnum):
    """Minimal lifecycle state used by normal retrieval."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One retrieval-neutral, versioned knowledge asset."""

    id: str
    title: str
    content: str
    document_type: KnowledgeDocumentType
    source: str
    version: str
    effective_date: str
    metadata: dict[str, Any] = field(default_factory=dict)
    knowledge_key: str | None = None
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.ACTIVE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or _DOCUMENT_ID_PATTERN.fullmatch(self.id) is None
        ):
            raise ValueError("knowledge document id is invalid")
        self._require_text(self.title, "title", 300)
        self._require_text(self.content, "content", 20_000)
        self._require_text(self.source, "source", 300)
        self._require_text(self.version, "version", 100)
        try:
            document_type = KnowledgeDocumentType(self.document_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("document_type is invalid") from exc
        knowledge_key = (
            self.id if self.knowledge_key is None else self.knowledge_key
        )
        if (
            not isinstance(knowledge_key, str)
            or _DOCUMENT_ID_PATTERN.fullmatch(knowledge_key) is None
        ):
            raise ValueError("knowledge_key is invalid")
        try:
            status = KnowledgeDocumentStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("knowledge document status is invalid") from exc
        try:
            date.fromisoformat(self.effective_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("effective_date must be an ISO date") from exc
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        try:
            encoded_metadata = json.dumps(
                dict(self.metadata),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            if len(encoded_metadata.encode("utf-8")) > 16_384:
                raise ValueError("metadata exceeds 16384 bytes")
            metadata_copy = json.loads(encoded_metadata)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("metadata must be JSON serializable") from exc
        if not isinstance(metadata_copy, dict) or any(
            not isinstance(key, str) for key in metadata_copy
        ):
            raise ValueError("metadata keys must be strings")
        self._validate_retrieval_metadata(metadata_copy)
        object.__setattr__(self, "document_type", document_type)
        object.__setattr__(self, "metadata", metadata_copy)
        object.__setattr__(self, "knowledge_key", knowledge_key)
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe defensive representation."""

        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "document_type": self.document_type.value,
            "source": self.source,
            "version": self.version,
            "effective_date": self.effective_date,
            "knowledge_key": self.knowledge_key,
            "status": self.status.value,
            "metadata": json.loads(
                json.dumps(
                    self.metadata,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build one document from the exact version-one JSON shape."""

        if not isinstance(data, Mapping):
            raise ValueError("knowledge document must be an object")
        required = {
            "id",
            "title",
            "content",
            "document_type",
            "source",
            "version",
            "effective_date",
        }
        missing = sorted(required - set(data))
        extra = sorted(
            set(data) - required - {"metadata", "knowledge_key", "status"}
        )
        if missing:
            raise ValueError(
                "knowledge document missing fields: " + ", ".join(missing)
            )
        if extra:
            raise ValueError(
                "knowledge document has unknown fields: " + ", ".join(extra)
            )
        return cls(
            id=data["id"],
            title=data["title"],
            content=data["content"],
            document_type=data["document_type"],
            source=data["source"],
            version=data["version"],
            effective_date=data["effective_date"],
            metadata=data.get("metadata", {}),
            knowledge_key=data.get("knowledge_key"),
            status=data.get("status", KnowledgeDocumentStatus.ACTIVE.value),
        )

    @staticmethod
    def _require_text(value: object, field_name: str, maximum: int) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > maximum
            or "\x00" in value
        ):
            raise ValueError(
                f"{field_name} must be a trimmed non-empty string "
                f"of at most {maximum} characters"
            )

    @staticmethod
    def _validate_retrieval_metadata(metadata: dict[str, Any]) -> None:
        for field_name, maximum in _RETRIEVAL_METADATA_LIMITS.items():
            if field_name not in metadata:
                continue
            values = metadata[field_name]
            if (
                not isinstance(values, list)
                or len(values) > 50
                or any(
                    not isinstance(value, str)
                    or not value
                    or value != value.strip()
                    or len(value) > maximum
                    or "\x00" in value
                    for value in values
                )
            ):
                raise ValueError(
                    f"metadata.{field_name} must be an array of at most "
                    f"50 trimmed strings up to {maximum} characters"
                )


@dataclass(frozen=True, slots=True)
class KnowledgeContext:
    """A bounded, immutable set of knowledge selected for one Event."""

    documents: tuple[KnowledgeDocument, ...] = ()
    version: str = _CONTEXT_VERSION

    def __post_init__(self) -> None:
        documents = tuple(self.documents)
        if len(documents) > 10 or any(
            not isinstance(item, KnowledgeDocument) for item in documents
        ):
            raise ValueError(
                "knowledge context must contain at most 10 documents"
            )
        if any(
            document.status is not KnowledgeDocumentStatus.ACTIVE
            for document in documents
        ):
            raise ValueError(
                "knowledge context may contain only active documents"
            )
        knowledge_keys = [document.knowledge_key for document in documents]
        if len(knowledge_keys) != len(set(knowledge_keys)):
            raise ValueError(
                "knowledge context has multiple active documents "
                "for one knowledge_key"
            )
        if (
            not isinstance(self.version, str)
            or not self.version
            or len(self.version) > 100
        ):
            raise ValueError("knowledge context version is invalid")
        object.__setattr__(self, "documents", documents)

    def to_prompt_payload(self) -> list[dict[str, Any]]:
        """Project only explicit document fields into a model prompt."""

        return [
            {
                "id": document.id,
                "title": document.title,
                "content": document.content,
                "document_type": document.document_type.value,
                "source": document.source,
                "version": document.version,
                "effective_date": document.effective_date,
                "status": document.status.value,
            }
            for document in self.documents
        ]

    def audit_metadata(self) -> dict[str, Any]:
        """Return provenance without storing knowledge content."""

        return {
            "knowledge_sources": [
                f"{document.source}@{document.version}"
                for document in self.documents
            ],
            "knowledge_version": self.version,
            "context_count": len(self.documents),
            "knowledge_statuses": [
                f"{document.id}:{document.status.value}"
                for document in self.documents
            ],
        }
