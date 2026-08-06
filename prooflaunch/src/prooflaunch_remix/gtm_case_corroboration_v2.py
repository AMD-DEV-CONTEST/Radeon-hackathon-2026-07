from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .gtm_gold_lead_review_queue_v2 import verify_gold_lead_review_queue
from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMCaseCorroborationLedgerV2"
SOURCE_CLASSES = {
    "independent_editorial",
    "first_party_company",
    "implementation_partner",
    "vendor_case_mirror",
    "third_party_republication",
    "community_unverified",
}
RELATIONS = {"same_episode_same_claim", "same_company_adjacent", "same_mechanism_only"}
QUERY_INTENTS = (
    "exact_outcome",
    "first_party_timeline",
    "independent_challenge_or_confirmation",
)


class GTMCaseCorroborationError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.casefold() != "https" or not parts.hostname or parts.username or parts.password:
        raise GTMCaseCorroborationError("corroboration sources must be credential-free HTTPS URLs")
    hostname = parts.hostname.casefold()
    port = f":{parts.port}" if parts.port and parts.port != 443 else ""
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit(("https", hostname + port, path, "", ""))


def _provisional_entity_hint(review: Mapping[str, Any]) -> str:
    """Return a search-only hint; never a CaseCandidateV2 identity decision."""

    title = re.sub(r"\s+", " ", str(review.get("title") or "")).strip()
    patterns = (
        r"^How\s+(.+?)\s+(?:grew|grows|improved|increased|cut|cuts|scaled|scales|uses|used|achieved|built|drove|drives|transformed|streamlined)\b",
        r"^(.+?)\s+(?:increases|increased|grows|grew|drives|drove|achieves|achieved|improves|improved|doubles|doubled|triples|tripled|cuts|cut|sees|saw|captures|captured|closes|closed|qualifies|qualified|gets|got|boosts|boosted|scales|scaled|finds|found|uses|used|switches|switched|nets|netted|aligns|aligned|generates|generated|launches|launched|reduces|reduced|accelerates|accelerated|creates|created|delivers|delivered)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            candidate = re.sub(r"^(?:case study:\s*|startup\s+)", "", match.group(1), flags=re.IGNORECASE).strip(" :-")
            if 2 <= len(candidate) <= 80 and not candidate.casefold().startswith(("a ", "an ", "the ")):
                return candidate
    slug = urlsplit(str(review.get("source_url") or "")).path.rstrip("/").split("/")[-1]
    tokens = [token for token in re.split(r"[-_]+", slug) if token]
    stop = {
        "case", "study", "success", "stories", "story", "customer", "marketing", "sales", "growth", "with",
        "and", "the", "how", "increases", "increased", "drives", "generates", "sees", "achieves", "tiktok",
    }
    cleaned: list[str] = []
    for token in tokens:
        if token.casefold() in stop or token.isdigit():
            if cleaned:
                break
            continue
        cleaned.append(token)
        if len(cleaned) == 5:
            break
    hint = " ".join(cleaned).strip()
    return hint if len(hint) >= 3 else ""


def _query_rows(review_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for review in review_rows:
        company = str(review.get("company") or "").strip()
        title = str(review.get("title") or "").strip()
        identity_ready = bool(company and company not in {'""', "undisclosed"} and not company.casefold().startswith("undisclosed "))
        entity_query_term = company if identity_ready else _provisional_entity_hint(review)
        entity_term_status = (
            "explicit_directory_company"
            if identity_ready
            else "provisional_title_or_url_hint"
            if entity_query_term
            else "unresolved"
        )
        terms = {
            "exact_outcome": f'"{entity_query_term}" "{title}" result revenue sales customers',
            "first_party_timeline": f'"{entity_query_term}" newsroom annual report launch results',
            "independent_challenge_or_confirmation": f'"{entity_query_term}" "{title}" review analysis failure success',
        }
        for intent in QUERY_INTENTS:
            query_id = "corroboration-query-" + hashlib.sha256(
                f'{review["lead_id"]}|{intent}'.encode("utf-8")
            ).hexdigest()[:16]
            rows.append({
                "query_id": query_id,
                "lead_id": review["lead_id"],
                "query_intent": intent,
                "query": terms[intent] if entity_query_term else "",
                "identity_ready": identity_ready,
                "entity_query_term": entity_query_term,
                "entity_term_status": entity_term_status,
                "entity_hint_is_admission_identity": False,
                "execution_status": (
                    "prepared_for_bounded_public_search"
                    if identity_ready
                    else "prepared_with_provisional_entity_hint"
                    if entity_query_term
                    else "blocked_identity_gap"
                ),
                "quota_credit": 0,
            })
    return rows


def compile_case_corroboration(
    review_queue: Mapping[str, Any],
    public_capture: Mapping[str, Any],
    discovered_sources: Sequence[Mapping[str, Any]],
    *,
    research_cutoff: str,
) -> dict[str, Any]:
    verify_gold_lead_review_queue(review_queue)
    verify_public_source_capture(public_capture)
    reviews = {row["lead_id"]: row for row in review_queue["records"]}
    captures = {_canonical_url(row["source_url"]): row for row in public_capture["records"]}
    query_rows = _query_rows(review_queue["records"])
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in discovered_sources:
        lead_id = str(raw.get("lead_id") or "")
        if lead_id not in reviews:
            raise GTMCaseCorroborationError("corroboration source references an unknown lead")
        source_url = _canonical_url(str(raw.get("source_url") or ""))
        key = (lead_id, source_url)
        if key in seen:
            continue
        seen.add(key)
        source_class = str(raw.get("source_class") or "")
        relation = str(raw.get("relation") or "")
        if source_class not in SOURCE_CLASSES or relation not in RELATIONS:
            raise GTMCaseCorroborationError("corroboration source class or relation is invalid")
        capture = captures.get(source_url)
        if capture is None:
            raise GTMCaseCorroborationError("corroboration source lacks a public capture receipt")
        primary_url = reviews[lead_id]["source_url"]
        distinct_origin = urlsplit(primary_url).hostname != urlsplit(source_url).hostname
        captured = capture.get("capture_status") == "captured_metadata_only"
        independent_candidate = bool(
            captured
            and distinct_origin
            and source_class == "independent_editorial"
            and relation == "same_episode_same_claim"
        )
        record_basis = {
            "lead_id": lead_id,
            "source_url": source_url,
            "source_class": source_class,
            "relation": relation,
        }
        records.append({
            "corroboration_id": "corroboration-" + _digest(record_basis)[:16],
            **record_basis,
            "primary_source_url": primary_url,
            "publisher": str(raw.get("publisher") or "").strip(),
            "title": str(raw.get("title") or "").strip(),
            "discovery_query": str(raw.get("discovery_query") or "").strip(),
            "source_excerpt": str(raw.get("source_excerpt") or "").strip()[:500],
            "capture_status": capture.get("capture_status"),
            "capture_receipt_sha256": capture.get("content_sha256", ""),
            "distinct_origin_from_primary": distinct_origin,
            "independent_same_claim_candidate": independent_candidate,
            "human_same_episode_review_required": True,
            "human_claim_equivalence_review_required": True,
            "automatic_independent_evidence_credit": False,
            "outcome_audit_credit": 0,
            "candidate_quota_credit": 0,
        })
    records.sort(key=lambda row: (row["lead_id"], row["source_url"]))
    class_counts = Counter(row["source_class"] for row in records)
    relation_counts = Counter(row["relation"] for row in records)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "research_cutoff": research_cutoff,
        "source_review_queue_sha256": review_queue["content_sha256"],
        "source_public_capture_sha256": public_capture["content_sha256"],
        "review_lead_count": len(review_queue["records"]),
        "query_count": len(query_rows),
        "query_status_counts": dict(sorted(Counter(row["execution_status"] for row in query_rows).items())),
        "queries": query_rows,
        "record_count": len(records),
        "source_class_counts": dict(sorted(class_counts.items())),
        "relation_counts": dict(sorted(relation_counts.items())),
        "independent_same_claim_candidate_count": sum(row["independent_same_claim_candidate"] for row in records),
        "human_confirmed_independent_evidence_count": 0,
        "records": records,
        "promotion_policy": {
            "same_vendor_or_partner_republication_is_independent": False,
            "different_hostname_alone_is_independent": False,
            "first_party_company_source_replaces_independent_source": False,
            "independent_candidate_requires_human_same_episode_and_claim_equivalence_review": True,
            "automatic_candidate_or_outcome_credit_allowed": False,
        },
        "candidate_quota_credit": 0,
        "outcome_audit_credit": 0,
        "truth_boundary": (
            "This ledger separates public corroboration discovery by source interest and claim relation. A captured URL, "
            "different hostname, partner retelling, first-party statement, or search-result match does not independently "
            "verify an episode or outcome. Named human same-episode and exact-claim review remains mandatory."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_case_corroboration(payload)
    return payload


def verify_case_corroboration(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseCorroborationError("case corroboration seal is invalid")
    queries = payload.get("queries")
    records = payload.get("records")
    if not isinstance(queries, list) or payload.get("query_count") != len(queries):
        raise GTMCaseCorroborationError("corroboration query aggregate drifted")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise GTMCaseCorroborationError("corroboration record aggregate drifted")
    if len({row.get("query_id") for row in queries}) != len(queries):
        raise GTMCaseCorroborationError("corroboration query IDs are duplicated")
    if len({(row.get("lead_id"), row.get("source_url")) for row in records}) != len(records):
        raise GTMCaseCorroborationError("corroboration sources were not deduplicated")
    if any(row.get("quota_credit") != 0 for row in queries):
        raise GTMCaseCorroborationError("a query escaped the zero-credit boundary")
    if any(row.get("entity_hint_is_admission_identity") is not False for row in queries):
        raise GTMCaseCorroborationError("a search hint escaped into admission identity")
    if any(
        row.get("source_class") not in SOURCE_CLASSES
        or row.get("relation") not in RELATIONS
        or row.get("automatic_independent_evidence_credit") is not False
        or row.get("candidate_quota_credit") != 0
        or row.get("outcome_audit_credit") != 0
        for row in records
    ):
        raise GTMCaseCorroborationError("a corroboration record escaped the review boundary")
    expected_independent = sum(row.get("independent_same_claim_candidate") is True for row in records)
    if payload.get("independent_same_claim_candidate_count") != expected_independent:
        raise GTMCaseCorroborationError("independent candidate aggregate drifted")
    if payload.get("human_confirmed_independent_evidence_count") != 0:
        raise GTMCaseCorroborationError("human evidence cannot be fabricated by compilation")
    if payload.get("candidate_quota_credit") != 0 or payload.get("outcome_audit_credit") != 0:
        raise GTMCaseCorroborationError("corroboration ledger minted quota")


__all__ = [
    "GTMCaseCorroborationError",
    "compile_case_corroboration",
    "verify_case_corroboration",
]
