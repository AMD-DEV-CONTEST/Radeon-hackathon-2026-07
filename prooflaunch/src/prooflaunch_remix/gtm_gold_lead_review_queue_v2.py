from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_claim_surface_v2 import verify_case_claim_surfaces
from .gtm_gold_case_discovery_v2 import GOLD_SUBVERTICALS, verify_gold_case_discovery
from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMGoldLeadReviewQueueV2"


class GTMGoldLeadReviewQueueError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _score(lead: Mapping[str, Any], capture: Mapping[str, Any], surface: Mapping[str, Any]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    if capture.get("capture_status") == "captured_metadata_only":
        score += 10
        reasons.append("public page capture succeeded")
    route_count = len(lead.get("provisional_subvertical_ids", ()))
    if route_count == 1:
        score += 15
        reasons.append("single provisional subvertical route")
    elif route_count > 1:
        score += 5
        reasons.append("multiple provisional routes require disambiguation")
    counts = surface.get("fragment_counts", {})
    for category, points in (("outcome", 20), ("time_window", 15), ("cost_resource", 15), ("mechanism", 15)):
        if int(counts.get(category, 0)):
            score += points
            reasons.append(f"bounded {category} signal present")
    if surface.get("surface_completeness") == "four_surface_signal":
        score += 5
    if lead.get("directory_company_size"):
        score += 5
        reasons.append("directory company-size signal present")
    return score, reasons


def compile_gold_lead_review_queue(
    discovery: Mapping[str, Any],
    public_capture: Mapping[str, Any],
    claim_surfaces: Mapping[str, Any],
) -> dict[str, Any]:
    verify_gold_case_discovery(discovery)
    verify_public_source_capture(public_capture)
    verify_case_claim_surfaces(claim_surfaces)
    captures = {row["source_url"]: row for row in public_capture["records"]}
    surfaces = {row["source_url"]: row for row in claim_surfaces["records"]}
    rows: list[dict[str, Any]] = []
    for lead in discovery["records"]:
        if not lead["provisional_subvertical_ids"]:
            continue
        capture = captures.get(lead["source_url"], {})
        surface = surfaces.get(lead["source_url"], {})
        score, reasons = _score(lead, capture, surface)
        blockers = []
        if capture.get("capture_status") != "captured_metadata_only":
            blockers.append("public_case_page_capture")
        if not surface:
            blockers.append("bounded_claim_surfaces")
        else:
            blockers.extend(f"claim_surface:{value}" for value in surface.get("missing_surface_categories", ()))
        blockers.extend((
            "human_exact_claim_binding",
            "entity_and_episode_resolution",
            "observed_start_and_end",
            "primary_market_and_lifecycle",
            "six_component_cost_completeness",
            "independent_or_first_party_outcome_surface",
            "cross_platform_duplicate_review",
        ))
        rows.append({
            "review_item_id": "gold-review-" + hashlib.sha256(lead["source_url"].encode()).hexdigest()[:16],
            "lead_id": lead["lead_id"],
            "source_url": lead["source_url"],
            "company": lead["company"],
            "title": lead["title"],
            "source_family_ids": lead["source_family_ids"],
            "provisional_subvertical_ids": lead["provisional_subvertical_ids"],
            "directory_industry": lead["directory_industry"],
            "directory_company_size": lead["directory_company_size"],
            "capture_status": capture.get("capture_status", "not_attempted"),
            "claim_surface_status": surface.get("surface_completeness", "not_attempted"),
            "claim_surface_sha256": surface.get("source_content_sha256"),
            "review_priority_score": score,
            "review_priority_reasons": reasons,
            "blocking_requirements": sorted(set(blockers)),
            "independent_discovery_queries": [
                f"\"{lead['company']}\" {lead['title']} revenue OR sales OR customers",
                f"\"{lead['company']}\" annual report newsroom growth results",
                f"\"{lead['company']}\" campaign case study independent",
            ],
            "review_status": "ready_for_human_binding" if score >= 80 and surface else "evidence_gap",
            "automatic_case_promotion_allowed": False,
            "quota_credit": 0,
        })

    for subvertical_id in GOLD_SUBVERTICALS:
        candidates = sorted(
            (row for row in rows if subvertical_id in row["provisional_subvertical_ids"]),
            key=lambda row: (-row["review_priority_score"], row["source_url"]),
        )
        for rank, row in enumerate(candidates, start=1):
            row.setdefault("subvertical_review_ranks", {})[subvertical_id] = rank
    rows.sort(key=lambda row: (-row["review_priority_score"], row["source_url"]))
    subvertical_queues = []
    for subvertical_id in GOLD_SUBVERTICALS:
        candidates = [row for row in rows if subvertical_id in row["provisional_subvertical_ids"]]
        ready = [row for row in candidates if row["review_status"] == "ready_for_human_binding"]
        subvertical_queues.append({
            "subvertical_id": subvertical_id,
            "candidate_discovery_target": 200,
            "mechanism_review_target": 40,
            "provisional_lead_count": len(candidates),
            "human_binding_ready_count": len(ready),
            "provisional_lead_gap_to_200": max(0, 200 - len(candidates)),
            "review_batch_lead_ids": [row["lead_id"] for row in candidates[:40]],
            "status": "review_queue_ready" if ready else "source_coverage_gap",
            "quota_credit": 0,
        })
    status_counts = Counter(row["review_status"] for row in rows)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_sha256s": {
            "discovery": discovery["content_sha256"],
            "public_capture": public_capture["content_sha256"],
            "claim_surfaces": claim_surfaces["content_sha256"],
        },
        "review_item_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "human_binding_ready_count": status_counts.get("ready_for_human_binding", 0),
        "subvertical_queue_count": len(subvertical_queues),
        "subvertical_queues": subvertical_queues,
        "records": rows,
        "promotion_policy": {
            "priority_score_grants_candidate_credit": False,
            "human_binding_can_infer_unknown_budget": False,
            "independent_search_query_is_independent_evidence": False,
            "all_case_candidate_v2_fields_and_dedup_review_required": True,
        },
        "truth_boundary": (
            "This queue prioritizes human evidence work. Scores and query plans are triage aids, not verified case fields, "
            "outcomes, causal findings, or candidate quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_gold_lead_review_queue(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMGoldLeadReviewQueueError("gold lead review queue seal is invalid")
    rows = payload.get("records")
    if not isinstance(rows, list) or payload.get("review_item_count") != len(rows):
        raise GTMGoldLeadReviewQueueError("gold lead review aggregate drifted")
    if payload.get("subvertical_queue_count") != len(GOLD_SUBVERTICALS):
        raise GTMGoldLeadReviewQueueError("gold subvertical queue cardinality drifted")
    if len({row.get("review_item_id") for row in rows}) != len(rows):
        raise GTMGoldLeadReviewQueueError("gold review item IDs are duplicated")
    if any(row.get("quota_credit") != 0 or row.get("automatic_case_promotion_allowed") is not False for row in rows):
        raise GTMGoldLeadReviewQueueError("review triage escaped zero-credit boundary")
    queues = payload.get("subvertical_queues", [])
    if {row.get("subvertical_id") for row in queues} != set(GOLD_SUBVERTICALS):
        raise GTMGoldLeadReviewQueueError("gold queue subvertical IDs drifted")
    if any(row.get("quota_credit") != 0 or row.get("provisional_lead_count", 0) >= 200 and row.get("provisional_lead_gap_to_200") != 0 for row in queues):
        raise GTMGoldLeadReviewQueueError("subvertical review queue aggregate is invalid")


__all__ = [
    "GTMGoldLeadReviewQueueError",
    "compile_gold_lead_review_queue",
    "verify_gold_lead_review_queue",
]
