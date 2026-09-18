"""Retrieval schemas."""

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class RetrievedEvidence(StrictSchema):
    document_id: str
    chunk_id: str
    content: str = Field(min_length=1, max_length=100_000)
    score: float = Field(ge=0, le=1)
    source: str = Field(min_length=1, max_length=2000)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
