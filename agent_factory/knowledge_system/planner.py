from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.knowledge_system.loaders import SourceDiscovery
from agent_factory.knowledge_system.schema import (
    KnowledgeIngestionPlan,
    KnowledgeLimits,
    KnowledgeSplitterRule,
    MountMode,
    SourceType,
)
from agent_factory.models import get_task_model


KNOWLEDGE_PLANNER_MAX_ATTEMPTS = 3
MAX_SAMPLE_DOCUMENTS = 8
MAX_SAMPLE_CHARS = 900


KNOWLEDGE_PLANNER_SYSTEM = """You design a safe, reproducible document chunking plan for a RAG ingestion pipeline.

You do not write code. You only choose from the allowed splitter enum and numeric chunk parameters.

Planning policy:
- Prefer structure-preserving splitters when the document format exposes structure.
- Markdown or RST should usually use markdown.
- Code files should use code.
- JSON should use json.
- PDFs and generic prose usually use recursive.
- Larger conceptual documents usually need larger chunks.
- Dense API/reference/code documents usually need moderate chunks with useful overlap.
- Keep overlap much smaller than chunk size.
- Produce rules only when they are useful; otherwise rely on defaults.
- Return JSON only and obey the schema exactly."""


def plan_knowledge_ingestion(
    *,
    source_type: SourceType,
    mount_mode: MountMode,
    discovery: SourceDiscovery,
    limits: KnowledgeLimits,
    metadata: dict[str, Any] | None = None,
    model: object | None = None,
) -> KnowledgeIngestionPlan:
    if mount_mode != "rag":
        return _default_plan(limits=limits, rationale="index_only sources do not require semantic chunk planning.")
    task_model = model or get_task_model()
    if task_model is None:
        plan = _default_plan(limits=limits, rationale="task model is not configured; using deterministic default splitters.")
        return plan.model_copy(update={"warnings": ["task_model_not_configured"]})
    structured = task_model.with_structured_output(KnowledgeIngestionPlan, method="json_mode").with_config(
        tags=["nostream"]
    )
    messages = [
        SystemMessage(content=KNOWLEDGE_PLANNER_SYSTEM),
        HumanMessage(
            content=json.dumps(
                {
                    "source_type": source_type,
                    "mount_mode": mount_mode,
                    "limits": limits.model_dump(mode="json", exclude={"splitter_overrides"}),
                    "metadata": metadata or {},
                    "file_type_counts": discovery.file_type_counts,
                    "sample_documents": _sample_documents(discovery),
                    "allowed_splitters": ["recursive", "markdown", "code", "json"],
                    "output_json_schema": KnowledgeIngestionPlan.model_json_schema(),
                },
                ensure_ascii=False,
                indent=2,
            )
        ),
    ]
    last_error: Exception | None = None
    for attempt in range(1, KNOWLEDGE_PLANNER_MAX_ATTEMPTS + 1):
        try:
            plan = structured.invoke(messages)
            return _bounded_plan(plan, limits=limits).model_copy(update={"planner": "task_model"})
        except Exception as exc:
            last_error = exc
            if attempt >= KNOWLEDGE_PLANNER_MAX_ATTEMPTS:
                break
            messages.append(
                HumanMessage(
                    content=(
                        "The previous ingestion plan failed validation.\n"
                        "Regenerate the full JSON only, obeying every schema constraint.\n"
                        f"Validation observation from attempt {attempt}/{KNOWLEDGE_PLANNER_MAX_ATTEMPTS}:\n"
                        f"{type(exc).__name__}: {exc}\n\n"
                        f"Output JSON schema:\n{json.dumps(KnowledgeIngestionPlan.model_json_schema(), ensure_ascii=False)}"
                    )
                )
            )
    fallback = _default_plan(limits=limits, rationale="task model planning failed; using deterministic default splitters.")
    return fallback.model_copy(update={"warnings": [f"planner_failed: {type(last_error).__name__}: {last_error}"]})


def _sample_documents(discovery: SourceDiscovery) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for document in discovery.documents[:MAX_SAMPLE_DOCUMENTS]:
        samples.append(
            {
                "title": document.title,
                "uri": document.uri,
                "document_type": document.document_type,
                "content_chars": len(document.content),
                "metadata": document.metadata,
                "sample": document.content[:MAX_SAMPLE_CHARS],
            }
        )
    return samples


def _default_plan(*, limits: KnowledgeLimits, rationale: str) -> KnowledgeIngestionPlan:
    rules = [
        KnowledgeSplitterRule(match="md", splitter="markdown", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="markdown", splitter="markdown", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="json", splitter="json", chunk_size=limits.chunk_size, chunk_overlap=0),
        KnowledgeSplitterRule(match="py", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="ts", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="tsx", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="js", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="jsx", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="java", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="go", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="rs", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
        KnowledgeSplitterRule(match="sql", splitter="code", chunk_size=limits.chunk_size, chunk_overlap=limits.chunk_overlap),
    ]
    return KnowledgeIngestionPlan(
        planner="system_default",
        default_splitter="recursive",
        default_chunk_size=limits.chunk_size,
        default_chunk_overlap=limits.chunk_overlap,
        rules=rules,
        rationale=rationale,
    )


def _bounded_plan(plan: KnowledgeIngestionPlan, *, limits: KnowledgeLimits) -> KnowledgeIngestionPlan:
    default_overlap = min(plan.default_chunk_overlap, plan.default_chunk_size - 1)
    rules = []
    for rule in plan.rules:
        overlap = min(rule.chunk_overlap, rule.chunk_size - 1)
        rules.append(rule.model_copy(update={"chunk_overlap": overlap}))
    return plan.model_copy(
        update={
            "default_chunk_overlap": default_overlap,
            "rules": rules,
            "warnings": list(plan.warnings),
        }
    )
