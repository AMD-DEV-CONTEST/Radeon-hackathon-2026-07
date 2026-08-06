from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard, compile_case_evidence_funnel_coverage


ADMISSION_SCHEMA = "ProofLaunchGTMBarn2CaseCandidateAdmissionV2"
CASE_ID = "case-barn2-2016-2026-global-plugin-portfolio-plateau"


class GTMBarn2CandidateAdmissionError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _verify_seal(payload: Mapping[str, Any], label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMBarn2CandidateAdmissionError(f"{label} seal is invalid")


def compile_barn2_candidate_admission(intake: Mapping[str, Any], ledger: Mapping[str, Any], dossier: Mapping[str, Any], proposal: Mapping[str, Any], existing_candidates: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    _verify_seal(dossier, "Barn2 dossier")
    _verify_seal(proposal, "Barn2 proposal")
    if dossier.get("schema") != "ProofLaunchGTMBarn2AdmissionDossierV2" or proposal.get("schema") != "ProofLaunchGTMBarn2NamedReviewProposalV2":
        raise GTMBarn2CandidateAdmissionError("Barn2 admission inputs use an unexpected schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256") or proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"):
        raise GTMBarn2CandidateAdmissionError("Barn2 proposal lineage is stale")
    records = intake.get("records", [])
    if len(records) != 1:
        raise GTMBarn2CandidateAdmissionError("exactly one Barn2 review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id") or review.get("decision") != "submit_for_admission_gate":
        raise GTMBarn2CandidateAdmissionError("review did not submit the bound Barn2 packet")
    for field, proposal_key in (("field_bindings", "field_bindings"), ("cost_components", "cost_components"), ("exact_claim_bindings", "exact_primary_claim_bindings")):
        if review.get(field) != proposal.get(proposal_key):
            raise GTMBarn2CandidateAdmissionError(f"Barn2 {field} drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()):
        raise GTMBarn2CandidateAdmissionError("one or more Barn2 named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1 or dossier.get("gates", {}).get("named_human_exact_binding") != "pending_named_review":
        raise GTMBarn2CandidateAdmissionError("Barn2 dossier is not at the strict 10/11 boundary")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"):
        raise GTMBarn2CandidateAdmissionError("Barn2 duplicate screen failed")
    sources = {row["source_role"]: row for row in dossier.get("sources", []) if row.get("capture_status") == "captured_and_bounded"}
    if len(sources) != 7 or sum(bool(row.get("independent")) for row in sources.values()) < 3:
        raise GTMBarn2CandidateAdmissionError("Barn2 requires seven captures and three independent surfaces")
    classes = {"founder_interview_2026": "public_community", "official_transparency_2024": "official_company", "official_transparency_2021": "official_company", "official_about": "official_company", "independent_product_interview": "independent_media", "independent_founder_profile": "independent_media", "independent_revenue_profile": "independent_media"}
    receipts = [{"source_url": row["source_url"], "source_class": classes[role], "access_method": "ordinary_public_page", "captured_at": row["captured_at"], "content_sha256": row["source_content_sha256"]} for role, row in sources.items()]
    hashes = {role: row["source_content_sha256"] for role, row in sources.items()}
    primary_hash, h2024, h2021 = hashes["founder_interview_2026"], hashes["official_transparency_2024"], hashes["official_transparency_2021"]
    costs = {
        "paid_media": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash, h2024], "notes": "SEO, video, outreach and community are described, but no complete paid-media ledger is public."},
        "personnel": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [h2024], "notes": "A 19.5-person team, external CMO service and freelance writers are disclosed without complete compensation."},
        "tools": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash, h2024], "notes": "Development, analytics, automation and AI tools are described without a complete total."},
        "creators": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [h2024], "notes": "Dedicated video, design, marketing and freelance-writing inputs are explicit but not fully priced."},
        "channel_fees": {"disclosure_status": "bounded_estimate", "amount_usd": 21155, "evidence_receipt_sha256s": [h2021], "notes": "USD 21,155 was paid to 486 affiliates in 2021; it is a bounded historical amount, not a complete episode total."},
        "production": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [h2021, h2024], "notes": "High-volume documentation, blog, video, product and support production is not fully costed."},
    }
    fields = proposal["field_bindings"]
    candidate = {
        "case_id": CASE_ID, "status": "structured_candidate", "subvertical_id": fields["subvertical_ids"][0], "business_model": "b2b",
        "company": fields["company"], "product": fields["product"], "campaign_or_motion": fields["campaign_or_motion"], "primary_audience": fields["primary_audience"],
        "observed_start": fields["observed_start"], "observed_end": fields["observed_end"], "episode_key": dossier["episode_key"],
        "company_scale": fields["company_scale"], "lifecycle_state": fields["lifecycle_state"], "budget_tier": fields["budget_tier"],
        "recency_bucket": fields["recency_bucket"], "outcome_type": fields["outcome_type"], "quota_market": fields["quota_market"],
        "platforms": ["youtube", "owned_blog_newsletter", "podcast_rss"],
        "mechanism_hypothesis": fields["mechanism_summary"], "result_summary": fields["result_summary"],
        "resource_scope": "Capital-efficient resources are source-bound through a 19.5-person team, outside marketing support, creators and a USD 21,155 historical affiliate payout; other totals remain unknown.",
        "resource_costs": costs, "budget_quota_status": "source_bound", "budget_classification_evidence_receipt_sha256s": [h2024, h2021],
        "source_receipts": receipts, "review_binding": {"reviewer_name": review["reviewer_name"], "reviewed_at": review["reviewed_at"], "review_packet_id": review["review_packet_id"], "review_intake_sha256": _digest(intake)},
        "copy_or_voice_reuse_allowed": False, "quota_credit": 1,
    }
    for existing in existing_candidates:
        if existing.get("case_id") == CASE_ID or existing.get("episode_key") == candidate["episode_key"]:
            raise GTMBarn2CandidateAdmissionError("Barn2 candidate or episode already exists")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMBarn2CandidateAdmissionError("Barn2 candidate failed CaseCandidateV2")
    payload = {"schema": ADMISSION_SCHEMA, "source_sha256s": {"unified_review_ledger": ledger["content_sha256"], "named_review_intake": _digest(intake), "admission_dossier": dossier["content_sha256"], "named_review_proposal": proposal["content_sha256"]}, "reviewer_name": review["reviewer_name"], "reviewed_at": review["reviewed_at"], "admitted_candidate_count": 1, "formal_candidate_quota_credit": 1, "candidate": candidate, "candidate_sha256": _digest(candidate), "automatic_external_action_allowed": False, "truth_boundary": "This grants one structured-candidate credit only. Revenue and plateau remain founder-stated; diversification success, causality, transferability and blueprint readiness are unproven."}
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_barn2_candidate_admission(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, "Barn2 admission")
    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("formal_candidate_quota_credit") != 1:
        raise GTMBarn2CandidateAdmissionError("Barn2 admission aggregate is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate):
        raise GTMBarn2CandidateAdmissionError("Barn2 candidate binding is invalid")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMBarn2CandidateAdmissionError("Barn2 admission no longer passes CaseCandidateV2")


__all__ = ["ADMISSION_SCHEMA", "CASE_ID", "GTMBarn2CandidateAdmissionError", "compile_barn2_candidate_admission", "verify_barn2_candidate_admission"]
