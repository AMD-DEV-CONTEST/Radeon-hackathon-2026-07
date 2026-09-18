"""Versioned RAG index identity and deterministic invalidation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import orjson
from pydantic import Field

from buildguard.config import RagConfig
from buildguard.rag.embedding_backend import EmbeddingBackend
from buildguard.schemas.common import StrictSchema
from buildguard.utils.time import utc_now


class IndexManifest(StrictSchema):
    embedding_model: str
    model_revision: str
    tokenizer_revision: str
    model_sha256: str
    pooling: str
    dimension: int = Field(ge=1)
    normalize: bool
    query_instruction_version: str
    chunker_version: str
    source_manifest_sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)

    def identity(self) -> tuple[object, ...]:
        return (
            self.model_revision,
            self.tokenizer_revision,
            self.model_sha256,
            self.pooling,
            self.dimension,
            self.normalize,
            self.query_instruction_version,
            self.chunker_version,
            self.source_manifest_sha256,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_manifest(
    config: RagConfig,
    backend: EmbeddingBackend,
    source_manifest: Path,
    *,
    document_count: int,
    chunk_count: int,
) -> IndexManifest:
    model_name = (
        config.embedding_model_path.name
        if config.embedding_model_path is not None
        else "mock"
    )
    return IndexManifest(
        embedding_model=model_name,
        model_revision=config.embedding_model_revision,
        tokenizer_revision=config.embedding_tokenizer_revision,
        model_sha256=config.embedding_model_sha256,
        pooling=config.embedding_pooling,
        dimension=backend.dimension,
        normalize=config.embedding_normalize,
        query_instruction_version=config.embedding_query_instruction_version,
        chunker_version=config.chunker_version,
        source_manifest_sha256=sha256_file(source_manifest),
        document_count=document_count,
        chunk_count=chunk_count,
    )


def load_manifest(path: Path) -> IndexManifest:
    return IndexManifest.model_validate(orjson.loads(path.read_bytes()))
