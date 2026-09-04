"""Versioned legal-corpus and citation contracts.

The retrieval layer stores one :class:`LegalChunk` per article/paragraph/item.
Every field needed to decide temporal applicability is carried into Qdrant;
retrieval never infers a document version from its title alone.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LegalStatus(str, Enum):
    EFFECTIVE = "effective"
    EXPIRED = "expired"
    NOT_YET_EFFECTIVE = "not_yet_effective"


class LegalDocumentType(str, Enum):
    LAW = "law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    DEPARTMENT_RULE = "department_rule"
    JUDICIAL_INTERPRETATION = "judicial_interpretation"
    NATIONAL_STANDARD = "national_standard"
    INDUSTRY_STANDARD = "industry_standard"
    OFFICIAL_CASE = "official_case"


class LegalQuoteType(str, Enum):
    """Only verbatim official-source excerpts may enter the legal index."""

    VERBATIM_EXCERPT = "verbatim_excerpt"


class LegalDocument(BaseModel):
    """A source-level record before article-aware chunking."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{2,79}$")
    title: str = Field(min_length=2)
    document_type: LegalDocumentType
    issuer: str = Field(min_length=2)
    jurisdiction: str = Field(min_length=2)
    version: str = Field(min_length=1)
    promulgation_date: date
    effective_date: date
    expiry_date: date | None = None
    status: LegalStatus
    source_url: HttpUrl
    text_source_url: HttpUrl
    retrieved_at: datetime
    raw_path: str
    expected_title: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_dates_and_status(self) -> "LegalDocument":
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date must be after effective_date")
        return self


class LegalChunk(BaseModel):
    """Uniform storage schema required by the local legal index."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str
    title: str
    document_type: LegalDocumentType
    issuer: str
    jurisdiction: str
    version: str
    promulgation_date: date
    effective_date: date
    expiry_date: date | None = None
    status: LegalStatus
    source_url: HttpUrl
    text_source_url: HttpUrl
    retrieved_at: datetime
    article_no: str | None = None
    paragraph_no: str | None = None
    item_no: str | None = None
    page_or_location: str
    quote_type: LegalQuoteType
    text: str = Field(min_length=2)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_id: str

    @classmethod
    def build(
        cls,
        *,
        document: LegalDocument,
        text: str,
        article_no: str | None,
        paragraph_no: str | None,
        item_no: str | None,
        page_or_location: str,
        quote_type: LegalQuoteType,
        text_source_url: HttpUrl | str | None = None,
    ) -> "LegalChunk":
        normalized = " ".join(text.split())
        digest_payload = "\n".join(
            [
                document.document_id,
                document.version,
                article_no or "",
                paragraph_no or "",
                item_no or "",
                normalized,
            ]
        )
        digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
        return cls(
            **document.model_dump(
                exclude={
                    "raw_path",
                    "expected_title",
                    "content_hash",
                    "text_source_url",
                }
            ),
            article_no=article_no,
            paragraph_no=paragraph_no,
            item_no=item_no,
            page_or_location=page_or_location,
            quote_type=quote_type,
            text_source_url=text_source_url or document.text_source_url,
            text=normalized,
            content_hash=digest,
            source_id=f"LAW-{digest[:20].upper()}",
        )

    def qdrant_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["source_url"] = str(self.source_url)
        payload["text_source_url"] = str(self.text_source_url)
        return payload


class LegalCitation(BaseModel):
    """A complete, verifier-ready citation returned with a legal conclusion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str
    article_no: str | None = None
    paragraph_no: str | None = None
    item_no: str | None = None
    version: str
    effective_date: date
    expiry_date: date | None = None
    status: LegalStatus
    source_id: str
    source_url: HttpUrl
    text_source_url: HttpUrl
    quote_type: LegalQuoteType
    quote: str = Field(min_length=2, max_length=800)
    retrieval_score: float
    document_id: str
    jurisdiction: str
    page_or_location: str

    @classmethod
    def from_chunk(
        cls, chunk: LegalChunk, retrieval_score: float
    ) -> "LegalCitation":
        return cls(
            title=chunk.title,
            article_no=chunk.article_no,
            paragraph_no=chunk.paragraph_no,
            item_no=chunk.item_no,
            version=chunk.version,
            effective_date=chunk.effective_date,
            expiry_date=chunk.expiry_date,
            status=chunk.status,
            source_id=chunk.source_id,
            source_url=chunk.source_url,
            text_source_url=chunk.text_source_url,
            quote_type=chunk.quote_type,
            quote=chunk.text[:800],
            retrieval_score=retrieval_score,
            document_id=chunk.document_id,
            jurisdiction=chunk.jurisdiction,
            page_or_location=chunk.page_or_location,
        )

    def is_applicable(self, as_of: date) -> bool:
        return (
            self.status is LegalStatus.EFFECTIVE
            and self.effective_date <= as_of
            and (self.expiry_date is None or as_of < self.expiry_date)
        )


class LegalConclusion(BaseModel):
    """Fails closed when a model attempts a deterministic uncited conclusion."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    certainty: str = Field(pattern=r"^(deterministic|qualified|unknown)$")
    citations: list[LegalCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def deterministic_requires_citation(self) -> "LegalConclusion":
        if self.certainty == "deterministic" and not self.citations:
            raise ValueError(
                "A deterministic legal conclusion requires at least one citation."
            )
        return self
