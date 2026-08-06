"""Deterministic host checks on Insurance RAG Agent run results.

Host-owned deterministic checks (owner=host) — do not call a model, only inspect run facts:
- retrieval.sufficient       — retrieval result count >= MIN_ITEMS
- retrieval.hybrid_used      — BM25+FAISS hybrid retrieval was used (not FAISS only)
- retrieval.reranked         — Cross-Encoder reranking was applied
- citation.present           — answer contains [[ref:xxx]] citation markers
- citation.valid             — all citation refs point to real retrieved items
- citation.source_traced     — citations include source document and title
- answer.non_empty           — answer is not empty
- answer.no_hallucination_markers — answer contains no uncited "I cannot"/"I don't know"
- session.persisted          — Session was persisted (memo exists)
- trace.recorded             — Trace events were recorded
"""

from __future__ import annotations

import re
from typing import Any


# ── retrieval quality thresholds ──
MIN_ITEMS = 2

# ── citation token regex ──
CITATION_PATTERN = re.compile(r"\[\[ref:(\w+)\]\]")

# ── hallucination markers ──
HALLUCINATION_MARKERS = ("I cannot", "I don't know", "cannot answer", "no relevant information found")


def _row(
    rule: dict[str, str],
    stage: str,
    passed: bool,
    evidence: list[str],
    reason: str,
) -> dict[str, object]:
    """Build one check-result row."""

    return {
        "stage": stage,
        "rule_id": rule["rule_id"],
        "description": rule["description"],
        "level": "pass" if passed else "fail",
        "evidence": evidence,
        "reason": reason,
    }


def _extract_citation_refs(answer: str) -> list[str]:
    """Extract [[ref:xxx]] citation keys from the answer text."""

    return CITATION_PATTERN.findall(answer)


def _offered_ref_keys(context_pack: dict[str, Any]) -> set[str]:
    """Derive the offered citation-key set (e1, e2, ...) from context_pack items."""

    items = context_pack.get("items", []) if context_pack else []
    return {f"e{i + 1}" for i in range(len(items))}


def _check_retrieval_sufficient(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """retrieval.sufficient — retrieval result count >= MIN_ITEMS."""

    context_pack = run.get("context_pack") or {}
    items = context_pack.get("items", []) if context_pack else []
    count = len(items)
    passed = count >= MIN_ITEMS
    return (
        passed,
        [f"items={count}/{MIN_ITEMS}"],
        f"retrieval results sufficient ({count}>={MIN_ITEMS})" if passed
        else f"retrieval results insufficient ({count}<{MIN_ITEMS})",
    )


def _check_retrieval_hybrid_used(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """retrieval.hybrid_used — BM25+FAISS hybrid retrieval was used."""

    candidates = run.get("faiss_candidates") or []
    if not candidates:
        return (
            False,
            ["candidates=0"],
            "no retrieval candidates, cannot determine hybrid retrieval",
        )
    hybrid_count = sum(
        1
        for c in candidates
        if isinstance(c, dict)
        and "bm25" in (c.get("sources") or [])
    )
    passed = hybrid_count > 0
    return (
        passed,
        [f"hybrid_candidates={hybrid_count}/{len(candidates)}"],
        f"hybrid retrieval used ({hybrid_count} candidates with BM25 source)" if passed
        else "hybrid retrieval not used (FAISS only)",
    )


def _check_retrieval_reranked(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """retrieval.reranked — Cross-Encoder reranking was applied."""

    candidates = run.get("faiss_candidates") or []
    if not candidates:
        return (
            False,
            ["candidates=0"],
            "no retrieval candidates, cannot determine reranking",
        )
    reranked_count = sum(
        1
        for c in candidates
        if isinstance(c, dict) and c.get("rerank_score") is not None
    )
    passed = reranked_count > 0
    return (
        passed,
        [f"reranked={reranked_count}/{len(candidates)}"],
        f"Cross-Encoder reranking applied ({reranked_count} candidates with rerank_score)" if passed
        else "Cross-Encoder reranking not applied",
    )


def _check_citation_present(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """citation.present — answer contains [[ref:xxx]] citation markers."""

    answer = str(run.get("answer", ""))
    refs = _extract_citation_refs(answer)
    passed = len(refs) > 0
    return (
        passed,
        [f"citation_count={len(refs)}"],
        f"answer contains {len(refs)} citation markers" if passed
        else "answer contains no [[ref:xxx]] citation markers",
    )


def _check_citation_valid(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """citation.valid — all citation refs point to real retrieved items."""

    answer = str(run.get("answer", ""))
    context_pack = run.get("context_pack") or {}
    offered = _offered_ref_keys(context_pack)
    refs = _extract_citation_refs(answer)
    if not refs:
        return (
            False,
            ["refs=0"],
            "no citation markers in answer, cannot validate citation validity",
        )
    invalid = [r for r in refs if r not in offered]
    passed = len(invalid) == 0
    return (
        passed,
        [f"valid={len(refs) - len(invalid)}/{len(refs)}", f"invalid={invalid}"],
        f"all citations valid (offered={sorted(offered)})" if passed
        else f"invalid citations found: {invalid} (offered={sorted(offered)})",
    )


def _check_citation_source_traced(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """citation.source_traced — citations include source document and title."""

    citations = run.get("citations") or []
    context_pack = run.get("context_pack") or {}
    items = context_pack.get("items", []) if context_pack else []

    if not citations:
        return (
            False,
            ["citations=0"],
            "no citation structure, cannot trace provenance",
        )

    traced_count = 0
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        ref_id = str(citation.get("ref_id", ""))
        # ref_id format is e1, e2, ... corresponding to items[0], items[1], ...
        idx = None
        if ref_id.startswith("e") and ref_id[1:].isdigit():
            idx = int(ref_id[1:]) - 1
        if idx is not None and 0 <= idx < len(items):
            item = items[idx]
            source = str(item.get("source") or item.get("chunk_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if source and title:
                traced_count += 1

    passed = traced_count == len(citations)
    return (
        passed,
        [f"traced={traced_count}/{len(citations)}"],
        f"all citations include source and title ({traced_count}/{len(citations)})" if passed
        else f"some citations missing source or title ({traced_count}/{len(citations)})",
    )


def _check_answer_non_empty(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """answer.non_empty — answer is not empty."""

    answer = str(run.get("answer", "")).strip()
    passed = len(answer) > 0
    return (
        passed,
        [f"answer_length={len(answer)}"],
        "answer is not empty" if passed else "answer is empty",
    )


def _check_answer_no_hallucination_markers(
    run: dict[str, Any],
) -> tuple[bool, list[str], str]:
    """answer.no_hallucination_markers — answer contains no uncited hallucination markers."""

    answer = str(run.get("answer", ""))
    refs = _extract_citation_refs(answer)
    has_citation = len(refs) > 0

    found_markers = [
        marker for marker in HALLUCINATION_MARKERS if marker in answer
    ]

    if not found_markers:
        return (
            True,
            ["markers=none"],
            "answer contains no hallucination markers",
        )

    if has_citation:
        return (
            True,
            [f"markers={found_markers}", "has_citation=true"],
            f"answer contains markers {found_markers} but has citation markers, acceptable",
        )

    return (
        False,
        [f"markers={found_markers}", "has_citation=false"],
        f"answer contains hallucination markers {found_markers} and no citation markers",
    )


def _check_session_persisted(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """session.persisted — Session was persisted (memo exists).

    Look up the business.finalize.completed event among trace_events
    and check whether facts.session_persisted is True.
    """

    events = run.get("trace_events") or []
    finalize_events = [
        e for e in events
        if isinstance(e, dict)
        and str(e.get("event_type", "")) == "business.finalize.completed"
    ]

    if not finalize_events:
        return (
            False,
            ["finalize_events=0"],
            "no finalize event found, Session may not have been persisted",
        )

    facts = finalize_events[-1].get("facts") or {}
    persisted = bool(facts.get("session_persisted", False))
    return (
        persisted,
        [f"session_persisted={persisted}"],
        "Session persisted" if persisted else "Session not persisted",
    )


def _check_trace_recorded(run: dict[str, Any]) -> tuple[bool, list[str], str]:
    """trace.recorded — Trace events were recorded."""

    events = run.get("trace_events") or []
    count = len(events)
    passed = count > 0
    return (
        passed,
        [f"trace_events={count}"],
        f"Trace events recorded ({count})" if passed
        else "Trace events are empty",
    )


# ── rule ID → check function mapping ──
_FACT_CHECKS: dict[str, Any] = {
    "retrieval.sufficient": _check_retrieval_sufficient,
    "retrieval.hybrid_used": _check_retrieval_hybrid_used,
    "retrieval.reranked": _check_retrieval_reranked,
    "citation.present": _check_citation_present,
    "citation.valid": _check_citation_valid,
    "citation.source_traced": _check_citation_source_traced,
    "answer.non_empty": _check_answer_non_empty,
    "answer.no_hallucination_markers": _check_answer_no_hallucination_markers,
    "session.persisted": _check_session_persisted,
    "trace.recorded": _check_trace_recorded,
}


def deterministic_verdicts(
    *,
    run: dict[str, Any],
    case_rules: dict[str, Any],
    stage_rules: dict[str, list[dict[str, str]]],
) -> list[dict[str, object]]:
    """Evaluate only owner=host rules and return the deterministic verdict list.

    Args:
        run: A complete result dict of a single InsuranceAgent.query() run,
             containing fields such as answer, citations, sources,
             context_pack, faiss_candidates, trace_events, status.
        case_rules: The case-specific rules (expected_refs, business_boundary, etc.).
        stage_rules: All rules grouped by stage from rules.yaml.

    Returns:
        A list of verdict rows, each containing stage, rule_id, description,
        level, evidence, reason.
    """

    rows: list[dict[str, object]] = []
    for stage, rules in stage_rules.items():
        for rule in rules:
            if rule.get("owner") != "host":
                continue
            rule_id = str(rule["rule_id"])
            check_fn = _FACT_CHECKS.get(rule_id)
            if check_fn is None:
                rows.append(_row(rule, stage, False, [], f"check function not found: {rule_id}"))
                continue
            passed, evidence_items, reason = check_fn(run)
            rows.append(_row(rule, stage, passed, evidence_items, reason))
    return rows


__all__ = ["deterministic_verdicts", "MIN_ITEMS", "CITATION_PATTERN"]
