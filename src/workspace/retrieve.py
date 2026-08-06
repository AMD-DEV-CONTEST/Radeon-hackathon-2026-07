"""Workspace packing: FAISS candidates → scope filtering + budget trimming → ContextPackage."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def retrieve_context(
    ws: Any,
    query: str,
    faiss_candidates: list[dict],
    budget_chars: int = 2000,
    scope: dict | None = None,
) -> dict:
    """Step4: FAISS candidates → scope filtering → budget trimming → ContextPackage.

    Differences from pure Workspace retrieve:
    - no longer relies on the internal candidate recall of retrieve (Lesson 19: the vector store is just one segment of candidate recall)
    - candidates are provided by FAISS ANN retrieval (see rag/retriever.py)
    - here only scope filtering + budget trimming + source/ref annotation are done

    Args:
        ws: Agently Workspace instance
        query: the original query text
        faiss_candidates: candidate list returned by FAISS ANN retrieval
        budget_chars: character budget for packing
        scope: permission/scope filter conditions, e.g. {"tenant_id": "xxx", "allowed_sources": [...]}

    Returns:
        ContextPackage dict (containing items + diagnostics)
    """
    # C3: scope filtering — first filter out failed/unauthorized candidates
    allowed_sources = set(scope.get("allowed_sources", [])) if scope else set()
    tenant_id = scope.get("tenant_id") if scope else None

    filtered_candidates = []
    skipped_failed = 0
    skipped_scope = 0

    for candidate in faiss_candidates:
        # filter 1: evidence_state == failed
        if candidate.get("evidence_state") == "failed":
            skipped_failed += 1
            continue

        # filter 2: scope permission check
        if allowed_sources:
            source = candidate.get("source", "")
            if source and source not in allowed_sources:
                skipped_scope += 1
                continue

        # filter 3: tenant isolation
        if tenant_id:
            cand_tenant = candidate.get("meta", {}).get("tenant_id")
            if cand_tenant and cand_tenant != tenant_id:
                skipped_scope += 1
                continue

        filtered_candidates.append(candidate)

    # pack by budget
    items = []
    total_chars = 0

    for candidate in filtered_candidates:
        if total_chars >= budget_chars:
            break

        chunk_ref = candidate.get("ref", candidate.get("chunk_id", ""))
        chunk_text = candidate.get("chunk_text", "")

        # C3/I4: propagate evidence state and metadata
        evidence_state = candidate.get("evidence_state", "bounded")

        items.append({
            "source": chunk_ref,
            "content": chunk_text,
            "summary": candidate.get("chunk_summary", ""),
            "score": candidate.get("score", 0.0),
            # M2: forward source-data metadata
            "title": candidate.get("title", ""),
            "section_title": candidate.get("section_title", ""),
            "section_type": candidate.get("section_type", "text"),
            "evidence_state": evidence_state,
            "meta": candidate.get("meta", {}),
        })
        total_chars += len(chunk_text)

    logger.info(
        "packing complete: %d/%d candidates (after filter=%d, skipped failed=%d, skipped scope=%d), %d/%d chars",
        len(items), len(faiss_candidates), len(filtered_candidates),
        skipped_failed, skipped_scope,
        total_chars, budget_chars,
    )

    return {
        "items": items,
        "diagnostics": {
            "representation": "faiss_ann + workspace_scope",
            "total_candidates": len(faiss_candidates),
            "filtered_candidates": len(filtered_candidates),
            "skipped_failed": skipped_failed,
            "skipped_scope": skipped_scope,
            "packed_items": len(items),
            "total_chars": total_chars,
            "budget_chars": budget_chars,
        },
    }
