from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .gtm_all_subvertical_discovery_v2 import verify_all_subvertical_discovery
from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMAllSubverticalReviewQueueV2"
UNRESOLVED_CANDIDATE_GATES = (
    "observed_period",
    "market",
    "company_scale",
    "lifecycle_state",
    "budget_tier_and_six_cost_components",
    "result_meaning_and_baseline",
    "independent_same_episode_outcome_evidence",
    "entity_and_episode_identity",
    "cross_platform_deduplication",
    "named_human_source_inspection",
)


class GTMAllSubverticalReviewQueueError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _url_key(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def build_all_subvertical_review_queue(
    discovery: Mapping[str, Any],
    capture: Mapping[str, Any],
    *,
    source_origin: str,
) -> dict[str, Any]:
    verify_all_subvertical_discovery(discovery)
    verify_public_source_capture(capture)
    capture_by_url = {_url_key(str(row["source_url"])): row for row in capture["records"]}
    records = []
    for lead in discovery["records"]:
        if source_origin not in lead.get("source_record_origins", []):
            continue
        captured = capture_by_url.get(_url_key(str(lead["source_url"])))
        if captured is None:
            raise GTMAllSubverticalReviewQueueError(f"{lead['lead_id']} lacks a capture receipt")
        company = str(lead.get("company") or "").strip()
        identity_is_named = bool(company) and not company.casefold().startswith("undisclosed")
        captured_ok = captured.get("capture_status") == "captured_metadata_only"
        blockers = list(UNRESOLVED_CANDIDATE_GATES)
        if not identity_is_named:
            blockers.insert(0, "named_company_identity")
        if not captured_ok:
            blockers.insert(0, "public_source_capture")
        hint = company if identity_is_named else str(lead["title"])
        row = {
            "review_item_id": "all-review-" + _digest(lead["lead_id"])[:16],
            "lead_id": lead["lead_id"],
            "source_url": lead["source_url"],
            "source_capture_status": captured["capture_status"],
            "source_capture_content_sha256": captured.get("content_sha256"),
            "source_capture_ledger_sha256": capture["content_sha256"],
            "company": company,
            "title": lead["title"],
            "source_excerpt": lead["source_excerpt"],
            "provisional_subvertical_ids": lead["provisional_subvertical_ids"],
            "identity_is_named": identity_is_named,
            "machine_ready_for_named_review": bool(captured_ok and identity_is_named),
            "status": "ready_for_named_review" if captured_ok and identity_is_named else "evidence_gap",
            "candidate_gate_blockers": blockers,
            "corroboration_queries": [
                f'"{hint}" independent outcome revenue pipeline failure',
                f'"{hint}" official timeline case study results',
                f'"{hint}" marketing budget team production cost',
            ],
            "named_reviewer": None,
            "human_source_inspection_completed": False,
            "formal_candidate_quota_credit": 0,
            "automatic_promotion_allowed": False,
        }
        row["packet_sha256"] = _digest(row)
        records.append(row)
    records.sort(key=lambda row: row["review_item_id"])
    status_counts = Counter(row["status"] for row in records)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "discovery_sha256": discovery["content_sha256"],
        "capture_sha256": capture["content_sha256"],
        "source_origin": source_origin,
        "review_item_count": len(records),
        "machine_ready_for_named_review_count": status_counts["ready_for_named_review"],
        "evidence_gap_count": status_counts["evidence_gap"],
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "records": records,
        "truth_boundary": (
            "Machine-ready means a named company and captured public page are available for a human to inspect. It does not "
            "mean the case identity, budget, outcome, causality, deduplication or CaseCandidateV2 admission has passed."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_all_subvertical_review_queue(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMAllSubverticalReviewQueueError("all-subvertical review queue seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("review_item_count") != len(records):
        raise GTMAllSubverticalReviewQueueError("review item aggregate drifted")
    statuses = Counter(row.get("status") for row in records)
    if payload.get("machine_ready_for_named_review_count") != statuses["ready_for_named_review"]:
        raise GTMAllSubverticalReviewQueueError("ready-review aggregate drifted")
    if payload.get("evidence_gap_count") != statuses["evidence_gap"]:
        raise GTMAllSubverticalReviewQueueError("evidence-gap aggregate drifted")
    if payload.get("observed_named_human_review_count") != 0 or payload.get("formal_candidate_quota_credit") != 0:
        raise GTMAllSubverticalReviewQueueError("unreviewed queue was misreported as reviewed or admitted")
    ids = [row.get("review_item_id") for row in records]
    if len(ids) != len(set(ids)):
        raise GTMAllSubverticalReviewQueueError("review item IDs are duplicated")
    for row in records:
        packet_sha = row.get("packet_sha256")
        if packet_sha != _digest({key: value for key, value in row.items() if key != "packet_sha256"}):
            raise GTMAllSubverticalReviewQueueError("review packet seal is invalid")
        if (
            row.get("named_reviewer") is not None
            or row.get("human_source_inspection_completed") is not False
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
            or len(row.get("corroboration_queries", [])) != 3
            or set(UNRESOLVED_CANDIDATE_GATES) - set(row.get("candidate_gate_blockers", []))
        ):
            raise GTMAllSubverticalReviewQueueError("review item escaped its human or admission boundary")
        expected_ready = row.get("source_capture_status") == "captured_metadata_only" and row.get("identity_is_named") is True
        if row.get("machine_ready_for_named_review") is not expected_ready:
            raise GTMAllSubverticalReviewQueueError("machine-ready state is inconsistent")


__all__ = [
    "GTMAllSubverticalReviewQueueError",
    "build_all_subvertical_review_queue",
    "verify_all_subvertical_review_queue",
]
