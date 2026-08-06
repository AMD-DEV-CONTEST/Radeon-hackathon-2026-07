from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import (
    build_case_evidence_funnel_standard,
    compile_case_evidence_funnel_coverage,
)


ADMISSION_SCHEMA = "ProofLaunchGTMEmailOctopusCaseCandidateAdmissionV2"
CASE_ID = "case-emailoctopus-2014-2023-compound-growth"


class GTMEmailOctopusCandidateAdmissionError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _verify_seal(payload: Mapping[str, Any], *, label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMEmailOctopusCandidateAdmissionError(f"{label} seal is invalid")


def _captured_sources(dossier: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = {
        str(row.get("source_role")): row
        for row in dossier.get("sources", [])
        if isinstance(row, Mapping) and row.get("capture_status") == "captured_and_bounded"
    }
    if len(rows) != 7 or dossier.get("captured_source_count") != 7:
        raise GTMEmailOctopusCandidateAdmissionError("all seven bounded public captures are required")
    if dossier.get("independent_captured_source_count", 0) < 2:
        raise GTMEmailOctopusCandidateAdmissionError("two independent outcome surfaces are required")
    return rows


def _source_class(role: str) -> str:
    return {
        "company_marketing_postmortem": "official_company",
        "founder_ama": "public_community",
        "independent_founder_profile": "independent_media",
        "independent_accounting_partner_case": "independent_media",
        "company_resource_history": "official_company",
        "official_legal_identity": "official_company",
        "official_company_registry": "official_filing",
    }[role]


def compile_emailoctopus_candidate_admission(
    intake: Mapping[str, Any],
    ledger: Mapping[str, Any],
    dossier: Mapping[str, Any],
    proposal: Mapping[str, Any],
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Admit exactly one named-human-reviewed EmailOctopus episode.

    The browser proposal cannot call this function. The function rechecks the
    source-bound dossier, named intake, identity, episode, deduplication, costs,
    and the complete CaseCandidateV2 contract before issuing one quota credit.
    """

    validate_unified_review_intake(intake, ledger)
    _verify_seal(dossier, label="EmailOctopus admission dossier")
    _verify_seal(proposal, label="EmailOctopus named-review proposal")
    if dossier.get("schema") != "ProofLaunchGTMEmailOctopusAdmissionDossierV2":
        raise GTMEmailOctopusCandidateAdmissionError("unexpected EmailOctopus dossier schema")
    if proposal.get("schema") != "ProofLaunchGTMEmailOctopusNamedReviewProposalV2":
        raise GTMEmailOctopusCandidateAdmissionError("unexpected EmailOctopus proposal schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256"):
        raise GTMEmailOctopusCandidateAdmissionError("proposal is stale against the unified ledger")
    if proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"):
        raise GTMEmailOctopusCandidateAdmissionError("proposal is stale against the admission dossier")
    records = intake.get("records", [])
    if len(records) != 1:
        raise GTMEmailOctopusCandidateAdmissionError("exactly one EmailOctopus named review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id"):
        raise GTMEmailOctopusCandidateAdmissionError("named review targets the wrong packet")
    if review.get("decision") != "submit_for_admission_gate":
        raise GTMEmailOctopusCandidateAdmissionError("named reviewer did not submit this episode for admission")
    if review.get("field_bindings") != proposal.get("field_bindings"):
        raise GTMEmailOctopusCandidateAdmissionError("named-review field bindings drifted from the inspected proposal")
    if review.get("cost_components") != proposal.get("cost_components"):
        raise GTMEmailOctopusCandidateAdmissionError("named-review cost bindings drifted from the inspected proposal")
    if review.get("exact_claim_bindings") != proposal.get("exact_primary_claim_bindings"):
        raise GTMEmailOctopusCandidateAdmissionError("named-review exact claim bindings drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()):
        raise GTMEmailOctopusCandidateAdmissionError("one or more named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1:
        raise GTMEmailOctopusCandidateAdmissionError("machine dossier is not at the expected 10/11 boundary")
    if dossier.get("gates", {}).get("named_human_exact_binding") != "pending_named_review":
        raise GTMEmailOctopusCandidateAdmissionError("machine dossier fabricated the named-human gate")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"):
        raise GTMEmailOctopusCandidateAdmissionError("EmailOctopus duplicate screen failed")

    fields = proposal["field_bindings"]
    sources = _captured_sources(dossier)
    receipts = [
        {
            "source_url": row["source_url"],
            "source_class": _source_class(role),
            "access_method": "ordinary_public_page",
            "captured_at": row["captured_at"],
            "content_sha256": row["source_content_sha256"],
        }
        for role, row in sources.items()
    ]
    hashes = {role: row["source_content_sha256"] for role, row in sources.items()}
    primary_hash = hashes["company_marketing_postmortem"]
    ama_hash = hashes["founder_ama"]
    resource_hash = hashes["company_resource_history"]
    resource_costs = {
        "paid_media": {
            "disclosure_status": "disclosed",
            "amount_usd": 15000,
            "evidence_receipt_sha256s": [primary_hash],
            "notes": "The company postmortem reports approximately USD 15,000 monthly Google Ads; it separately records a USD 1,000 newsletter test and GBP 275 per podcast episode.",
        },
        "personnel": {
            "disclosure_status": "unknown",
            "amount_usd": None,
            "evidence_receipt_sha256s": [ama_hash],
            "notes": "The founder AMA identifies two full-time founders and a remote team of nine, but no complete personnel amount is disclosed.",
        },
        "tools": {
            "disclosure_status": "unknown",
            "amount_usd": None,
            "evidence_receipt_sha256s": [ama_hash],
            "notes": "Hosting is described as approximately ten percent of early revenue, but the episode has no source-bound USD tool total.",
        },
        "creators": {
            "disclosure_status": "unknown",
            "amount_usd": None,
            "evidence_receipt_sha256s": [resource_hash],
            "notes": "The company history reports up to five freelancers across technical, design, and content work without a complete amount.",
        },
        "channel_fees": {
            "disclosure_status": "bounded_estimate",
            "amount_usd": 3500,
            "evidence_receipt_sha256s": [primary_hash],
            "notes": "The company postmortem bounds affiliate payments below USD 3,500 monthly; USD 3,500 is retained as the conservative upper bound.",
        },
        "production": {
            "disclosure_status": "unknown",
            "amount_usd": None,
            "evidence_receipt_sha256s": [ama_hash],
            "notes": "The founder AMA identifies the domain purchase and Fiverr logo production, but the complete production amount is not disclosed.",
        },
    }
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
        "platforms": ["reddit", "podcast_rss", "owned_blog_newsletter"],
        "mechanism_hypothesis": fields["mechanism_summary"],
        "result_summary": fields["result_summary"],
        "resource_scope": "Six components recorded independently: paid media and channel fees are source-bounded; personnel, tools, creators, and production amounts remain explicitly unknown.",
        "resource_costs": resource_costs,
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
        if existing.get("case_id") == candidate["case_id"] or existing.get("episode_key") == candidate["episode_key"]:
            raise GTMEmailOctopusCandidateAdmissionError("candidate or episode already exists in the target registry")
    standard = build_case_evidence_funnel_standard()
    coverage = compile_case_evidence_funnel_coverage(standard, [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMEmailOctopusCandidateAdmissionError("CaseCandidateV2 contract did not issue exactly one quota credit")
    admission = {
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
        "truth_boundary": "Admission grants one structured-candidate quota credit only. It does not grant a mechanism audit, outcome audit, execution blueprint, causal claim, publication, spend, or memory promotion.",
    }
    admission["content_sha256"] = _digest(admission)
    return admission


def verify_emailoctopus_candidate_admission(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, label="EmailOctopus candidate admission")
    if payload.get("schema") != ADMISSION_SCHEMA:
        raise GTMEmailOctopusCandidateAdmissionError("EmailOctopus admission schema is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate):
        raise GTMEmailOctopusCandidateAdmissionError("admitted candidate binding is invalid")
    if payload.get("admitted_candidate_count") != 1 or payload.get("formal_candidate_quota_credit") != 1:
        raise GTMEmailOctopusCandidateAdmissionError("admission did not issue exactly one quota credit")
    standard = build_case_evidence_funnel_standard()
    coverage = compile_case_evidence_funnel_coverage(standard, [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1:
        raise GTMEmailOctopusCandidateAdmissionError("admitted candidate no longer passes CaseCandidateV2")


__all__ = [
    "ADMISSION_SCHEMA",
    "CASE_ID",
    "GTMEmailOctopusCandidateAdmissionError",
    "compile_emailoctopus_candidate_admission",
    "verify_emailoctopus_candidate_admission",
]
