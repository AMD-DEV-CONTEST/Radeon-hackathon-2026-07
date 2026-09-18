"""Validate report citations against retrieved local chunks."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.common import StrictSchema


class CitationStatement(StrictSchema):
    """One proposed normative statement and its claimed source."""

    chunk_id: str = Field(min_length=64, max_length=64)
    standard_name: str = Field(min_length=1)
    source_path: Path
    article: str | None = None
    page: int | None = Field(default=None, ge=1)
    quoted_content: str = Field(min_length=1, max_length=4000)


class CitationValidation(StrictSchema):
    statement: CitationStatement
    valid: bool
    errors: list[str] = Field(default_factory=list)


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


class CitationValidator:
    """Only approve claims that exactly map to retrieved evidence metadata."""

    def validate(
        self,
        statements: list[CitationStatement],
        chunks: list[DocumentChunk],
    ) -> list[CitationValidation]:
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        results: list[CitationValidation] = []
        for statement in statements:
            errors: list[str] = []
            chunk = by_id.get(statement.chunk_id)
            if chunk is None:
                errors.append("chunk_id was not present in retrieved evidence")
            else:
                if statement.standard_name != chunk.document_name:
                    errors.append("standard_name does not match the retrieved chunk")
                if statement.article != chunk.article:
                    errors.append("article does not match the retrieved chunk")
                if statement.page != chunk.page:
                    errors.append("page does not match the retrieved chunk")
                if statement.source_path.resolve() != chunk.source_path.resolve():
                    errors.append("source_path does not match the retrieved chunk")
                quote = _normalized_text(statement.quoted_content)
                if quote not in _normalized_text(chunk.content):
                    errors.append("quoted content is not contained in the retrieved chunk")
            results.append(
                CitationValidation(
                    statement=statement,
                    valid=not errors,
                    errors=errors,
                )
            )
        return results
