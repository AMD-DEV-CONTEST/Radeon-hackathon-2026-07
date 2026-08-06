#!/usr/bin/env python3
"""Verify a recorded AMD Search/Reader run without external I/O."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = "amd.search-reader-offline.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXPECTED_CONTRACT: dict[str, object] = {
    "searchServiceVersion": "shidu-search-mcp.v4",
    "readerServiceVersion": "shidu-reader-mcp.v2",
    "searchTool": "coding_plan.search",
    "readerTool": "coding_plan.read_page",
    "catalogProviders": ["google-books", "open-library", "crossref"],
    "queryExpansionProvider": "wikidata",
    "webSearchProvider": "web-search-prime",
    "webSearchRecency": "noLimit",
    "fallbackProvider": "zh-wikipedia-mediawiki-api",
    "fallbackConditions": ["http_429", "http_5xx", "network_error"],
    "searchReturnsUrlsOnly": True,
    "readerRequiredForEvidence": True,
}
_EXPECTED_DEPLOYMENT = {
    "persistentRoot": "/persistent/douyin-amd",
    "codeRoot": "/persistent/douyin-amd/releases/current",
    "configRoot": "/persistent/douyin-amd/config",
    "selectedEvidenceRoot": "/persistent/douyin-amd/evidence/selected",
    "runtimeCacheRoot": "/workspace/amd-runtime-cache",
}
_TRANSITIONS = {
    "queued": {"resolving"},
    "resolving": {"searching", "failed"},
    "searching": {"reading", "failed"},
    "reading": {"extracting", "failed"},
    "extracting": {"synthesizing", "failed"},
    "synthesizing": {"ready", "insufficient", "retryable_failed", "failed"},
    "ready": set(),
    "insufficient": set(),
    "retryable_failed": set(),
    "failed": set(),
}
_TERMINAL_STATES = {"ready", "insufficient", "retryable_failed", "failed"}
_SOURCE_TYPES = {"academic", "reference", "publisher", "media", "web"}
_SOURCE_DISCLOSURE = {
    "code": "SOURCE_GROUNDED",
    "contentMode": "source_grounded",
    "label": "来源支撑",
    "notice": "内容来自 Reader 核验资料。",
}
_AI_DISCLOSURE = {
    "code": "AI_COMPLETED_NON_ORIGINAL",
    "contentMode": "ai_completed",
    "label": "AI 补全内容，非原文",
    "notice": "未找到可核验原文；内容由 AI 根据书目信息和可用资料补全，可能存在偏差。",
}
_AI_SECTIONS = ["情节梗概", "情绪脉络", "适读提示", "不确定性说明"]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _safe_https(value: object) -> bool:
    if not isinstance(value, str) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _add(violations: list[str], condition: bool, message: str) -> None:
    if not condition:
        violations.append(message)


def _validate_contract(payload: Mapping[str, Any], violations: list[str]) -> None:
    contract = _mapping(payload.get("contract"))
    _add(violations, bool(contract), "contract must be an object")
    for key, expected in _EXPECTED_CONTRACT.items():
        if key == "fallbackConditions":
            message = (
                "contract.fallbackConditions must contain only "
                "http_429, http_5xx, network_error"
            )
        else:
            rendered = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
            if isinstance(expected, str):
                rendered = expected
            message = f"contract.{key} must equal {rendered}"
        _add(violations, contract.get(key) == expected, message)


def _validate_deployment(payload: Mapping[str, Any], violations: list[str]) -> None:
    deployment = _mapping(payload.get("deployment"))
    _add(violations, bool(deployment), "deployment must be an object")
    for key, expected in _EXPECTED_DEPLOYMENT.items():
        _add(
            violations,
            deployment.get(key) == expected,
            f"deployment.{key} must equal {expected}",
        )


def _validate_durability(payload: Mapping[str, Any], violations: list[str]) -> None:
    durability = _mapping(payload.get("durability"))
    valid = (
        durability.get("stateStore") == "database"
        and durability.get("persistBeforeProjection") is True
        and durability.get("resumeRetainsBudget") is True
    )
    _add(
        violations,
        valid,
        "durability must persist state before projection and retain budget after restart",
    )


def _validate_budget(
    payload: Mapping[str, Any], violations: list[str]
) -> tuple[int, int, int]:
    budget = _mapping(payload.get("budget"))
    limits = (
        budget.get("maxSearchCalls"),
        budget.get("maxReaderCalls"),
        budget.get("maxProviderRetries"),
    )
    _add(
        violations,
        limits == (4, 8, 2),
        "budget limits must equal 4 Search, 8 Reader, 2 retries",
    )
    values: list[int] = []
    for key, upper in (
        ("searchCallsUsed", 4),
        ("readerCallsUsed", 8),
        ("providerRetriesUsed", 2),
    ):
        value = budget.get(key)
        valid = _integer(value) and 0 <= value <= upper
        _add(
            violations,
            valid,
            f"budget.{key} must be between 0 and {upper}",
        )
        values.append(value if valid else 0)
    return values[0], values[1], values[2]


def _validate_queries(
    payload: Mapping[str, Any], search_calls: int, violations: list[str]
) -> tuple[list[Mapping[str, Any]], list[str]]:
    plan = _mapping(payload.get("queryPlan"))
    _add(
        violations,
        plan.get("plannerAuthority") == ["queries", "evidence_gaps"],
        "queryPlan.plannerAuthority must contain only queries and evidence_gaps",
    )
    queries = [item for item in _sequence(plan.get("queries")) if isinstance(item, Mapping)]
    raw_queries = _sequence(plan.get("queries"))
    _add(
        violations,
        1 <= len(raw_queries) <= 4 and len(queries) == len(raw_queries),
        "queryPlan.queries must contain between 1 and 4 query objects",
    )
    for index, query in enumerate(queries, start=1):
        text = query.get("query")
        valid = (
            query.get("ordinal") == index
            and query.get("origin") in {"default", "expanded"}
            and isinstance(text, str)
            and bool(text.strip())
            and len(text.strip()) <= 70
        )
        _add(violations, valid, f"queryPlan query {index} is invalid")
    _add(
        violations,
        len(queries) <= search_calls,
        "queryPlan query count cannot exceed budget.searchCallsUsed",
    )
    gaps_value = _sequence(plan.get("evidenceGaps"))
    gaps = [item.strip() for item in gaps_value if isinstance(item, str) and item.strip()]
    _add(
        violations,
        len(gaps) == len(gaps_value) and len(gaps) <= 8,
        "queryPlan.evidenceGaps must contain at most 8 non-empty strings",
    )
    return queries, gaps


def _validate_states(
    payload: Mapping[str, Any], violations: list[str]
) -> tuple[list[Mapping[str, Any]], str | None]:
    raw_history = _sequence(payload.get("stateHistory"))
    history = [item for item in raw_history if isinstance(item, Mapping)]
    _add(
        violations,
        bool(history) and len(history) == len(raw_history),
        "stateHistory must contain state objects",
    )
    if not history:
        return [], None
    _add(violations, history[0].get("state") == "queued", "stateHistory must start at queued")
    _add(
        violations,
        all(item.get("persisted") is True for item in history),
        "every stateHistory entry must be persisted",
    )
    for index, item in enumerate(history, start=1):
        _add(
            violations,
            item.get("ordinal") == index and item.get("state") in _TRANSITIONS,
            f"stateHistory entry {index} is invalid",
        )
    for previous, current in zip(history, history[1:]):
        previous_state = previous.get("state")
        current_state = current.get("state")
        if previous_state in _TRANSITIONS:
            _add(
                violations,
                current_state in _TRANSITIONS[previous_state],
                f"stateHistory contains an invalid transition: {previous_state} -> {current_state}",
            )
    terminal = history[-1].get("state")
    _add(
        violations,
        terminal in _TERMINAL_STATES,
        "stateHistory must end in a terminal state",
    )
    return history, terminal if isinstance(terminal, str) else None


def _validate_search(
    payload: Mapping[str, Any], queries: list[Mapping[str, Any]], violations: list[str]
) -> tuple[bool, list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    search = _mapping(payload.get("search"))
    systemic_failure = search.get("systemicFailure") is True
    _add(
        violations,
        isinstance(search.get("systemicFailure"), bool),
        "search.systemicFailure must be boolean",
    )
    raw_hits = _sequence(search.get("hits"))
    hits = [item for item in raw_hits if isinstance(item, Mapping)]
    _add(
        violations,
        len(hits) == len(raw_hits),
        "search.hits must contain objects",
    )
    query_ordinals = {item.get("ordinal") for item in queries}
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, hit in enumerate(hits, start=1):
        hit_id = hit.get("hitId")
        only_url_fields = set(hit) == {"hitId", "queryOrdinal", "url"}
        valid = (
            isinstance(hit_id, str)
            and bool(hit_id)
            and hit_id not in by_id
            and hit.get("queryOrdinal") in query_ordinals
            and _safe_https(hit.get("url"))
            and only_url_fields
        )
        _add(
            violations,
            valid,
            f"search hit {index} must contain only a unique id, query ordinal, and HTTPS URL",
        )
        if isinstance(hit_id, str) and hit_id:
            by_id[hit_id] = hit
    return systemic_failure, hits, by_id


def _validate_reader(
    payload: Mapping[str, Any],
    hits: Mapping[str, Mapping[str, Any]],
    reader_calls: int,
    violations: list[str],
) -> tuple[bool, list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    reader = _mapping(payload.get("reader"))
    security_mismatch = reader.get("securityMismatch") is True
    _add(
        violations,
        isinstance(reader.get("securityMismatch"), bool),
        "reader.securityMismatch must be boolean",
    )
    raw_documents = _sequence(reader.get("documents"))
    documents = [item for item in raw_documents if isinstance(item, Mapping)]
    _add(
        violations,
        len(documents) == len(raw_documents),
        "reader.documents must contain objects",
    )
    _add(
        violations,
        len(documents) <= reader_calls,
        "Reader document count cannot exceed budget.readerCallsUsed",
    )
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, document in enumerate(documents, start=1):
        document_id = document.get("documentId")
        hit_id = document.get("hitId")
        hit = hits.get(hit_id) if isinstance(hit_id, str) else None
        _add(
            violations,
            isinstance(document_id, str) and bool(document_id) and document_id not in by_id,
            f"reader document {index} must have a unique documentId",
        )
        if isinstance(document_id, str) and document_id:
            by_id[document_id] = document
        _add(
            violations,
            hit is not None and document.get("canonicalUrl") == hit.get("url"),
            f"reader document {document_id or index} must resolve from a Search URL",
        )
        _add(
            violations,
            _digest(document.get("contentSha256")),
            f"reader document {document_id or index} contentSha256 must be lowercase SHA-256",
        )
        secure = (
            document.get("sourceType") in _SOURCE_TYPES
            and document.get("peerAttestationValid") is True
            and document.get("redirected") is False
        )
        _add(
            violations,
            secure,
            f"reader document {document_id or index} must have a valid security attestation",
        )
    return security_mismatch, documents, by_id


def _validate_evidence(
    payload: Mapping[str, Any], documents: Mapping[str, Mapping[str, Any]], violations: list[str]
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], set[str]]:
    evidence = _mapping(payload.get("evidence"))
    raw_claims = _sequence(evidence.get("claims"))
    claims = [item for item in raw_claims if isinstance(item, Mapping)]
    _add(
        violations,
        len(claims) == len(raw_claims),
        "evidence.claims must contain objects",
    )
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims, start=1):
        claim_id = claim.get("claimId")
        if not isinstance(claim_id, str) or not claim_id or claim_id in claim_ids:
            violations.append(f"evidence claim {index} must have a unique claimId")
            rendered_id = str(index)
        else:
            claim_ids.add(claim_id)
            rendered_id = claim_id
        document_id = claim.get("documentId")
        reader_only = (
            claim.get("sourceKind") == "reader_document"
            and isinstance(document_id, str)
            and document_id in documents
            and "searchHitId" not in claim
            and "snippet" not in claim
        )
        _add(
            violations,
            reader_only,
            "evidence claims must come only from Reader documents",
        )
        citation = _mapping(claim.get("citation"))
        citation_valid = (
            bool(citation)
            and citation.get("documentId") == document_id
            and _integer(citation.get("start"))
            and _integer(citation.get("end"))
            and 0 <= citation.get("start", -1) < citation.get("end", -1)
            and _digest(citation.get("quoteSha256"))
        )
        if not citation:
            violations.append(
                f"evidence claim {rendered_id} must contain a Reader citation"
            )
        else:
            _add(
                violations,
                citation_valid,
                f"evidence claim {rendered_id} citation must match its Reader document",
            )
    return evidence, claims, claim_ids


def _validate_disclosure(
    disclosure: object, expected: Mapping[str, str], mode: str, violations: list[str]
) -> None:
    _add(
        violations,
        _mapping(disclosure) == expected,
        f"draft.disclosure does not match {mode}",
    )


def _validate_draft(
    payload: Mapping[str, Any],
    terminal: str | None,
    systemic_failure: bool,
    security_mismatch: bool,
    gaps: list[str],
    evidence: Mapping[str, Any],
    claim_ids: set[str],
    violations: list[str],
) -> str | None:
    raw_draft = payload.get("draft")
    system_failure = systemic_failure or security_mismatch
    if system_failure:
        _add(
            violations,
            terminal == "retryable_failed" and raw_draft is None,
            "system failure must end retryable_failed without a draft",
        )
        if isinstance(raw_draft, Mapping) and raw_draft.get("aiCompletionUsed") is True:
            violations.append(
                "AI completion is forbidden during Search or Reader security failure"
            )
        return raw_draft.get("contentMode") if isinstance(raw_draft, Mapping) else None

    if terminal != "ready":
        _add(
            violations,
            raw_draft is None,
            "non-ready terminal state must not contain a draft",
        )
        return None

    draft = _mapping(raw_draft)
    _add(violations, bool(draft), "ready terminal state requires a draft")
    mode = draft.get("contentMode")
    _add(
        violations,
        draft.get("status") == "ready",
        "draft.status must equal ready",
    )
    raw_ids = _sequence(draft.get("claimIds"))
    used_ids = set(item for item in raw_ids if isinstance(item, str))
    _add(
        violations,
        bool(used_ids) and len(used_ids) == len(raw_ids) and used_ids <= claim_ids,
        "draft.claimIds must reference frozen Evidence claims",
    )
    _add(
        violations,
        evidence.get("frozen") is True,
        "ready draft requires a frozen Evidence Pack",
    )
    original_available = evidence.get("originalTextAvailable") is True
    independent_count = evidence.get("independentSourceCount")
    _add(
        violations,
        _integer(independent_count) and 0 <= independent_count,
        "evidence.independentSourceCount must be a non-negative integer",
    )
    independent_count = independent_count if _integer(independent_count) else 0

    if mode == "source_grounded":
        _add(
            violations,
            draft.get("aiCompletionUsed") is False,
            "source_grounded draft cannot use AI completion",
        )
        _add(
            violations,
            not gaps,
            "source_grounded draft cannot retain evidence gaps",
        )
        _add(
            violations,
            original_available or independent_count >= 3,
            "source_grounded draft requires original text or 3 independent sources",
        )
        _validate_disclosure(draft.get("disclosure"), _SOURCE_DISCLOSURE, mode, violations)
    elif mode == "ai_completed":
        _add(
            violations,
            draft.get("aiCompletionUsed") is True,
            "ai_completed draft must set aiCompletionUsed",
        )
        _add(
            violations,
            bool(gaps),
            "draft.aiCompletionUsed requires at least one evidence gap",
        )
        _add(
            violations,
            not original_available and independent_count < 3,
            "AI completion is allowed only without original text and with fewer "
            "than 3 independent sources",
        )
        ai_completion = _mapping(draft.get("aiCompletion"))
        _add(
            violations,
            ai_completion.get("sourceType") == "ai_generated",
            "draft.aiCompletion.sourceType must equal ai_generated",
        )
        _add(
            violations,
            ai_completion.get("confidence") == 0.35,
            "draft.aiCompletion.confidence must equal 0.35",
        )
        _add(
            violations,
            ai_completion.get("isDirectQuote") is False,
            "draft.aiCompletion.isDirectQuote must be false",
        )
        _add(
            violations,
            ai_completion.get("sections") == _AI_SECTIONS,
            "draft.aiCompletion.sections must contain the four frozen sections",
        )
        _validate_disclosure(draft.get("disclosure"), _AI_DISCLOSURE, mode, violations)
    else:
        violations.append("draft.contentMode must be source_grounded or ai_completed")
    return mode if isinstance(mode, str) else None


def verify_fixture(value: object) -> dict[str, Any]:
    """Return a deterministic report for one already-recorded fixture."""

    violations: list[str] = []
    payload = _mapping(value)
    _add(violations, bool(payload), "fixture must be a JSON object")
    _add(
        violations,
        payload.get("schemaVersion") == SCHEMA_VERSION,
        f"schemaVersion must equal {SCHEMA_VERSION}",
    )
    _validate_contract(payload, violations)
    _validate_deployment(payload, violations)
    _validate_durability(payload, violations)
    search_calls, reader_calls, _ = _validate_budget(payload, violations)
    queries, gaps = _validate_queries(payload, search_calls, violations)
    _, terminal = _validate_states(payload, violations)
    systemic_failure, hits, hits_by_id = _validate_search(payload, queries, violations)
    security_mismatch, documents, documents_by_id = _validate_reader(
        payload, hits_by_id, reader_calls, violations
    )
    evidence, claims, claim_ids = _validate_evidence(payload, documents_by_id, violations)
    mode = _validate_draft(
        payload,
        terminal,
        systemic_failure,
        security_mismatch,
        gaps,
        evidence,
        claim_ids,
        violations,
    )
    return {
        "contract": SCHEMA_VERSION,
        "contentMode": mode,
        "counts": {
            "claims": len(claims),
            "queries": len(queries),
            "readerDocuments": len(documents),
            "searchHits": len(hits),
        },
        "ok": not violations,
        "terminalState": terminal,
        "violations": sorted(set(violations)),
    }


def _render(payload: Mapping[str, Any], *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="离线核验 AMD Search/Reader 录制合同"
    )
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        value = json.loads(arguments.fixture.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(
            _render(
                {"error": "fixture is not valid UTF-8 JSON", "ok": False},
                pretty=arguments.pretty,
            ),
            end="",
        )
        return 2
    report = verify_fixture(value)
    print(_render(report, pretty=arguments.pretty), end="")
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
