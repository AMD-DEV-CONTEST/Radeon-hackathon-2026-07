from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_sft_corpus import stable_sha256


REVIEWER_COUNT = 5
BRIEF_CASE_COUNT = 300
CAMPAIGN_CASE_COUNT = 150
CASE_COUNT = BRIEF_CASE_COUNT + CAMPAIGN_CASE_COUNT
EXPECTED_REVIEW_COUNT = REVIEWER_COUNT * CASE_COUNT
PROMOTION_MEAN = 4.7

RUBRIC_DIMENSIONS = (
    "evidence_grounding",
    "strategic_clarity",
    "creative_distinctiveness",
    "channel_fitness",
    "multimodal_coherence",
    "execution_readiness",
    "brand_and_claim_safety",
    "originality_without_imitation",
)

ATTESTATION = (
    "I reviewed this case independently as a human, used the supplied rubric, "
    "did not coordinate scores, and did not substitute model-generated ratings."
)


def blind_case(candidate: Mapping[str, Any], candidate_type: str) -> dict[str, Any]:
    if candidate_type not in {"brief", "campaign"}:
        raise V10ContractError("unknown gold review candidate type")
    content_sha = str(candidate["content_sha256"])
    case_id = f"blind-{candidate_type}-{stable_sha256({'type': candidate_type, 'sha': content_sha})[:20]}"
    if candidate_type == "brief":
        payload = {
            "objective": candidate["objective"],
            "audience": candidate["audience"],
            "job_to_be_done": candidate["job_to_be_done"],
            "market_tension": candidate["market_tension"],
            "single_minded_proposition": candidate["single_minded_proposition"],
            "reason_to_believe_claim": candidate["reason_to_believe"]["claim"],
            "evidence_token_count": len(candidate["source_identity_sha256s"]),
            "big_idea": candidate["big_idea"],
            "channel": candidate["channel"],
            "deliverables": candidate["deliverables"],
            "claim_inventory": [
                {"claim": row["claim"], "status": row["status"]}
                for row in candidate["claim_inventory"]
            ],
            "creative_mandatories": candidate["creative_mandatories"],
            "success_measurement_design": candidate["success_measurement_design"],
            "stop_conditions": candidate["stop_conditions"],
        }
    else:
        payload = {
            "strategy": candidate["strategy"],
            "channel_plan": [
                {"channel": row["channel"], "status": row["status"]}
                for row in candidate["channel_plan"]
            ],
            "multimodal_production_spec": candidate["multimodal_production_spec"],
            "agent_execution_plan": candidate["agent_execution_plan"],
            "acceptance_gates": candidate["acceptance_gates"],
            "evidence_token_count": len(candidate["source_ids"]),
        }
    case: dict[str, Any] = {
        "schema": "ProofLaunchBlindGoldReviewCaseV1",
        "case_id": case_id,
        "candidate_type": candidate_type,
        "candidate_content_sha256": content_sha,
        "blind_payload": payload,
        "source_provider_names_exposed": False,
        "source_urls_exposed": False,
        "candidate_order_exposed": False,
    }
    case["case_sha256"] = stable_sha256(case)
    return case


def review_template(case: Mapping[str, Any], reviewer_slot: int) -> dict[str, Any]:
    if reviewer_slot not in range(1, REVIEWER_COUNT + 1):
        raise V10ContractError("reviewer slot must be in [1, 5]")
    return {
        "schema": "ProofLaunchHumanGoldReviewV1",
        "reviewer_slot": reviewer_slot,
        "reviewer_pseudonym": None,
        "reviewer_attestation": None,
        "reviewed_at": None,
        "case_id": case["case_id"],
        "case_sha256": case["case_sha256"],
        "scores": {dimension: None for dimension in RUBRIC_DIMENSIONS},
        "strengths": None,
        "required_rework": None,
        "publishable": None,
        "review_content_sha256": None,
    }


def review_digest(review: Mapping[str, Any]) -> str:
    material = dict(review)
    material["review_content_sha256"] = None
    return stable_sha256(material)


def validate_completed_review(
    review: Mapping[str, Any], case_by_id: Mapping[str, Mapping[str, Any]]
) -> tuple[str, ...]:
    failures: list[str] = []
    case = case_by_id.get(str(review.get("case_id", "")))
    if case is None or review.get("case_sha256") != case.get("case_sha256"):
        failures.append("case_binding")
    if review.get("reviewer_slot") not in range(1, REVIEWER_COUNT + 1):
        failures.append("reviewer_slot")
    if not str(review.get("reviewer_pseudonym") or "").strip():
        failures.append("reviewer_pseudonym")
    if review.get("reviewer_attestation") != ATTESTATION:
        failures.append("human_attestation")
    if not str(review.get("reviewed_at") or "").strip():
        failures.append("reviewed_at")
    scores = review.get("scores")
    if not isinstance(scores, Mapping) or set(scores) != set(RUBRIC_DIMENSIONS):
        failures.append("score_dimensions")
    else:
        for dimension, score in scores.items():
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 1 <= float(score) <= 5:
                failures.append(f"score_range:{dimension}")
        numeric = [float(value) for value in scores.values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if numeric and min(numeric) < 5 and not str(review.get("required_rework") or "").strip():
            failures.append("low_score_requires_rework")
    if not str(review.get("strengths") or "").strip():
        failures.append("strengths")
    if not isinstance(review.get("publishable"), bool):
        failures.append("publishable")
    if review.get("review_content_sha256") != review_digest(review):
        failures.append("review_hash")
    return tuple(failures)


def aggregate_completed_reviews(
    cases: Sequence[Mapping[str, Any]], reviews: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    case_by_id = {str(case["case_id"]): case for case in cases}
    rows = list(reviews)
    failures: list[str] = []
    identities: set[tuple[int, str]] = set()
    reviewer_names: dict[int, set[str]] = defaultdict(set)
    case_slots: dict[str, set[int]] = defaultdict(set)
    dimension_values: dict[str, list[float]] = defaultdict(list)
    publishable_count = 0
    for index, row in enumerate(rows):
        row_failures = validate_completed_review(row, case_by_id)
        failures.extend(f"review-{index + 1}:{failure}" for failure in row_failures)
        slot = int(row.get("reviewer_slot", 0)) if isinstance(row.get("reviewer_slot"), int) else 0
        case_id = str(row.get("case_id", ""))
        identity = (slot, case_id)
        if identity in identities:
            failures.append(f"duplicate_review:{slot}:{case_id}")
        identities.add(identity)
        reviewer_names[slot].add(str(row.get("reviewer_pseudonym", "")))
        case_slots[case_id].add(slot)
        scores = row.get("scores", {})
        if isinstance(scores, Mapping):
            for dimension in RUBRIC_DIMENSIONS:
                value = scores.get(dimension)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    dimension_values[dimension].append(float(value))
        publishable_count += row.get("publishable") is True

    completed_case_count = sum(
        slots == set(range(1, REVIEWER_COUNT + 1)) for slots in case_slots.values()
    )
    reviewer_identity_count = len(
        {next(iter(names)) for slot, names in reviewer_names.items() if slot and len(names) == 1}
    )
    if any(len(names) != 1 for slot, names in reviewer_names.items() if slot):
        failures.append("reviewer_slot_identity_drift")
    all_scores = [value for values in dimension_values.values() for value in values]
    mean_score = sum(all_scores) / len(all_scores) if all_scores else None
    dimension_means = {
        dimension: (sum(values) / len(values) if values else None)
        for dimension, values in sorted(dimension_values.items())
    }
    publishable_rate = publishable_count / len(rows) if rows else None
    complete = (
        len(rows) == EXPECTED_REVIEW_COUNT
        and len(identities) == EXPECTED_REVIEW_COUNT
        and completed_case_count == CASE_COUNT
        and reviewer_identity_count == REVIEWER_COUNT
        and not failures
    )
    promoted = bool(
        complete
        and mean_score is not None
        and mean_score >= PROMOTION_MEAN
        and publishable_rate is not None
        and publishable_rate >= 0.95
        and all(value is not None and value >= 4.5 for value in dimension_means.values())
    )
    return {
        "submitted_review_count": len(rows),
        "expected_review_count": EXPECTED_REVIEW_COUNT,
        "completed_case_count": completed_case_count,
        "expected_case_count": CASE_COUNT,
        "reviewer_identity_count": reviewer_identity_count,
        "expected_reviewer_count": REVIEWER_COUNT,
        "mean_score": round(mean_score, 6) if mean_score is not None else None,
        "dimension_means": {
            key: round(value, 6) if value is not None else None
            for key, value in dimension_means.items()
        },
        "publishable_rate": round(publishable_rate, 6) if publishable_rate is not None else None,
        "review_set_complete": complete,
        "promotion_threshold": PROMOTION_MEAN,
        "promotion_passed": promoted,
        "failure_count": len(failures),
        "failures": failures[:200],
    }
