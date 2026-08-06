from __future__ import annotations
import hashlib, json
from typing import Any, Mapping, Sequence
from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard, compile_case_evidence_funnel_coverage

ADMISSION_SCHEMA = "ProofLaunchGTMSociallyCaseCandidateAdmissionV2"
CASE_ID = "case-socially-2023-2024-bootstrapped-community-growth"
class GTMSociallyCandidateAdmissionError(ValueError): pass
def _canonical(value: Any) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
def _digest(value: Any) -> str: return hashlib.sha256(_canonical(value).encode()).hexdigest()
def _seal(payload: Mapping[str, Any], label: str) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned): raise GTMSociallyCandidateAdmissionError(f"{label} seal is invalid")

def compile_socially_candidate_admission(intake: Mapping[str, Any], ledger: Mapping[str, Any], dossier: Mapping[str, Any], proposal: Mapping[str, Any], existing_candidates: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger); _seal(dossier, "Socially dossier"); _seal(proposal, "Socially proposal")
    if dossier.get("schema") != "ProofLaunchGTMSociallyAdmissionDossierV2" or proposal.get("schema") != "ProofLaunchGTMSociallyNamedReviewProposalV2": raise GTMSociallyCandidateAdmissionError("Socially admission inputs use an unexpected schema")
    if proposal.get("source_unified_review_ledger_sha256") != ledger.get("content_sha256") or proposal.get("source_admission_dossier_sha256") != dossier.get("content_sha256"): raise GTMSociallyCandidateAdmissionError("Socially proposal lineage is stale")
    records = intake.get("records", [])
    if len(records) != 1: raise GTMSociallyCandidateAdmissionError("exactly one Socially review is required")
    review = records[0]
    if review.get("review_packet_id") != proposal.get("review_packet_id") or review.get("decision") != "submit_for_admission_gate": raise GTMSociallyCandidateAdmissionError("review did not submit the bound Socially packet")
    for field, key in (("field_bindings", "field_bindings"), ("cost_components", "cost_components"), ("exact_claim_bindings", "exact_primary_claim_bindings")):
        if review.get(field) != proposal.get(key): raise GTMSociallyCandidateAdmissionError(f"Socially {field} drifted from the inspected proposal")
    if not all(review.get("gate_decisions", {}).values()): raise GTMSociallyCandidateAdmissionError("one or more Socially named-review gates failed")
    if dossier.get("evidence_ready_gate_count") != 10 or dossier.get("blocking_gate_count") != 1 or dossier.get("gates", {}).get("named_human_exact_binding") != "pending_named_review": raise GTMSociallyCandidateAdmissionError("Socially dossier is not at the strict 10/11 boundary")
    duplicate = dossier.get("duplicate_screen", {})
    if duplicate.get("exact_content_mirror_detected") or duplicate.get("additional_case_episode_collision_detected"): raise GTMSociallyCandidateAdmissionError("Socially duplicate screen failed")
    sources = {row["source_role"]: row for row in dossier.get("sources", []) if row.get("capture_status") == "captured_and_bounded"}
    if len(sources) != 7 or sum(bool(row.get("independent")) for row in sources.values()) < 4: raise GTMSociallyCandidateAdmissionError("Socially requires seven captures and four independent surfaces")
    classes = {"independent_financial_profile": "independent_media", "independent_company_interview": "independent_media", "independent_business_reconstruction": "independent_media", "founder_progress_update": "public_community", "official_product": "official_company", "official_launch_syndication": "official_company", "independent_founder_identity": "independent_media"}
    receipts = [{"source_url": row["source_url"], "source_class": classes[role], "access_method": "ordinary_public_page", "captured_at": row["captured_at"], "content_sha256": row["source_content_sha256"]} for role, row in sources.items()]
    hashes = {role: row["source_content_sha256"] for role, row in sources.items()}
    primary = hashes["independent_financial_profile"]
    costs = {
        "paid_media": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary], "notes": "No complete paid-media ledger is public; bootstrapped does not mean zero paid media."},
        "personnel": {"disclosure_status": "disclosed", "amount_usd": 7000, "currency": "USD", "period": "month", "evidence_receipt_sha256s": [primary], "notes": "Public monthly team-salary snapshot; complete compensation scope is unknown."},
        "tools": {"disclosure_status": "disclosed", "amount_usd": 500, "currency": "USD", "period": "month", "evidence_receipt_sha256s": [primary], "notes": "Public monthly software subscription snapshot including Canva and Figma."},
        "creators": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary], "notes": "Founder, community and content labor is not separately priced."},
        "channel_fees": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary], "notes": "Payment, lifetime-deal, partner and enterprise-sales fees are incomplete."},
        "production": {"disclosure_status": "unknown", "amount_usd": None, "evidence_receipt_sha256s": [primary, hashes["official_product"]], "notes": "AWS USD 2,000/month and Cloudflare USD 2,200/year are explicit infrastructure snapshots; complete app, product and creative production totals are unknown."},
    }
    f = proposal["field_bindings"]
    candidate = {"case_id": CASE_ID, "status": "structured_candidate", "subvertical_id": f["subvertical_ids"][0], "business_model": "b2b", "company": f["company"], "product": f["product"], "campaign_or_motion": f["campaign_or_motion"], "primary_audience": f["primary_audience"], "observed_start": f["observed_start"], "observed_end": f["observed_end"], "episode_key": dossier["episode_key"], "company_scale": f["company_scale"], "lifecycle_state": f["lifecycle_state"], "budget_tier": f["budget_tier"], "recency_bucket": f["recency_bucket"], "outcome_type": f["outcome_type"], "quota_market": f["quota_market"], "platforms": ["owned_blog_newsletter", "linkedin"], "mechanism_hypothesis": f["mechanism_summary"], "result_summary": f["result_summary"], "resource_scope": "Capital-efficient classification is source-bound to line-item monthly and annual operating snapshots; it is not a zero-budget claim and all missing components remain unknown.", "resource_costs": costs, "budget_quota_status": "source_bound", "budget_classification_evidence_receipt_sha256s": [primary], "source_receipts": receipts, "review_binding": {"reviewer_name": review["reviewer_name"], "reviewed_at": review["reviewed_at"], "review_packet_id": review["review_packet_id"], "review_intake_sha256": _digest(intake)}, "copy_or_voice_reuse_allowed": False, "quota_credit": 1}
    for existing in existing_candidates:
        if existing.get("case_id") == CASE_ID or existing.get("episode_key") == candidate["episode_key"]: raise GTMSociallyCandidateAdmissionError("Socially candidate or episode already exists")
    coverage = compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])
    if coverage["global_funnel_counts"]["structured_candidates"] != 1: raise GTMSociallyCandidateAdmissionError("Socially candidate failed CaseCandidateV2")
    payload = {"schema": ADMISSION_SCHEMA, "source_sha256s": {"unified_review_ledger": ledger["content_sha256"], "named_review_intake": _digest(intake), "admission_dossier": dossier["content_sha256"], "named_review_proposal": proposal["content_sha256"]}, "reviewer_name": review["reviewer_name"], "reviewed_at": review["reviewed_at"], "admitted_candidate_count": 1, "formal_candidate_quota_credit": 1, "candidate": candidate, "candidate_sha256": _digest(candidate), "automatic_external_action_allowed": False, "truth_boundary": "One structured-candidate credit only. Revenue and scale remain founder-reported, operator/product boundaries are preserved, cost disclosure is partial, and causality, transferability and blueprint readiness are unproven."}
    payload["content_sha256"] = _digest(payload)
    return payload

def verify_socially_candidate_admission(payload: Mapping[str, Any]) -> None:
    _seal(payload, "Socially admission")
    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("formal_candidate_quota_credit") != 1: raise GTMSociallyCandidateAdmissionError("Socially admission aggregate is invalid")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping) or payload.get("candidate_sha256") != _digest(candidate): raise GTMSociallyCandidateAdmissionError("Socially candidate binding is invalid")
    if compile_case_evidence_funnel_coverage(build_case_evidence_funnel_standard(), [candidate], [], [], [])["global_funnel_counts"]["structured_candidates"] != 1: raise GTMSociallyCandidateAdmissionError("Socially admission no longer passes CaseCandidateV2")

__all__ = ["ADMISSION_SCHEMA", "CASE_ID", "GTMSociallyCandidateAdmissionError", "compile_socially_candidate_admission", "verify_socially_candidate_admission"]
