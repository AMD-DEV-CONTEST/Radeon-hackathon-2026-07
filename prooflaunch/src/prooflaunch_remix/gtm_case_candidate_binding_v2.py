from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_claim_surface_v2 import CATEGORIES, verify_case_claim_surfaces
from .gtm_gold_case_discovery_v2 import verify_gold_case_discovery
from .gtm_gold_lead_review_queue_v2 import verify_gold_lead_review_queue
from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMCaseCandidateBindingPacketV2"
GATES = (
    "public_capture_current",
    "exact_company_product_motion_audience",
    "exact_subvertical_classification",
    "observed_period_and_recency",
    "market_scale_and_lifecycle",
    "source_bound_budget_tier_and_six_cost_components",
    "result_claim_binding",
    "independent_outcome_surface",
    "entity_and_episode_resolution",
    "cross_platform_duplicate_review",
    "named_human_exact_binding",
)


class GTMCaseCandidateBindingError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_case_candidate_binding_packets(
    discovery: Mapping[str, Any],
    public_capture: Mapping[str, Any],
    claim_surfaces: Mapping[str, Any],
    review_queue: Mapping[str, Any],
) -> dict[str, Any]:
    verify_gold_case_discovery(discovery)
    verify_public_source_capture(public_capture)
    verify_case_claim_surfaces(claim_surfaces)
    verify_gold_lead_review_queue(review_queue)

    leads = {row["lead_id"]: row for row in discovery["records"]}
    captures = {row["source_url"]: row for row in public_capture["records"]}
    surfaces = {row["lead_id"]: row for row in claim_surfaces["records"]}
    packets: list[dict[str, Any]] = []
    for review in review_queue["records"]:
        lead = leads[review["lead_id"]]
        capture = captures.get(lead["source_url"], {})
        surface = surfaces.get(lead["lead_id"])
        fragments = {
            category: [dict(row) for row in (surface or {}).get("fragments", {}).get(category, [])]
            for category in CATEGORIES
        }
        capture_current = capture.get("capture_status") == "captured_metadata_only"
        gates = {gate: False for gate in GATES}
        gates["public_capture_current"] = capture_current
        proposed = {
            "company": {"value": lead.get("company", ""), "status": "provisional_directory_label"},
            "product": {"value": "", "status": "evidence_gap"},
            "campaign_or_motion": {"value": lead.get("title", ""), "status": "provisional_directory_title"},
            "primary_audience": {"value": "", "status": "evidence_gap"},
            "subvertical_ids": {"value": lead.get("provisional_subvertical_ids", []), "status": "provisional_route"},
            "company_scale": {"value": lead.get("directory_company_size", ""), "status": "provisional_or_gap"},
            "observed_start": {"value": "", "status": "evidence_gap"},
            "observed_end": {"value": "", "status": "evidence_gap"},
            "recency_bucket": {"value": "", "status": "evidence_gap"},
            "quota_market": {"value": "", "status": "evidence_gap"},
            "lifecycle_state": {"value": "", "status": "evidence_gap"},
            "budget_tier": {"value": "", "status": "evidence_gap"},
            "outcome_type": {"value": "", "status": "evidence_gap"},
            "result_summary": {
                "value": [row["bounded_exact_excerpt"] for row in fragments["outcome"]],
                "status": "exact_excerpt_requires_human_semantic_binding" if fragments["outcome"] else "evidence_gap",
            },
            "resource_scope": {
                "value": [row["bounded_exact_excerpt"] for row in fragments["cost_resource"]],
                "status": "exact_excerpt_not_budget_classification" if fragments["cost_resource"] else "evidence_gap",
            },
            "mechanism_hypothesis": {
                "value": [row["bounded_exact_excerpt"] for row in fragments["mechanism"]],
                "status": "exact_excerpt_requires_human_semantic_binding" if fragments["mechanism"] else "evidence_gap",
            },
        }
        packet_id = "candidate-binding-" + lead["lead_id"].removeprefix("gold-lead-")
        blockers = [gate for gate, passed in gates.items() if not passed]
        packets.append({
            "packet_id": packet_id,
            "lead_id": lead["lead_id"],
            "source_url": lead["source_url"],
            "source_family_ids": lead["source_family_ids"],
            "review_priority_score": review["review_priority_score"],
            "machine_ready_for_human_binding": review["review_status"] == "ready_for_human_binding",
            "capture_receipt": {
                "capture_status": capture.get("capture_status", "missing"),
                "captured_at": capture.get("captured_at", ""),
                "content_sha256": capture.get("content_sha256", ""),
                "robots_status": capture.get("robots_status", ""),
                "access_method": capture.get("access_method", ""),
            },
            "claim_surface_status": (surface or {}).get("surface_completeness", "missing"),
            "claim_fragments": fragments,
            "proposed_fields": proposed,
            "independent_discovery_queries": review["independent_discovery_queries"],
            "admission_gates": gates,
            "blocking_requirements": blockers,
            "human_review_template": {
                "reviewer_name": "",
                "reviewed_at": "",
                "source_inspected": False,
                "exact_claim_bindings": [],
                "decision": "pending",
                "decision_notes": "",
            },
            "automatic_candidate_promotion_allowed": False,
            "quota_credit": 0,
        })

    packets.sort(key=lambda row: (-row["review_priority_score"], row["source_url"]))
    status_counts = Counter(
        "machine_ready_for_human_binding" if row["machine_ready_for_human_binding"] else "evidence_gap"
        for row in packets
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_sha256s": {
            "discovery": discovery["content_sha256"],
            "public_capture": public_capture["content_sha256"],
            "claim_surfaces": claim_surfaces["content_sha256"],
            "review_queue": review_queue["content_sha256"],
        },
        "packet_count": len(packets),
        "status_counts": dict(sorted(status_counts.items())),
        "candidate_quota_credit": 0,
        "records": packets,
        "promotion_policy": {
            "exact_excerpt_is_verified_semantic_binding": False,
            "directory_label_is_verified_case_identity": False,
            "qualitative_resource_mention_is_budget_tier_evidence": False,
            "search_query_is_independent_evidence": False,
            "named_source_inspecting_human_review_required": True,
            "automatic_candidate_promotion_allowed": False,
        },
        "truth_boundary": (
            "These packets reduce human review effort by binding source receipts and bounded exact excerpts to every lead. "
            "They do not resolve identity, budget, market, timing, outcome, independence, deduplication, or human approval and "
            "therefore grant zero CaseCandidateV2 quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_candidate_binding_packets(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseCandidateBindingError("candidate binding packet seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("packet_count") != len(records):
        raise GTMCaseCandidateBindingError("candidate binding packet aggregate drifted")
    if len({row.get("packet_id") for row in records}) != len(records):
        raise GTMCaseCandidateBindingError("candidate binding packet IDs are duplicated")
    if payload.get("candidate_quota_credit") != 0:
        raise GTMCaseCandidateBindingError("candidate binding packet aggregate escaped zero credit")
    expected_status_counts = Counter(
        "machine_ready_for_human_binding" if row.get("machine_ready_for_human_binding") else "evidence_gap"
        for row in records
    )
    if payload.get("status_counts") != dict(sorted(expected_status_counts.items())):
        raise GTMCaseCandidateBindingError("candidate binding packet status counts drifted")
    policy = payload.get("promotion_policy", {})
    if policy.get("automatic_candidate_promotion_allowed") is not False:
        raise GTMCaseCandidateBindingError("candidate binding promotion policy escaped fail-closed mode")
    source_sha256s = payload.get("source_sha256s", {})
    if set(source_sha256s) != {"discovery", "public_capture", "claim_surfaces", "review_queue"}:
        raise GTMCaseCandidateBindingError("candidate binding source lineage is incomplete")
    if not all(isinstance(value, str) and len(value) == 64 for value in source_sha256s.values()):
        raise GTMCaseCandidateBindingError("candidate binding source lineage hash is invalid")
    for row in records:
        if row.get("quota_credit") != 0 or row.get("automatic_candidate_promotion_allowed") is not False:
            raise GTMCaseCandidateBindingError("candidate binding packet escaped zero-credit boundary")
        gates = row.get("admission_gates")
        if not isinstance(gates, Mapping) or set(gates) != set(GATES):
            raise GTMCaseCandidateBindingError("candidate binding gate set drifted")
        if any(gates[gate] for gate in GATES if gate != "public_capture_current"):
            raise GTMCaseCandidateBindingError("an unresolved evidence gate was auto-passed")
        expected_blockers = [gate for gate in GATES if not gates[gate]]
        if row.get("blocking_requirements") != expected_blockers:
            raise GTMCaseCandidateBindingError("candidate binding blocker list drifted from admission gates")
        receipt = row.get("capture_receipt", {})
        expected_capture_gate = receipt.get("capture_status") == "captured_metadata_only"
        if gates["public_capture_current"] is not expected_capture_gate:
            raise GTMCaseCandidateBindingError("public capture gate drifted from its receipt")
        template = row.get("human_review_template", {})
        if template.get("decision") != "pending" or template.get("source_inspected") is not False:
            raise GTMCaseCandidateBindingError("human review was fabricated")
        for category in CATEGORIES:
            for fragment in row.get("claim_fragments", {}).get(category, []):
                excerpt = fragment.get("bounded_exact_excerpt", "")
                if fragment.get("excerpt_sha256") != hashlib.sha256(excerpt.encode("utf-8")).hexdigest():
                    raise GTMCaseCandidateBindingError("claim excerpt hash drifted")


__all__ = [
    "GTMCaseCandidateBindingError",
    "compile_case_candidate_binding_packets",
    "verify_case_candidate_binding_packets",
]
