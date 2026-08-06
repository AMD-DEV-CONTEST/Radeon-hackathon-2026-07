from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMSeedCandidateNormalizationV2"


class GTMSeedCandidateNormalizationError(ValueError):
    pass


_BUDGET_MAP = {
    "cold_start_zero_paid": "zero_paid",
    "cold_start_low_budget": "low_budget",
    "capital_efficient": "capital_efficient",
    "mixed_budget": "mixed_budget",
    "mature_scaled": "mature_scale",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_seed_candidate_normalization(
    quality_seed: Mapping[str, Any],
    capture_ledger: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    teams = {str(row["team_id"]): row for row in quality_seed.get("teams", [])}
    captures_by_team: dict[str, list[Mapping[str, Any]]] = {}
    for record in capture_ledger.get("records", []):
        if record.get("capture_status") != "captured_metadata_only":
            continue
        for context_id in record.get("source_context_ids", []):
            if str(context_id).startswith("team:"):
                captures_by_team.setdefault(str(context_id).split(":", 1)[1], []).append(record)

    candidates: list[dict[str, Any]] = []
    seen_subverticals: set[str] = set()
    for decision in decisions:
        team_id = str(decision.get("team_id", ""))
        team = teams.get(team_id)
        if team is None:
            raise GTMSeedCandidateNormalizationError(f"unknown seed team: {team_id}")
        subvertical_id = str(decision.get("subvertical_id", ""))
        seen_subverticals.add(subvertical_id)
        budget_tier = _BUDGET_MAP.get(str(team.get("cold_start_budget_tier")))
        if not budget_tier:
            raise GTMSeedCandidateNormalizationError(f"{team_id} lacks a V2-eligible disclosed budget tier")
        captures = captures_by_team.get(team_id, [])
        if not captures:
            raise GTMSeedCandidateNormalizationError(f"{team_id} lacks a successful public source capture")
        receipts = []
        for record in captures:
            source_class = "official_company" if team_id in {
                "clay", "mercury", "plausible", "tally", "beehiiv"
            } else "official_platform"
            receipts.append(
                {
                    "source_url": record["source_url"],
                    "source_class": source_class,
                    "access_method": "ordinary_public_page",
                    "captured_at": record["captured_at"],
                    "content_sha256": record["content_sha256"],
                }
            )
        receipt_hashes = [row["content_sha256"] for row in receipts]
        resource_costs = {
            component: {
                "disclosure_status": "unknown",
                "amount_usd": None,
                "evidence_receipt_sha256s": [],
                "notes": "The source set does not disclose a complete USD cost for this component.",
            }
            for component in ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")
        }
        if budget_tier == "zero_paid":
            resource_costs["paid_media"] = {
                "disclosure_status": "known_zero",
                "amount_usd": 0,
                "evidence_receipt_sha256s": receipt_hashes,
                "notes": "The source-bounded cold-start window explicitly reports no paid media spend; all other costs remain separate.",
            }
        case_id = f"v2-seed-{team_id}"
        candidates.append(
            {
                "case_id": case_id,
                "status": "structured_candidate",
                "subvertical_id": subvertical_id,
                "business_model": decision["business_model"],
                "company": team["team_name"],
                "product": decision["product"],
                "campaign_or_motion": decision["campaign_or_motion"],
                "primary_audience": decision["primary_audience"],
                "observed_start": decision["observed_start"],
                "observed_end": decision["observed_end"],
                "episode_key": (
                    f"{team_id}:{decision['campaign_or_motion_id']}:{decision['quota_market']}:"
                    f"{decision['observed_start']}:{decision['observed_end']}"
                ),
                "company_scale": decision["company_scale"],
                "lifecycle_state": decision["lifecycle_state"],
                "budget_tier": budget_tier,
                "recency_bucket": decision["recency_bucket"],
                "outcome_type": decision["outcome_type"],
                "quota_market": decision["quota_market"],
                "platforms": list(decision["platforms"]),
                "mechanism_hypothesis": team["observable_mechanism"],
                "result_summary": "; ".join(team["reported_outcomes"]),
                "resource_scope": team["cold_start_budget_window"],
                "resource_costs": resource_costs,
                "budget_quota_status": "evidence_gap",
                "budget_classification_evidence_receipt_sha256s": [],
                "classification_basis": decision["classification_basis"],
                "source_receipts": receipts,
                "copy_or_voice_reuse_allowed": False,
                "quota_credit": 0,
            }
        )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_seed_sha256": quality_seed.get("content_sha256"),
        "source_capture_sha256": capture_ledger.get("content_sha256"),
        "candidate_count": len(candidates),
        "distinct_subvertical_count": len(seen_subverticals),
        "quota_eligible_candidate_count": 0,
        "quota_eligible_distinct_subvertical_count": 0,
        "candidates": candidates,
        "promotion_boundary": {
            "mechanism_deep_audit_count": 0,
            "outcome_cross_verification_count": 0,
            "execution_blueprint_count": 0,
            "candidate_status_does_not_prove_effectiveness": True,
        },
        "truth_boundary": (
            "These records preserve V2 identity hypotheses and source hashes, but the seed budget labels are not bound to "
            "complete exact source evidence. They remain zero-credit candidate records until budget classification and every "
            "other CaseCandidateV2 field pass source inspection."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_seed_candidate_normalization(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMSeedCandidateNormalizationError("seed candidate normalization seal is invalid")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or payload.get("candidate_count") != len(candidates):
        raise GTMSeedCandidateNormalizationError("seed candidate aggregate drifted")
    if payload.get("distinct_subvertical_count") != len({row.get("subvertical_id") for row in candidates}):
        raise GTMSeedCandidateNormalizationError("seed candidate subvertical aggregate drifted")
    if any(
        row.get("quota_credit") != 0
        or row.get("budget_quota_status") != "evidence_gap"
        or row.get("budget_classification_evidence_receipt_sha256s") != []
        or row.get("copy_or_voice_reuse_allowed") is not False
        for row in candidates
    ):
        raise GTMSeedCandidateNormalizationError("candidate escaped normalization boundary")
    if payload.get("quota_eligible_candidate_count") != 0 or payload.get("quota_eligible_distinct_subvertical_count") != 0:
        raise GTMSeedCandidateNormalizationError("unreviewed seed budget labels minted quota eligibility")


__all__ = [
    "GTMSeedCandidateNormalizationError",
    "compile_seed_candidate_normalization",
    "verify_seed_candidate_normalization",
]
