from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_corpus_curator import krippendorff_alpha_ordinal
from .v10_sft_corpus import stable_sha256


REVIEWER_COUNT = 3
AUDIT_CASE_COUNT = 1_500
EXPECTED_REVIEW_COUNT = REVIEWER_COUNT * AUDIT_CASE_COUNT
ALPHA_MINIMUM = 0.85
POSITIVE_MEAN_MINIMUM = 4.7

AUDIT_STRATA = {
    "cpt": 300,
    "sft": 350,
    "preference": 250,
    "region": 200,
    "trajectory": 150,
    "repair": 100,
    "source": 150,
}

RUBRIC_DIMENSIONS = (
    "overall_quality",
    "evidence_grounding",
    "rights_provenance",
    "gtm_usefulness",
    "novelty",
    "difficulty",
)

ATTESTATION = (
    "I reviewed this case independently as a human, used the supplied rubric, "
    "did not coordinate scores, and did not substitute model-generated ratings."
)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def redact_urls(value: Any) -> Any:
    """Remove source locators from the reviewer-facing payload only."""

    if isinstance(value, str):
        return _URL_RE.sub("[SOURCE_LOCATOR_REDACTED]", value)
    if isinstance(value, Mapping):
        return {str(key): redact_urls(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_urls(item) for item in value]
    return value


def _payload_for(stratum: str, row: Mapping[str, Any], asset_ref: str | None) -> dict[str, Any]:
    if stratum == "cpt":
        payload = {
            "content_class": row["content_class"],
            "text": row["text"],
            "token_count": row["token_count"],
            "license_spdx": row["license_spdx"],
            "rights_basis_present": bool(row.get("rights_basis")),
            "training_admitted": row.get("training_admitted") is True,
        }
    elif stratum == "sft":
        payload = {
            "stage": row["stage"],
            "input_kind": row["input_kind"],
            "system_prompt": row["system_prompt"],
            "user_prompt": row["user_prompt"],
            "completion": row["completion"],
            "rights_verified": row.get("rights_verified") is True,
        }
    elif stratum == "preference":
        payload = {
            "stage": row["stage"],
            "input_kind": row["input_kind"],
            "system_prompt": row["system_prompt"],
            "user_prompt": row["user_prompt"],
            "chosen": row["chosen"],
            "rejected": row["rejected"],
            "rejected_error_codes": row["rejected_error_codes"],
            "preference_reason": row["preference_reason"],
        }
    elif stratum == "region":
        if not asset_ref:
            raise V10ContractError("region review requires a blinded asset")
        payload = {
            "review_asset": asset_ref,
            "asset_sha256": row["asset_sha256"],
            "image_size": row["image_size"],
            "chosen_region": row["chosen_region"],
            "rejected_region": row["rejected_region"],
            "score_margin": row["score_margin"],
            "preference_basis": row["preference_basis"],
        }
    elif stratum == "trajectory":
        payload = {
            "lane": row.get("lane") or row.get("stage") or "source_bound",
            "issue_kind": row.get("issue_kind") or row.get("input_kind") or "source_bound_execution",
            "outcome_kind": row["outcome_kind"],
            "events": row["events"],
            "verification": row["verification"],
            "mechanically_verified": row.get("mechanically_verified", row.get("verification", {}).get("passed") is True),
        }
    elif stratum == "repair":
        payload = {
            "stage": row["stage"],
            "input_kind": row["input_kind"],
            "failure_family": row["failure_family"],
            "broken_contract": row["broken_contract"],
            "repair_actions": row["repair_actions"],
            "repaired_completion": row["repaired_completion"],
            "verification": row["verification"],
        }
    elif stratum == "source":
        payload = {
            "kind": row["kind"],
            "media_type": row["media_type"],
            "license_id": row["license_id"],
            "digest_algorithm": row["digest_algorithm"],
            "revision_pinned": bool(row.get("revision")),
            "upstream_digest_present": bool(row.get("upstream_digest")),
            "trademark_hold": row["trademark_hold"],
            "training_allowed": row["training_allowed"],
        }
    else:
        raise V10ContractError(f"unknown audit stratum: {stratum}")
    return redact_urls(payload)


def blind_case(
    *,
    audit_id: str,
    stratum: str,
    row: Mapping[str, Any],
    source_row_sha256: str,
    asset_ref: str | None = None,
) -> dict[str, Any]:
    if stratum not in AUDIT_STRATA:
        raise V10ContractError("unknown audit stratum")
    case: dict[str, Any] = {
        "schema": "ProofLaunchCuratedCorpusBlindAuditCaseV1",
        "case_id": audit_id,
        "stratum": stratum,
        "source_row_sha256": source_row_sha256,
        "blind_payload": _payload_for(stratum, row, asset_ref),
        "source_provider_names_exposed": False,
        "source_urls_exposed": False,
        "source_record_order_exposed": False,
    }
    serialized = str(case["blind_payload"])
    if "http://" in serialized.lower() or "https://" in serialized.lower():
        raise V10ContractError("review payload leaked a source URL")
    case["case_sha256"] = stable_sha256(case)
    return case


def review_template(case: Mapping[str, Any], reviewer_slot: int) -> dict[str, Any]:
    if reviewer_slot not in range(1, REVIEWER_COUNT + 1):
        raise V10ContractError("reviewer slot must be in [1, 3]")
    return {
        "schema": "ProofLaunchCuratedCorpusHumanAuditReviewV1",
        "reviewer_slot": reviewer_slot,
        "reviewer_pseudonym": None,
        "reviewer_attestation": None,
        "reviewed_at": None,
        "case_id": case["case_id"],
        "case_sha256": case["case_sha256"],
        "scores": {dimension: None for dimension in RUBRIC_DIMENSIONS},
        "strengths": None,
        "required_rework": None,
        "recommended_route": None,
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
    slot = review.get("reviewer_slot")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot not in range(1, REVIEWER_COUNT + 1):
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
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                failures.append(f"integer_score_range:{dimension}")
        numeric = [score for score in scores.values() if isinstance(score, int) and not isinstance(score, bool)]
        if numeric and min(numeric) < 5 and not str(review.get("required_rework") or "").strip():
            failures.append("low_score_requires_rework")
    if not str(review.get("strengths") or "").strip():
        failures.append("strengths")
    if review.get("recommended_route") not in {"positive", "remove", "repair", "replay"}:
        failures.append("recommended_route")
    if review.get("review_content_sha256") != review_digest(review):
        failures.append("review_hash")
    return tuple(failures)


def _route(mean_quality: float, mean_difficulty: float) -> str:
    if mean_quality < 3.0:
        return "remove"
    if mean_difficulty >= 4.0:
        return "replay"
    if mean_quality >= POSITIVE_MEAN_MINIMUM:
        return "positive"
    return "repair"


def aggregate_completed_reviews(
    cases: Sequence[Mapping[str, Any]], reviews: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    case_by_id = {str(case["case_id"]): case for case in cases}
    rows = list(reviews)
    failures: list[str] = []
    identities: set[tuple[int, str]] = set()
    case_slots: dict[str, set[int]] = defaultdict(set)
    reviewer_names: dict[int, set[str]] = defaultdict(set)
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        failures.extend(
            f"review-{index + 1}:{failure}"
            for failure in validate_completed_review(row, case_by_id)
        )
        slot = row.get("reviewer_slot") if isinstance(row.get("reviewer_slot"), int) else 0
        case_id = str(row.get("case_id", ""))
        identity = (int(slot), case_id)
        if identity in identities:
            failures.append(f"duplicate_review:{slot}:{case_id}")
        identities.add(identity)
        case_slots[case_id].add(int(slot))
        reviewer_names[int(slot)].add(str(row.get("reviewer_pseudonym", "")))
        by_case[case_id].append(row)

    expected_slots = set(range(1, REVIEWER_COUNT + 1))
    completed_case_count = sum(case_slots.get(case_id) == expected_slots for case_id in case_by_id)
    stable_names = {
        next(iter(names)) for slot, names in reviewer_names.items() if slot in expected_slots and len(names) == 1
    }
    if rows and any(len(reviewer_names.get(slot, set())) != 1 for slot in expected_slots):
        failures.append("reviewer_slot_identity_drift")
    if rows and len(stable_names) != REVIEWER_COUNT:
        failures.append("reviewers_not_distinct")
    complete = (
        len(cases) == AUDIT_CASE_COUNT
        and len(case_by_id) == AUDIT_CASE_COUNT
        and len(rows) == EXPECTED_REVIEW_COUNT
        and len(identities) == EXPECTED_REVIEW_COUNT
        and completed_case_count == AUDIT_CASE_COUNT
        and not failures
    )

    alpha: float | None = None
    routes: list[dict[str, Any]] = []
    if complete:
        ratings = [
            [int(review["scores"]["overall_quality"]) for review in sorted(by_case[case_id], key=lambda item: item["reviewer_slot"])]
            for case_id in sorted(case_by_id)
        ]
        alpha = krippendorff_alpha_ordinal(ratings)
        for case_id in sorted(case_by_id):
            case_reviews = by_case[case_id]
            mean_quality = sum(float(row["scores"]["overall_quality"]) for row in case_reviews) / REVIEWER_COUNT
            mean_difficulty = sum(float(row["scores"]["difficulty"]) for row in case_reviews) / REVIEWER_COUNT
            routes.append(
                {
                    "case_id": case_id,
                    "case_sha256": case_by_id[case_id]["case_sha256"],
                    "stratum": case_by_id[case_id]["stratum"],
                    "mean_quality": round(mean_quality, 6),
                    "mean_difficulty": round(mean_difficulty, 6),
                    "route": _route(mean_quality, mean_difficulty),
                }
            )
    route_counts = Counter(row["route"] for row in routes)
    positive_values = [row["mean_quality"] for row in routes if row["route"] == "positive"]
    positive_mean = sum(positive_values) / len(positive_values) if positive_values else None
    alpha_passed = bool(complete and alpha is not None and alpha >= ALPHA_MINIMUM)
    positive_mean_passed = bool(
        complete and positive_mean is not None and positive_mean >= POSITIVE_MEAN_MINIMUM
    )
    freeze_passed = bool(complete and alpha_passed and positive_mean_passed)
    return {
        "submitted_review_count": len(rows),
        "expected_review_count": EXPECTED_REVIEW_COUNT,
        "completed_case_count": completed_case_count,
        "expected_case_count": AUDIT_CASE_COUNT,
        "reviewer_identity_count": len(stable_names),
        "expected_reviewer_count": REVIEWER_COUNT,
        "review_set_complete": complete,
        "krippendorff_alpha_ordinal": round(alpha, 6) if alpha is not None else None,
        "alpha_minimum": ALPHA_MINIMUM,
        "alpha_passed": alpha_passed,
        "positive_case_count": len(positive_values),
        "positive_mean_quality": round(positive_mean, 6) if positive_mean is not None else None,
        "positive_mean_minimum": POSITIVE_MEAN_MINIMUM,
        "positive_mean_passed": positive_mean_passed,
        "route_counts": {key: route_counts.get(key, 0) for key in ("positive", "remove", "repair", "replay")},
        "routes": routes,
        "freeze_passed": freeze_passed,
        "failure_count": len(failures),
        "failures": failures[:200],
    }
