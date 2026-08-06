from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard, compile_case_evidence_funnel_coverage


ADMISSION_SCHEMA = "ProofLaunchGTMBufferCaseCandidateAdmissionV2"
CASE_ID = "case-buffer-2010-2016-content-compound-growth"


class GTMBufferCandidateAdmissionError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _verify_seal(payload: Mapping[str, Any], label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMBufferCandidateAdmissionError(f"{label} seal is invalid")


def compile_buffer_candidate_admission(
    intake: Mapping[str, Any],
    ledger: Mapping[str, Any],
    dossier: Mapping[str, Any],
    proposal: Mapping[str, Any],
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    _verify_seal(dossier, "Buffer dossier")
    _verify_seal(proposal, "Buffer proposal")
    if dossier.get("schema") != "ProofLaunchGTMBufferAdmissionDossierV2" or proposal.get("schema") != "ProofLaunchGTMBufferNamedReviewProposalV2":
        raise GTMBufferCandidateAdmissionError("Buffer admission inputs use an unexpected schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256") or proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"):
        raise GTMBufferCandidateAdmissionError("Buffer proposal lineage is stale")
    records = intake.get("records", [])
    if len(records) != 1:
        raise GTMBufferCandidateAdmissionError("exactly one Buffer review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id") or review.get("decision") != "submit_for_admission_gate":
        raise GTMBufferCandidateAdmissionError("review did not submit the bound Buffer packet")
    for field, proposal_key in (
        ("field_bindings", "field_bindings"),
        ("cost_components", "cost_components"),
        ("exact_claim_bindings", "exact_primary_claim_bindings"),
    ):
        if review.get(field) != proposal.get(proposal_key):
            raise GTMBufferCandidateAdmissionError(f"Buffer {field} drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()):
        raise GTMBufferCandidateAdmissionError("one or more Buffer named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1:
        raise GTMBufferCandidateAdmissionError("Buffer dossier is not at 10/11")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"):
        raise GTMBufferCandidateAdmissionError("Buffer duplicate screen failed")
    sources = {
        row["source_role"]: row
        for row in dossier.get("sources", [])
        if row.get("capture_status") == "captured_and_bounded"
    }
    if len(sources) != 7 or sum(bool(row.get("independent")) for row in sources.values()) < 2:
        raise GTMBufferCandidateAdmissionError("Buffer requires seven captures and two independent surfaces")
    classes = {
        "company_growth_postmortem": "official_company",
        "company_transparent_pricing": "official_company",
        "company_revenue_dashboard": "official_company",
        "independent_tech_press": "independent_media",
        "independent_strategy_analysis": "independent_media",
        "official_legal_identity": "official_company",
        "official_company_profile": "official_company",
    }
    receipts = [{
        "source_url": row["source_url"],
        "source_class": classes[role],
        "access_method": "ordinary_public_page",
        "captured_at": row["captured_at"],
        "content_sha256": row["source_content_sha256"],
    } for role, row in sources.items()]
    primary_hash = sources["company_growth_postmortem"]["source_content_sha256"]
    pricing_hash = sources["company_transparent_pricing"]["source_content_sha256"]
    costs = {
        "paid_media": {"disclosure_status": "disclosed", "amount_usd": 6302.40, "evidence_receipt_sha256s": [pricing_hash], "notes": "The transparent-pricing ledger reports USD 6,302.40 monthly advertising and marketing."},
        "personnel": {"disclosure_status": "disclosed", "amount_usd": 223939.74, "evidence_receipt_sha256s": [pricing_hash], "notes": "The transparent-pricing ledger reports USD 223,939.74 in monthly team salaries."},
        "tools": {"disclosure_status": "disclosed", "amount_usd": 14161.79, "evidence_receipt_sha256s": [pricing_hash], "notes": "The transparent-pricing ledger reports USD 14,161.79 monthly for tools, excluding separately listed servers."},
        "creators": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash, pricing_hash], "notes": "The growth source identifies content marketing and the pricing source allocates marketing salary, but creator-specific cost is not isolated."},
        "channel_fees": {"disclosure_status": "disclosed", "amount_usd": 13885.42, "evidence_receipt_sha256s": [pricing_hash], "notes": "The transparent-pricing ledger reports USD 13,885.42 monthly in Stripe payment channel fees."},
        "production": {"disclosure_status": "bounded_estimate", "amount_usd": 2577.81, "evidence_receipt_sha256s": [pricing_hash], "notes": "Computer and equipment cost USD 2,577.81 monthly; this is a bounded production input, not a complete content-production total."},
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
        "platforms": ["x", "owned_blog_newsletter"],
        "mechanism_hypothesis": fields["mechanism_summary"],
        "result_summary": fields["result_summary"],
        "resource_scope": "A source-bound monthly ledger records media, salaries, tools, fees and equipment; creator-specific labor remains explicitly unknown.",
        "resource_costs": costs,
        "budget_quota_status": "source_bound",
        "budget_classification_evidence_receipt_sha256s": [pricing_hash],
        "source_receipts": receipts,
        "review_binding": {
            "reviewer_name": review["reviewer_name"],
            "reviewed_at": review["reviewed_at"],
            "review_packet_id": review["review_packet_id"],
            "review_intake_sha256": _digest(intake),
        },
        "copy_or_voice_reuse_allowed": False,
        "quota_credit": 1,
    }
    for existing in existing_candidates:
        if existing.get("case_id") == CASE_ID or existing.get("episode_key") == candidate["episode_key"]:
            raise GTMBufferCandidateAdmissionError("Buffer candidate or episode already exists")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMBufferCandidateAdmissionError("Buffer candidate failed the CaseCandidateV2 contract")
    payload = {
        "schema": ADMISSION_SCHEMA,
        "source_sha256s": {
            "unified_review_ledger": ledger["content_sha256"],
            "named_review_intake": _digest(intake),
            "admission_dossier": dossier["content_sha256"],
            "named_review_proposal": proposal["content_sha256"],
        },
        "reviewer_name": review["reviewer_name"],
        "reviewed_at": review["reviewed_at"],
        "admitted_candidate_count": 1,
        "formal_candidate_quota_credit": 1,
        "candidate": candidate,
        "candidate_sha256": _digest(candidate),
        "automatic_external_action_allowed": False,
        "truth_boundary": "This admission grants one historical structured-candidate credit only; it does not prove single-channel causality, current transferability, mechanism audit, outcome audit or blueprint completion.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_buffer_candidate_admission(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, "Buffer admission")
    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("formal_candidate_quota_credit") != 1:
        raise GTMBufferCandidateAdmissionError("Buffer admission aggregate is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate):
        raise GTMBufferCandidateAdmissionError("Buffer candidate binding is invalid")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMBufferCandidateAdmissionError("Buffer admission no longer passes CaseCandidateV2")


__all__ = ["ADMISSION_SCHEMA", "CASE_ID", "GTMBufferCandidateAdmissionError", "compile_buffer_candidate_admission", "verify_buffer_candidate_admission"]
