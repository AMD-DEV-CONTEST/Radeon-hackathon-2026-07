"""Manifest validation, article-aware ingestion, and SQLite corpus storage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

from app.schemas.legal import LegalChunk, LegalDocument, LegalStatus

CORPUS_SCHEMA_VERSION = 2
ARTICLE_PATTERN = re.compile(
    r"(?m)^(第[零〇一二三四五六七八九十百千万0-9]+条"
    r"(?:之[零〇一二三四五六七八九十百千万0-9]+)?)\s*"
)
ITEM_PATTERN = re.compile(r"^[（(]([零〇一二三四五六七八九十百千万0-9]+)[）)]")


def clean_legal_text(text: str) -> str:
    """Normalize downloaded official text without changing legal wording."""

    normalized = text.replace("\ufeff", "").replace("\u3000", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line)


def split_legal_text(
    text: str, *, page_or_location: str = "official source text"
) -> list[dict[str, str | None]]:
    """Split official full text into article/paragraph/item-aware records.

    The curated manifest remains the auditable submission corpus. This helper is
    used by importers when an official endpoint exposes stable full text.
    """

    cleaned = clean_legal_text(text)
    matches = list(ARTICLE_PATTERN.finditer(cleaned))
    if not matches:
        return (
            [
                {
                    "article_no": None,
                    "paragraph_no": None,
                    "item_no": None,
                    "page_or_location": page_or_location,
                    "text": cleaned,
                }
            ]
            if cleaned
            else []
        )
    sections: list[dict[str, str | None]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        body = cleaned[match.end() : end].strip()
        paragraphs = [part.strip() for part in body.split("\n") if part.strip()]
        if not paragraphs:
            paragraphs = [""]
        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            item_match = ITEM_PATTERN.match(paragraph)
            sections.append(
                {
                    "article_no": match.group(1),
                    "paragraph_no": (
                        f"第{paragraph_index}款" if len(paragraphs) > 1 else None
                    ),
                    "item_no": (f"第{item_match.group(1)}项" if item_match else None),
                    "page_or_location": page_or_location,
                    "text": paragraph,
                }
            )
    return sections


def load_manifest(path: Path | str) -> tuple[list[LegalDocument], list[LegalChunk]]:
    manifest_path = Path(path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ValueError("Unsupported legal manifest schema version.")
    retrieved_at = raw["retrieved_at"]
    documents: list[LegalDocument] = []
    chunks: list[LegalChunk] = []
    seen_document_ids: set[str] = set()
    seen_chunk_hashes: set[str] = set()
    for item in raw.get("documents", []):
        sections = item.get("sections") or []
        if not sections:
            raise ValueError(f"{item.get('document_id')} has no curated sections.")
        document_payload = {
            key: value
            for key, value in item.items()
            if key not in {"sections", "verification_url"}
        }
        document_payload["text_source_url"] = item.get(
            "text_source_url", item["source_url"]
        )
        canonical_sections = json.dumps(
            sections, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        document_payload["retrieved_at"] = retrieved_at
        document_payload["raw_path"] = str(manifest_path)
        document_payload["content_hash"] = hashlib.sha256(
            canonical_sections.encode("utf-8")
        ).hexdigest()
        document = LegalDocument.model_validate(document_payload)
        if document.document_id in seen_document_ids:
            raise ValueError(f"Duplicate document_id: {document.document_id}")
        seen_document_ids.add(document.document_id)
        documents.append(document)
        for section in sections:
            chunk = LegalChunk.build(document=document, **section)
            if chunk.content_hash in seen_chunk_hashes:
                continue
            seen_chunk_hashes.add(chunk.content_hash)
            chunks.append(chunk)
    _reject_overlapping_effective_versions(documents)
    return documents, chunks


def _reject_overlapping_effective_versions(documents: list[LegalDocument]) -> None:
    by_title: dict[str, list[LegalDocument]] = {}
    for document in documents:
        if document.status is LegalStatus.EFFECTIVE:
            by_title.setdefault(document.title, []).append(document)
    for title, versions in by_title.items():
        ordered = sorted(versions, key=lambda item: item.effective_date)
        for older, newer in zip(ordered, ordered[1:], strict=False):
            if older.expiry_date is None or older.expiry_date > newer.effective_date:
                raise ValueError(
                    f"Effective versions overlap for {title}: "
                    f"{older.version} / {newer.version}"
                )


class LegalCorpusStore:
    """Persistent lexical source of truth; Qdrant is a rebuildable derivative."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS corpus_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legal_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legal_chunks (
                    source_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL
                        REFERENCES legal_documents(document_id) ON DELETE CASCADE,
                    content_hash TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_legal_document_status
                    ON legal_documents(status);
                CREATE INDEX IF NOT EXISTS idx_legal_chunk_document
                    ON legal_chunks(document_id);
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO corpus_meta(key, value) VALUES('version', ?)",
                (str(CORPUS_SCHEMA_VERSION),),
            )

    def replace(
        self, documents: Iterable[LegalDocument], chunks: Iterable[LegalChunk]
    ) -> dict[str, int]:
        self.initialize()
        document_list = list(documents)
        chunk_list = list(chunks)
        with self.transaction() as db:
            db.execute("DELETE FROM legal_chunks")
            db.execute("DELETE FROM legal_documents")
            db.executemany(
                """
                INSERT INTO legal_documents(
                    document_id, title, version, status, content_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.document_id,
                        item.title,
                        item.version,
                        item.status.value,
                        item.content_hash,
                        item.model_dump_json(),
                    )
                    for item in document_list
                ],
            )
            db.executemany(
                """
                INSERT INTO legal_chunks(
                    source_id, document_id, content_hash, text, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.source_id,
                        item.document_id,
                        item.content_hash,
                        item.text,
                        item.model_dump_json(),
                    )
                    for item in chunk_list
                ],
            )
        return {"documents": len(document_list), "chunks": len(chunk_list)}

    def list_chunks(
        self,
        *,
        as_of: date | None = None,
        jurisdiction: str | None = None,
        status: LegalStatus | None = LegalStatus.EFFECTIVE,
        document_types: set[str] | None = None,
    ) -> list[LegalChunk]:
        self.initialize()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT payload_json FROM legal_chunks ORDER BY source_id"
            ).fetchall()
        chunks = [LegalChunk.model_validate_json(row["payload_json"]) for row in rows]
        filtered: list[LegalChunk] = []
        for chunk in chunks:
            if jurisdiction and chunk.jurisdiction != jurisdiction:
                continue
            if status and chunk.status is not status:
                continue
            if document_types and chunk.document_type.value not in document_types:
                continue
            if as_of and (
                chunk.effective_date > as_of
                or (chunk.expiry_date is not None and as_of >= chunk.expiry_date)
            ):
                continue
            filtered.append(chunk)
        return filtered

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self.transaction() as db:
            documents = db.execute(
                "SELECT COUNT(*) AS count FROM legal_documents"
            ).fetchone()["count"]
            chunks = db.execute(
                "SELECT COUNT(*) AS count FROM legal_chunks"
            ).fetchone()["count"]
        return {"documents": int(documents), "chunks": int(chunks)}

    def get_chunk(self, source_id: str) -> LegalChunk:
        with self.transaction() as db:
            row = db.execute(
                "SELECT payload_json FROM legal_chunks WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return LegalChunk.model_validate_json(row["payload_json"])
