from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_case_evidence_funnel_v2 import FUNNEL_TARGETS, QUOTA_DIMENSIONS


SCHEMA = "ProofLaunchGTMCandidateTriageLedgerV2"
SELECTION_TARGET = FUNNEL_TARGETS["mechanism_deep_audits"]


class GTMCandidateTriageError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


def _scaled_targets(quotas: Mapping[str, int], target: int = SELECTION_TARGET) -> dict[str, int]:
    exact = {key: value * target / sum(quotas.values()) for key, value in quotas.items()}
    floors = {key: int(value) for key, value in exact.items()}
    remainder = target - sum(floors.values())
    order = sorted(quotas, key=lambda key: (-(exact[key] - floors[key]), key))
    for key in order[:remainder]:
        floors[key] += 1
    return floors


SELECTION_MARGINAL_TARGETS = {
    dimension: _scaled_targets(quotas)
    for dimension, quotas in QUOTA_DIMENSIONS.items()
}


def score_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(candidate.get("case_id") or "")
    if not case_id:
        raise GTMCandidateTriageError("candidate lacks case_id")
    required_fields = (
        "company", "product", "campaign_or_motion", "primary_audience", "observed_start",
        "observed_end", "episode_key", "mechanism_hypothesis", "result_summary", "resource_scope",
    )
    completeness = sum(bool(str(candidate.get(field) or "").strip()) for field in required_fields) / len(required_fields)
    receipts = candidate.get("source_receipts") if isinstance(candidate.get("source_receipts"), list) else []
    source_classes = {str(row.get("source_class")) for row in receipts if isinstance(row, Mapping) and row.get("source_class")}
    costs = candidate.get("resource_costs") if isinstance(candidate.get("resource_costs"), Mapping) else {}
    disclosed_costs = sum(
        isinstance(row, Mapping) and row.get("disclosure_status") in {"known_zero", "disclosed", "bounded_estimate"}
        for row in costs.values()
    )
    evidence_score = _clamp(
        completeness * 50
        + min(len(receipts), 3) / 3 * 20
        + min(len(source_classes), 2) / 2 * 15
        + disclosed_costs / max(1, len(costs)) * 15
    )

    recency_score = {
        "three_to_six_months": 100,
        "six_to_twelve_months": 85,
        "twelve_to_twenty_four_months": 65,
        "historical_mechanism": 35,
    }.get(str(candidate.get("recency_bucket")), 0)

    mechanism = str(candidate.get("mechanism_hypothesis") or "")
    mechanism_tokens = re.findall(r"\b[\w'-]+\b", mechanism.casefold())
    mechanism_markers = sum(
        marker in mechanism.casefold()
        for marker in ("through", "because", "via", "loop", "sequence", "distribution", "conversion", "retention")
    )
    mechanism_score = _clamp(
        min(len(mechanism_tokens), 80) / 80 * 45
        + min(mechanism_markers, 4) / 4 * 20
        + (15 if candidate.get("primary_audience") else 0)
        + (10 if candidate.get("platforms") else 0)
        + (10 if candidate.get("resource_scope") else 0)
    )

    outcome = str(candidate.get("result_summary") or "")
    outcome_folded = outcome.casefold()
    number_count = len(re.findall(r"(?<!\w)(?:[$£€]?\d[\d,.]*%?|\d+(?:\.\d+)?[mkb])", outcome_folded))
    outcome_markers = sum(
        marker in outcome_folded
        for marker in ("revenue", "profit", "retention", "order", "pipeline", "customer", "conversion", "activation", "churn", "arr")
    )
    time_markers = sum(marker in outcome_folded for marker in ("day", "week", "month", "quarter", "year"))
    independent_classes = source_classes - {"official_company", "official_platform"}
    outcome_score = _clamp(
        min(number_count, 4) / 4 * 30
        + min(outcome_markers, 4) / 4 * 30
        + min(time_markers, 2) / 2 * 15
        + min(len(outcome), 320) / 320 * 15
        + min(len(independent_classes), 1) * 10
    )
    composite = _clamp(evidence_score * 0.30 + recency_score * 0.20 + mechanism_score * 0.25 + outcome_score * 0.25)
    return {
        "case_id": case_id,
        "subvertical_id": str(candidate.get("subvertical_id") or ""),
        "evidence_completeness_score": evidence_score,
        "recency_score": recency_score,
        "mechanism_clarity_score": mechanism_score,
        "outcome_quality_score": outcome_score,
        "composite_triage_score": composite,
        "machine_triage_only": True,
        "human_source_review_required": True,
        "quota_credit": 0,
    }


def _choose_stratified(candidates: Sequence[Mapping[str, Any]], score_by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    remaining = [dict(row) for row in candidates]
    selected: list[str] = []
    counts = {dimension: Counter() for dimension in SELECTION_MARGINAL_TARGETS}
    while remaining and len(selected) < SELECTION_TARGET:
        def merit(row: Mapping[str, Any]) -> tuple[float, float, str]:
            deficit_gain = 0.0
            for dimension, targets in SELECTION_MARGINAL_TARGETS.items():
                bucket = str(row.get(dimension) or "")
                target = targets.get(bucket, 0)
                current = counts[dimension][bucket]
                if current < target:
                    deficit_gain += 100.0 * (target - current) / max(1, target)
                else:
                    deficit_gain -= 50.0 * (current - target + 1) / max(1, target)
            score = float(score_by_id[str(row["case_id"])]["composite_triage_score"])
            return (deficit_gain, score, str(row["case_id"]))
        chosen = max(remaining, key=merit)
        remaining.remove(chosen)
        selected.append(str(chosen["case_id"]))
        for dimension in counts:
            counts[dimension][str(chosen.get(dimension) or "")] += 1
    return selected


def compile_candidate_triage(
    candidates: Sequence[Mapping[str, Any]],
    *,
    subvertical_ids: Sequence[str],
) -> dict[str, Any]:
    candidate_ids = [str(row.get("case_id") or "") for row in candidates]
    if not all(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        raise GTMCandidateTriageError("candidate IDs must be non-empty and unique")
    scores = [score_candidate(row) for row in candidates]
    score_by_id = {row["case_id"]: row for row in scores}
    rows = []
    for subvertical_id in subvertical_ids:
        pool = [row for row in candidates if row.get("subvertical_id") == subvertical_id]
        selected_ids = _choose_stratified(pool, score_by_id)
        selected = [row for row in pool if row["case_id"] in selected_ids]
        marginal_counts = {
            dimension: dict(sorted(Counter(str(row.get(dimension) or "") for row in selected).items()))
            for dimension in SELECTION_MARGINAL_TARGETS
        }
        marginal_deficits = {
            dimension: {
                bucket: max(0, target - marginal_counts[dimension].get(bucket, 0))
                for bucket, target in targets.items()
            }
            for dimension, targets in SELECTION_MARGINAL_TARGETS.items()
        }
        deficit_total = sum(sum(values.values()) for values in marginal_deficits.values())
        rows.append({
            "subvertical_id": subvertical_id,
            "candidate_count": len(pool),
            "candidate_target": FUNNEL_TARGETS["structured_candidates"],
            "selected_for_mechanism_review_count": len(selected_ids),
            "selection_target": SELECTION_TARGET,
            "selected_case_ids": selected_ids,
            "marginal_counts": marginal_counts,
            "marginal_deficits": marginal_deficits,
            "marginal_deficit_total": deficit_total,
            "status": "ready_for_named_human_mechanism_review" if len(pool) >= 200 and len(selected_ids) == 40 and deficit_total == 0 else "selection_gap",
            "mechanism_audit_credit": 0,
        })
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "candidate_score_count": len(scores),
        "subvertical_count": len(subvertical_ids),
        "selection_marginal_targets": SELECTION_MARGINAL_TARGETS,
        "candidate_scores": sorted(scores, key=lambda row: row["case_id"]),
        "subvertical_selections": rows,
        "ready_subvertical_count": sum(row["status"] == "ready_for_named_human_mechanism_review" for row in rows),
        "policy": {
            "machine_score_can_promote_mechanism_audit": False,
            "named_human_source_review_required": True,
            "selection_preserves_all_six_marginal_dimensions": True,
            "missing_candidates_or_strata_fail_closed": True,
        },
        "truth_boundary": "Scores prioritize source inspection and stratified review. They do not prove mechanism, outcome, causality, or market effect and grant no audit credit.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_candidate_triage(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCandidateTriageError("candidate triage seal is invalid")
    scores = payload.get("candidate_scores")
    rows = payload.get("subvertical_selections")
    if not isinstance(scores, list) or payload.get("candidate_score_count") != len(scores):
        raise GTMCandidateTriageError("candidate score aggregate drifted")
    if not isinstance(rows, list) or payload.get("subvertical_count") != len(rows):
        raise GTMCandidateTriageError("subvertical selection aggregate drifted")
    score_ids = {row.get("case_id") for row in scores}
    if len(score_ids) != len(scores) or any(row.get("quota_credit") != 0 for row in scores):
        raise GTMCandidateTriageError("candidate scoring minted credit or duplicated IDs")
    for row in rows:
        selected = row.get("selected_case_ids")
        if not isinstance(selected, list) or len(selected) != len(set(selected)) or len(selected) > SELECTION_TARGET:
            raise GTMCandidateTriageError("invalid mechanism-review selection")
        if not set(selected).issubset(score_ids) or row.get("mechanism_audit_credit") != 0:
            raise GTMCandidateTriageError("selection references unknown candidates or minted audit credit")
        should_be_ready = row.get("candidate_count", 0) >= 200 and len(selected) == 40 and row.get("marginal_deficit_total") == 0
        if (row.get("status") == "ready_for_named_human_mechanism_review") != should_be_ready:
            raise GTMCandidateTriageError("selection readiness escaped the fail-closed rule")


__all__ = [
    "GTMCandidateTriageError",
    "SELECTION_MARGINAL_TARGETS",
    "compile_candidate_triage",
    "score_candidate",
    "verify_candidate_triage",
]
