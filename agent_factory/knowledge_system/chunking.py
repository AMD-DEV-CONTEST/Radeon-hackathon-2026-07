from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from agent_factory.knowledge_system.loaders import sha256_text
from agent_factory.knowledge_system.schema import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestionPlan,
    KnowledgeLimits,
    KnowledgeSplitterRule,
    SplitterKind,
)


@dataclass(frozen=True, slots=True)
class SplitterPlan:
    splitter: SplitterKind
    chunk_size: int
    chunk_overlap: int
    language: str | None = None


def chunk_document(
    *,
    source_id: str,
    document: KnowledgeDocument,
    content: str,
    limits: KnowledgeLimits,
    ingestion_plan: KnowledgeIngestionPlan | None = None,
) -> list[KnowledgeChunk]:
    plan = _resolve_splitter_plan(document=document, limits=limits, ingestion_plan=ingestion_plan)
    parts = _split_content(content=content, plan=plan)
    chunks: list[KnowledgeChunk] = []
    cursor = 0
    for index, part in enumerate(parts):
        text = part.page_content.strip()
        if not text:
            continue
        start = content.find(text, cursor)
        if start < 0:
            start = cursor
        end = start + len(text)
        cursor = max(end - plan.chunk_overlap, end)
        chunk_id = f"{source_id}:{document.document_id}:{index:05d}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                document_id=document.document_id,
                title=document.title,
                content=text,
                content_hash=sha256_text(text),
                chunk_index=index,
                position={
                    "line_start": content.count("\n", 0, start) + 1,
                    "line_end": content.count("\n", 0, end) + 1,
                },
                summary=text[:240],
                metadata={**dict(document.metadata), **dict(part.metadata or {}), "splitter": plan.splitter},
            )
        )
    return chunks


def _resolve_splitter_plan(
    *,
    document: KnowledgeDocument,
    limits: KnowledgeLimits,
    ingestion_plan: KnowledgeIngestionPlan | None,
) -> SplitterPlan:
    document_type = str(document.document_type or "").lower()
    file_type = str((document.metadata or {}).get("file_type") or "").lower()
    source_type = str((document.metadata or {}).get("source_type") or "").lower()
    rule = _matching_rule(
        ingestion_plan=ingestion_plan,
        document_type=document_type,
        file_type=file_type,
        source_type=source_type,
    )
    if rule is not None:
        splitter = rule.splitter
        chunk_size = rule.chunk_size
        chunk_overlap = rule.chunk_overlap
    elif ingestion_plan is not None:
        splitter = ingestion_plan.default_splitter
        chunk_size = ingestion_plan.default_chunk_size
        chunk_overlap = ingestion_plan.default_chunk_overlap
    else:
        splitter = None
        chunk_size = None
        chunk_overlap = None
    key_candidates = [document_type, file_type, source_type, "default"]
    override = next((limits.splitter_overrides.get(key) for key in key_candidates if key in limits.splitter_overrides), None)
    splitter = override.splitter if override is not None else splitter
    splitter = splitter or _default_splitter(document_type=document_type, file_type=file_type)
    chunk_size = override.chunk_size if override is not None and override.chunk_size is not None else chunk_size
    chunk_size = chunk_size or limits.chunk_size
    chunk_overlap = override.chunk_overlap if override is not None and override.chunk_overlap is not None else chunk_overlap
    chunk_overlap = limits.chunk_overlap if chunk_overlap is None else chunk_overlap
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    return SplitterPlan(
        splitter=splitter,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        language=_language_for(document_type=document_type, file_type=file_type),
    )


def _matching_rule(
    *,
    ingestion_plan: KnowledgeIngestionPlan | None,
    document_type: str,
    file_type: str,
    source_type: str,
) -> KnowledgeSplitterRule | None:
    if ingestion_plan is None:
        return None
    candidates = {item for item in [document_type, file_type, source_type] if item}
    for rule in ingestion_plan.rules:
        if rule.match in candidates:
            return rule
    return None


def _split_content(*, content: str, plan: SplitterPlan) -> list[Document]:
    text = content.strip()
    if not text:
        return []
    if len(text) <= plan.chunk_size:
        return [Document(page_content=text, metadata={"splitter_kind": "single_chunk"})]
    try:
        return _split_with_langchain(text=text, plan=plan)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "RAG chunking requires langchain-text-splitters. Install project dependencies before indexing long documents."
        ) from exc


def _split_with_langchain(*, text: str, plan: SplitterPlan) -> list[Document]:
    if plan.splitter == "markdown":
        splitter = _text_splitters_module().MarkdownTextSplitter(chunk_size=plan.chunk_size, chunk_overlap=plan.chunk_overlap)
        return splitter.create_documents([text])
    if plan.splitter == "json":
        return _split_json_with_langchain(text=text, plan=plan)
    if plan.splitter == "code" and plan.language:
        splitters = _text_splitters_module()
        language = getattr(splitters.Language, plan.language)
        splitter = splitters.RecursiveCharacterTextSplitter.from_language(
            language=language,
            chunk_size=plan.chunk_size,
            chunk_overlap=plan.chunk_overlap,
        )
        return splitter.create_documents([text])
    splitter = _text_splitters_module().RecursiveCharacterTextSplitter(
        chunk_size=plan.chunk_size,
        chunk_overlap=plan.chunk_overlap,
    )
    return splitter.create_documents([text])


def _split_json_with_langchain(*, text: str, plan: SplitterPlan) -> list[Document]:
    try:
        json_splitter = _text_splitters_module().RecursiveJsonSplitter
    except (ImportError, AttributeError):
        splitter = _text_splitters_module().RecursiveCharacterTextSplitter(
            chunk_size=plan.chunk_size,
            chunk_overlap=plan.chunk_overlap,
        )
        return splitter.create_documents([text])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        splitter = _text_splitters_module().RecursiveCharacterTextSplitter(
            chunk_size=plan.chunk_size,
            chunk_overlap=plan.chunk_overlap,
        )
        return splitter.create_documents([text])
    splitter = json_splitter(max_chunk_size=plan.chunk_size)
    try:
        documents = splitter.create_documents(texts=[data])
    except TypeError:
        split_texts = splitter.split_text(json_data=data)
        documents = [Document(page_content=item, metadata={"splitter_kind": "json"}) for item in split_texts]
    if not plan.chunk_overlap or len(documents) <= 1:
        return documents
    return documents


def _default_splitter(*, document_type: str, file_type: str) -> SplitterKind:
    key = document_type or file_type
    if key in {"md", "markdown", "rst"}:
        return "markdown"
    if key in {"json"}:
        return "json"
    if _language_for(document_type=document_type, file_type=file_type):
        return "code"
    return "recursive"


def _language_for(*, document_type: str, file_type: str) -> str | None:
    key = document_type or file_type
    return {
        "py": "PYTHON",
        "python": "PYTHON",
        "js": "JS",
        "jsx": "JS",
        "ts": "TS",
        "tsx": "TS",
        "java": "JAVA",
        "go": "GO",
        "rs": "RUST",
        "rust": "RUST",
        "sql": "SQL",
    }.get(key)


def _text_splitters_module():
    return importlib.import_module("langchain_text_splitters")
