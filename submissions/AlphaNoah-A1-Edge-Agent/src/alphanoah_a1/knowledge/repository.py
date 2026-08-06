"""Standard-library JSON storage and retrieval compatibility adapter."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from .models import KnowledgeDocument, KnowledgeDocumentStatus
from .retrieval import KnowledgeMatch, KnowledgeQuery

_SCHEMA_VERSION = "knowledge-repository-v1"


class KnowledgeRepository(Protocol):
    """Storage port kept independent from Runtime and retrieval method."""

    def add_document(self, document: KnowledgeDocument) -> None:
        """Persist one unique knowledge document."""

        ...

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        """Return one document by identity, if present."""

        ...

    def list_documents(self) -> list[KnowledgeDocument]:
        """Return all documents in deterministic identity order."""

        ...


class JsonKnowledgeRepository:
    """Small local JSON repository; no embeddings or remote lookup."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._documents: dict[str, KnowledgeDocument] = {}
        if self.path.exists():
            self._load()

    def add_document(self, document: KnowledgeDocument) -> None:
        if not isinstance(document, KnowledgeDocument):
            raise TypeError("document must be a KnowledgeDocument")
        if document.id in self._documents:
            raise ValueError(
                f"knowledge document already exists: {document.id}"
            )
        self._validate_active_document(document, self._documents.values())
        self._documents[document.id] = self._copy(document)
        try:
            self._write()
        except Exception:
            self._documents.pop(document.id, None)
            raise

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        document = self._documents.get(document_id)
        return self._copy(document) if document is not None else None

    def list_documents(self) -> list[KnowledgeDocument]:
        return [
            self._copy(self._documents[document_id])
            for document_id in sorted(self._documents)
        ]

    def search(
        self,
        *,
        event_type: str = "",
        asset_id: str = "",
        asset_type: str = "",
        location: str = "",
        keywords: Iterable[str] = (),
        limit: int = 5,
    ) -> list[KnowledgeDocument]:
        """Compatibility entry point for the Task 04.5B-1 call shape."""

        return self.search_query(
            KnowledgeQuery(
                event_type=self._query_text(event_type, "event_type"),
                asset_id=self._query_text(asset_id, "asset_id"),
                asset_type=self._query_text(asset_type, "asset_type"),
                location=self._query_text(location, "location"),
                keywords=self._normalized_keywords(keywords),
                limit=limit,
            )
        )

    def search_query(
        self,
        query: KnowledgeQuery,
    ) -> list[KnowledgeDocument]:
        """Compatibility projection from matches to documents."""

        return [match.document for match in self.retrieve(query)]

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeMatch]:
        """Compatibility adapter to the deterministic retriever."""

        from .deterministic import DeterministicKnowledgeRetriever

        return DeterministicKnowledgeRetriever(self).retrieve(query)

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(
                f"invalid knowledge repository: {self.path.name}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError("knowledge repository must be an object")
        unknown = set(payload) - {
            "schema_version",
            "documents",
            "data_notice",
        }
        if unknown:
            raise ValueError(
                "unknown knowledge repository fields: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError(
                f"knowledge repository schema must be {_SCHEMA_VERSION}"
            )
        data_notice = payload.get("data_notice")
        if data_notice is not None and (
            not isinstance(data_notice, str) or not data_notice.strip()
        ):
            raise ValueError("knowledge repository data_notice is invalid")
        raw_documents = payload.get("documents")
        if not isinstance(raw_documents, list):
            raise ValueError("knowledge repository documents must be an array")
        documents: dict[str, KnowledgeDocument] = {}
        for raw_document in raw_documents:
            document = KnowledgeDocument.from_dict(raw_document)
            if document.id in documents:
                raise ValueError(
                    f"duplicate knowledge document id: {document.id}"
                )
            documents[document.id] = document
        self._validate_active_families(documents.values())
        self._documents = documents

    def _write(self) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "data_notice": (
                "Local reviewed knowledge repository; content provenance "
                "must be validated before production use."
            ),
            "documents": [
                self._documents[document_id].to_dict()
                for document_id in sorted(self._documents)
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(encoded)
                temporary.write("\n")
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _normalized_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
        if isinstance(keywords, (str, bytes)):
            raise ValueError("keywords must be an iterable of strings")
        normalized: list[str] = []
        for keyword in keywords:
            if not isinstance(keyword, str):
                raise ValueError("keywords must contain only strings")
            folded = keyword.strip().casefold()
            if len(folded) >= 2 and folded not in normalized:
                normalized.append(folded)
            if len(normalized) >= 30:
                break
        return tuple(normalized)

    @staticmethod
    def _query_text(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} search value must be a string")
        return value.strip()

    @staticmethod
    def _copy(document: KnowledgeDocument) -> KnowledgeDocument:
        return KnowledgeDocument.from_dict(document.to_dict())

    @staticmethod
    def _validate_active_document(
        candidate: KnowledgeDocument,
        existing_documents: Iterable[KnowledgeDocument],
    ) -> None:
        if candidate.status is not KnowledgeDocumentStatus.ACTIVE:
            return
        for existing in existing_documents:
            if (
                existing.status is KnowledgeDocumentStatus.ACTIVE
                and existing.knowledge_key == candidate.knowledge_key
            ):
                raise ValueError(
                    "multiple active documents for knowledge_key: "
                    + candidate.knowledge_key
                )

    @staticmethod
    def _validate_active_families(
        documents: Iterable[KnowledgeDocument],
    ) -> None:
        active_keys: set[str] = set()
        for document in sorted(documents, key=lambda item: item.id):
            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                continue
            if document.knowledge_key in active_keys:
                raise ValueError(
                    "multiple active documents for knowledge_key: "
                    + document.knowledge_key
                )
            active_keys.add(document.knowledge_key)
