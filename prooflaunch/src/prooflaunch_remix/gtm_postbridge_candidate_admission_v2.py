from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard, compile_case_evidence_funnel_coverage


ADMISSION_SCHEMA = "ProofLaunchGTMPostBridgeCaseCandidateAdmissionV2"
CASE_ID = "case-postbridge-2024-2026-content-led-growth"


class GTMPostBridgeCandidateAdmissionError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _verify_seal(payload: Mapping[str, Any], label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMPostBridgeCandidateAdmissionError(f"{label} seal is invalid")


def compile_postbridge_candidate_admission(intake: Mapping[str, Any], ledger: Mapping[str, Any], dossier: Mapping[str, Any], proposal: Mapping[str, Any], existing_candidates: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    _verify_seal(dossier, "Post Bridge dossier")
    _verify_seal(proposal, "Post Bridge proposal")
    if dossier.get("schema") != "ProofLaunchGTMPostBridgeAdmissionDossierV2" or proposal.get("schema") != "ProofLaunchGTMPostBridgeNamedReviewProposalV2":
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge admission inputs use an unexpected schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256") or proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"):
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge proposal lineage is stale")
    records = intake.get("records", [])
    if len(records) != 1:
        raise GTMPostBridgeCandidateAdmissionError("exactly one Post Bridge review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id") or review.get("decision") != "submit_for_admission_gate":
        raise GTMPostBridgeCandidateAdmissionError("review did not submit the bound Post Bridge packet")
    for field, proposal_key in (("field_bindings", "field_bindings"), ("cost_components", "cost_components"), ("exact_claim_bindings", "exact_primary_claim_bindings")):
        if review.get(field) != proposal.get(proposal_key):
            raise GTMPostBridgeCandidateAdmissionError(f"Post Bridge {field} drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()):
        raise GTMPostBridgeCandidateAdmissionError("one or more Post Bridge named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1 or dossier.get("gates", {}).get("named_human_exact_binding") != "pending_named_review":
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge dossier is not at the strict 10/11 boundary")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"):
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge duplicate screen failed")
    sources = {row["source_role"]: row for row in dossier.get("sources", []) if row.get("capture_status") == "captured_and_bounded"}
    if len(sources) != 7 or sum(bool(row.get("independent")) for row in sources.values()) < 2:
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge requires seven captures and two independent surfaces")
    classes = {
        "founder_interview": "public_community",
        "independent_current_analysis": "independent_media",
        "independent_source_accountability": "independent_media",
        "independent_historical_analysis": "independent_media",
        "independent_revenue_dashboard": "independent_media",
        "official_api_pricing": "official_company",
        "founder_product_portfolio": "public_community",
    }
    receipts = [{"source_url": row["source_url"], "source_class": classes[role], "access_method": "ordinary_public_page", "captured_at": row["captured_at"], "content_sha256": row["source_content_sha256"]} for role, row in sources.items()]
    hashes = {role: row["source_content_sha256"] for role, row in sources.items()}
    primary_hash = hashes["founder_interview"]
    costs = {
        "paid_media": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash, hashes["independent_historical_analysis"]], "notes": "Content-led growth is reported, but the complete episode does not prove all paid media was zero."},
        "personnel": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash], "notes": "Founder labor and occasional contractor work are disclosed without a complete personnel amount."},
        "tools": {"disclosure_status": "bounded_estimate", "amount_usd": 200, "evidence_receipt_sha256s": [primary_hash], "notes": "The founder bounds current infrastructure at USD 100–200 monthly; USD 200 is retained as the conservative bound."},
        "creators": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash, hashes["independent_current_analysis"]], "notes": "Founder-produced X and short-form content has no isolated labor amount."},
        "channel_fees": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [hashes["official_api_pricing"]], "notes": "Official API and billing surfaces are visible, but company-side platform and payment fees are not disclosed."},
        "production": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash], "notes": "Initial cash build cost is reported as zero, but founder time is an unpriced economic cost and is not treated as free."},
    }
    fields = proposal["field_bindings"]
    candidate = {
        "case_id": CASE_ID,
        "status": "structured_candidate",
        "subvertical_id": fields["subvertical_ids"][0],
        "business_model": "b2b",
        "company": fields["company"],
        "product": fields["product"],
        "campaign_or_motion": fields["campaign_or_motion"],
        "primary_audience": fields["primary_audience"],
        "observed_start": fields["observed_start"],
        "observed_end": fields["observed_end"],
        "episode_key": dossier["episode_key"],
        "company_scale": fields["company_scale"],
        "lifecycle_state": fields["lifecycle_state"],
        "budget_tier": fields["budget_tier"],
        "recency_bucket": fields["recency_bucket"],
        "outcome_type": fields["outcome_type"],
        "quota_market": fields["quota_market"],
        "platforms": ["x", "tiktok", "instagram", "youtube"],
        "mechanism_hypothesis": fields["mechanism_summary"],
        "result_summary": fields["result_summary"],
        "resource_scope": "Initial cash build cost is reported as zero while labor remains unknown; current infrastructure is bounded at USD 100–200 monthly and every other cost component stays explicit.",
        "resource_costs": costs,
        "budget_quota_status": "source_bound",
        "budget_classification_evidence_receipt_sha256s": [primary_hash],
        "source_receipts": receipts,
        "review_binding": {"reviewer_name": review["reviewer_name"], "reviewed_at": review["reviewed_at"], "review_packet_id": review["review_packet_id"], "review_intake_sha256": _digest(intake)},
        "copy_or_voice_reuse_allowed": False,
        "quota_credit": 1,
    }
    for existing in existing_candidates:
        if existing.get("case_id") == CASE_ID or existing.get("episode_key") == candidate["episode_key"]:
            raise GTMPostBridgeCandidateAdmissionError("Post Bridge candidate or episode already exists")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge candidate failed CaseCandidateV2")
    payload = {
        "schema": ADMISSION_SCHEMA,
        "source_sha256s": {"unified_review_ledger": ledger["content_sha256"], "named_review_intake": _digest(intake), "admission_dossier": dossier["content_sha256"], "named_review_proposal": proposal["content_sha256"]},
        "reviewer_name": review["reviewer_name"],
        "reviewed_at": review["reviewed_at"],
        "admitted_candidate_count": 1,
        "formal_candidate_quota_credit": 1,
        "candidate": candidate,
        "candidate_sha256": _digest(candidate),
        "automatic_external_action_allowed": False,
        "truth_boundary": "This grants one structured-candidate credit only. Revenue remains founder-stated/estimated and it does not prove causality, current transferability, an audit, or a blueprint.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_postbridge_candidate_admission(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, "Post Bridge admission")
    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("formal_candidate_quota_credit") != 1:
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge admission aggregate is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate):
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge candidate binding is invalid")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMPostBridgeCandidateAdmissionError("Post Bridge admission no longer passes CaseCandidateV2")


__all__ = ["ADMISSION_SCHEMA", "CASE_ID", "GTMPostBridgeCandidateAdmissionError", "compile_postbridge_candidate_admission", "verify_postbridge_candidate_admission"]
