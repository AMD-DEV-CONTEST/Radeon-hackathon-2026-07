from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard, compile_case_evidence_funnel_coverage


ADMISSION_SCHEMA = "ProofLaunchGTMFlodeskCaseCandidateAdmissionV2"
CASE_ID = "case-flodesk-2019-2026-viral-product-growth"


class GTMFlodeskCandidateAdmissionError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _verify_seal(payload: Mapping[str, Any], label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMFlodeskCandidateAdmissionError(f"{label} seal is invalid")


def compile_flodesk_candidate_admission(
    intake: Mapping[str, Any],
    ledger: Mapping[str, Any],
    dossier: Mapping[str, Any],
    proposal: Mapping[str, Any],
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    _verify_seal(dossier, "Flodesk dossier")
    _verify_seal(proposal, "Flodesk proposal")
    if dossier.get("schema") != "ProofLaunchGTMFlodeskAdmissionDossierV2" or proposal.get("schema") != "ProofLaunchGTMFlodeskNamedReviewProposalV2":
        raise GTMFlodeskCandidateAdmissionError("Flodesk admission inputs use an unexpected schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256") or proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"):
        raise GTMFlodeskCandidateAdmissionError("Flodesk proposal lineage is stale")
    records = intake.get("records", [])
    if len(records) != 1:
        raise GTMFlodeskCandidateAdmissionError("exactly one Flodesk review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id") or review.get("decision") != "submit_for_admission_gate":
        raise GTMFlodeskCandidateAdmissionError("review did not submit the bound Flodesk packet")
    for field, proposal_key in (
        ("field_bindings", "field_bindings"),
        ("cost_components", "cost_components"),
        ("exact_claim_bindings", "exact_primary_claim_bindings"),
    ):
        if review.get(field) != proposal.get(proposal_key):
            raise GTMFlodeskCandidateAdmissionError(f"Flodesk {field} drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()):
        raise GTMFlodeskCandidateAdmissionError("one or more Flodesk named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1:
        raise GTMFlodeskCandidateAdmissionError("Flodesk dossier is not at 10/11")
    if dossier.get("gates", {}).get("named_human_exact_binding") != "pending_named_review":
        raise GTMFlodeskCandidateAdmissionError("Flodesk dossier fabricated the named-human gate")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"):
        raise GTMFlodeskCandidateAdmissionError("Flodesk duplicate screen failed")
    sources = {
        row["source_role"]: row
        for row in dossier.get("sources", [])
        if row.get("capture_status") == "captured_and_bounded"
    }
    if len(sources) != 7 or sum(bool(row.get("independent")) for row in sources.values()) < 2:
        raise GTMFlodeskCandidateAdmissionError("Flodesk requires seven captures and two independent surfaces")
    classes = {
        "founder_interview": "public_community",
        "company_information": "official_company",
        "company_milestone": "official_company",
        "independent_cloud_profile": "independent_media",
        "official_pricing": "official_company",
        "independent_founder_podcast": "independent_media",
        "official_legal_identity": "official_company",
    }
    receipts = [{
        "source_url": row["source_url"],
        "source_class": classes[role],
        "access_method": "ordinary_public_page",
        "captured_at": row["captured_at"],
        "content_sha256": row["source_content_sha256"],
    } for role, row in sources.items()]
    hashes = {role: row["source_content_sha256"] for role, row in sources.items()}
    primary_hash = hashes["founder_interview"]
    costs = {
        "paid_media": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash], "notes": "Organic and word-of-mouth growth are reported, but no source proves paid media was zero or discloses its amount."},
        "personnel": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [hashes["independent_cloud_profile"], primary_hash], "notes": "Team sizes are reported at different milestones, but the complete personnel cost is not disclosed."},
        "tools": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [hashes["company_milestone"]], "notes": "Product and infrastructure scope is visible without a source-bound tool total."},
        "creators": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary_hash], "notes": "Founder-led design and brand work are described without isolated creator labor cost."},
        "channel_fees": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [hashes["official_pricing"]], "notes": "Pricing and distribution surfaces are public, but the company's channel-fee total is not disclosed."},
        "production": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [hashes["company_milestone"]], "notes": "Design and engineering production are described without a complete production amount."},
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
        "platforms": ["owned_blog_newsletter"],
        "mechanism_hypothesis": fields["mechanism_summary"],
        "result_summary": fields["result_summary"],
        "resource_scope": "The initial resource pool is source-bounded at approximately USD 90K pooled savings; all six component amounts remain explicitly unknown.",
        "resource_costs": costs,
        "budget_quota_status": "source_bound",
        "budget_classification_evidence_receipt_sha256s": [primary_hash],
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
            raise GTMFlodeskCandidateAdmissionError("Flodesk candidate or episode already exists")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMFlodeskCandidateAdmissionError("Flodesk candidate failed the CaseCandidateV2 contract")
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
        "truth_boundary": "This admission grants one structured-candidate credit only; it does not prove single-channel causality, current transferability, mechanism audit, outcome audit or blueprint completion.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_flodesk_candidate_admission(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, "Flodesk admission")
    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("formal_candidate_quota_credit") != 1:
        raise GTMFlodeskCandidateAdmissionError("Flodesk admission aggregate is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate):
        raise GTMFlodeskCandidateAdmissionError("Flodesk candidate binding is invalid")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMFlodeskCandidateAdmissionError("Flodesk admission no longer passes CaseCandidateV2")


__all__ = ["ADMISSION_SCHEMA", "CASE_ID", "GTMFlodeskCandidateAdmissionError", "compile_flodesk_candidate_admission", "verify_flodesk_candidate_admission"]
