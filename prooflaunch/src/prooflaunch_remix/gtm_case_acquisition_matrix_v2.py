from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_evidence_funnel_v2 import (
    QUOTA_DIMENSIONS,
    verify_case_evidence_funnel_standard,
)
from .gtm_gold_case_discovery_v2 import verify_gold_case_discovery


SCHEMA = "ProofLaunchGTMCaseAcquisitionMatrixV2"
SLOT_STATUS = "coverage_gap_unfilled"
QUERY_TASKS_PER_SLOT = 3
QUERY_ROLES = (
    "primary_episode_discovery",
    "independent_outcome_or_failure_check",
    "first_party_timeline_and_cost_check",
)


class GTMCaseAcquisitionMatrixError(ValueError):
    """The acquisition matrix drifted from the 81 × 200 truth contract."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_bucket_sequence(
    subvertical_id: str,
    dimension: str,
    quotas: Mapping[str, int],
) -> list[str]:
    tagged: list[tuple[str, str]] = []
    for bucket, count in quotas.items():
        for occurrence in range(count):
            key = _digest(f"{subvertical_id}|{dimension}|{bucket}|{occurrence}")
            tagged.append((key, bucket))
    tagged.sort(key=lambda row: row[0])
    return [bucket for _, bucket in tagged]


def _platform_quotas(subvertical_id: str, platform_names: list[str]) -> dict[str, int]:
    base, remainder = divmod(200, len(platform_names))
    ranked = sorted(platform_names, key=lambda value: _digest(f"{subvertical_id}|platform|{value}"))
    extras = set(ranked[:remainder])
    return {platform: base + int(platform in extras) for platform in platform_names}


def _provisional_route_counts(discovery: Mapping[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in discovery.get("records", []):
        for subvertical_id in row.get("provisional_subvertical_ids", []):
            counts[str(subvertical_id)] += 1
    return counts


def build_case_acquisition_matrix(
    standard: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    verify_case_evidence_funnel_standard(standard)
    verify_gold_case_discovery(discovery)

    platform_names = [str(row["platform"]) for row in standard["platform_contracts"]]
    provisional_counts = _provisional_route_counts(discovery)
    slots: list[dict[str, Any]] = []
    subvertical_rows: list[dict[str, Any]] = []

    for registry_row in standard["subverticals"]:
        subvertical_id = str(registry_row["subvertical_id"])
        sequences = {
            dimension: _stable_bucket_sequence(subvertical_id, dimension, quotas)
            for dimension, quotas in QUOTA_DIMENSIONS.items()
        }
        platform_quotas = _platform_quotas(subvertical_id, platform_names)
        sequences["platform_search_lane"] = _stable_bucket_sequence(
            subvertical_id,
            "platform_search_lane",
            platform_quotas,
        )

        for slot_index in range(200):
            target_profile = {
                dimension: sequences[dimension][slot_index]
                for dimension in QUOTA_DIMENSIONS
            }
            slot = {
                "slot_id": f"{subvertical_id}.slot-{slot_index + 1:03d}",
                "subvertical_id": subvertical_id,
                "business_model": registry_row["business_model"],
                "vertical": registry_row["vertical"],
                "subvertical": registry_row["subvertical"],
                "target_profile": target_profile,
                "platform_search_lane": sequences["platform_search_lane"][slot_index],
                "query_roles": list(QUERY_ROLES),
                "query_seed_terms": [
                    str(registry_row["subvertical"]).replace("_", " "),
                    target_profile["outcome_type"].replace("_", " "),
                    target_profile["company_scale"].replace("_", " "),
                    target_profile["quota_market"].replace("_", " "),
                    target_profile["budget_tier"].replace("_", " "),
                    target_profile["recency_bucket"].replace("_", " "),
                ],
                "status": SLOT_STATUS,
                "case_id": None,
                "candidate_quota_credit": 0,
                "human_identity_and_evidence_review_required": True,
            }
            slots.append(slot)

        joint_profiles = {
            tuple(sequences[dimension][index] for dimension in QUOTA_DIMENSIONS)
            for index in range(200)
        }
        subvertical_rows.append(
            {
                "subvertical_id": subvertical_id,
                "slot_count": 200,
                "query_task_count": 200 * QUERY_TASKS_PER_SLOT,
                "formal_candidate_count": 0,
                "formal_candidate_gap": 200,
                "provisional_discovery_route_count": provisional_counts[subvertical_id],
                "provisional_routes_grant_quota_credit": False,
                "joint_target_profile_count": len(joint_profiles),
                "target_marginal_quotas": {
                    dimension: dict(quotas) for dimension, quotas in QUOTA_DIMENSIONS.items()
                },
                "platform_search_lane_quotas": platform_quotas,
                "status": "coverage_gap",
            }
        )

    provisional_total = sum(row["provisional_discovery_route_count"] for row in subvertical_rows)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "discovery_sha256": discovery["content_sha256"],
        "subvertical_count": len(subvertical_rows),
        "slot_count": len(slots),
        "query_tasks_per_slot": QUERY_TASKS_PER_SLOT,
        "query_task_count": len(slots) * QUERY_TASKS_PER_SLOT,
        "query_roles": list(QUERY_ROLES),
        "formal_candidate_count": 0,
        "formal_candidate_gap": len(slots),
        "provisional_discovery_lead_count": discovery["provisionally_routed_lead_count"],
        "provisional_discovery_route_count": provisional_total,
        "provisional_routes_grant_quota_credit": False,
        "subverticals": subvertical_rows,
        "slots": slots,
        "execution_contract": {
            "a_slot_is_filled_only_by_a_verified_CaseCandidateV2": True,
            "same_episode_cross_platform_mirrors_fill_at_most_one_slot": True,
            "all_six_marginal_buckets_must_match_the_bound_candidate": True,
            "zero_paid_requires_known_zero_paid_media_evidence": True,
            "independent_outcome_or_failure_check_is_search_not_proof_until_human_review": True,
            "authentication_captcha_paywall_or_access_restriction_bypass_allowed": False,
            "weak_duplicate_or_unknown_budget_backfill_allowed": False,
        },
        "truth_boundary": (
            "The 16,200 rows are acquisition slots, not cases. They grant zero candidate credit until a human-reviewed, "
            "sealed CaseCandidateV2 is bound and passes identity, cost, source, deduplication, and quota checks."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_acquisition_matrix(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseAcquisitionMatrixError("acquisition matrix seal is invalid")
    if payload.get("subvertical_count") != 81 or payload.get("slot_count") != 16_200:
        raise GTMCaseAcquisitionMatrixError("matrix must contain exactly 81 × 200 acquisition slots")
    if payload.get("query_tasks_per_slot") != 3 or payload.get("query_task_count") != 48_600:
        raise GTMCaseAcquisitionMatrixError("three bounded query roles are required per acquisition slot")
    if payload.get("formal_candidate_count") != 0 or payload.get("formal_candidate_gap") != 16_200:
        raise GTMCaseAcquisitionMatrixError("unfilled acquisition slots were misreported as formal cases")
    provisional_leads = payload.get("provisional_discovery_lead_count")
    provisional_routes = payload.get("provisional_discovery_route_count")
    if (
        not isinstance(provisional_leads, int)
        or not isinstance(provisional_routes, int)
        or provisional_leads < 0
        or provisional_routes < provisional_leads
    ):
        raise GTMCaseAcquisitionMatrixError("provisional discovery lead or route aggregate is invalid")
    if payload.get("provisional_routes_grant_quota_credit") is not False:
        raise GTMCaseAcquisitionMatrixError("provisional routes cannot grant quota credit")

    slots = payload.get("slots")
    rows = payload.get("subverticals")
    if not isinstance(slots, list) or not isinstance(rows, list) or len(rows) != 81:
        raise GTMCaseAcquisitionMatrixError("matrix rows are incomplete")
    slot_ids = [row.get("slot_id") for row in slots if isinstance(row, Mapping)]
    if len(slot_ids) != 16_200 or len(set(slot_ids)) != 16_200:
        raise GTMCaseAcquisitionMatrixError("acquisition slot IDs are missing or duplicated")

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for slot in slots:
        if not isinstance(slot, Mapping):
            raise GTMCaseAcquisitionMatrixError("an acquisition slot is malformed")
        grouped[str(slot.get("subvertical_id"))].append(slot)
        if (
            slot.get("status") != SLOT_STATUS
            or slot.get("case_id") is not None
            or slot.get("candidate_quota_credit") != 0
            or slot.get("human_identity_and_evidence_review_required") is not True
            or slot.get("query_roles") != list(QUERY_ROLES)
        ):
            raise GTMCaseAcquisitionMatrixError("an unfilled slot escaped the zero-credit human-review boundary")

    platform_names: set[str] = set()
    for row in rows:
        subvertical_id = str(row.get("subvertical_id"))
        members = grouped.get(subvertical_id, [])
        if len(members) != 200 or row.get("slot_count") != 200:
            raise GTMCaseAcquisitionMatrixError(f"{subvertical_id} does not have 200 slots")
        if row.get("formal_candidate_count") != 0 or row.get("formal_candidate_gap") != 200:
            raise GTMCaseAcquisitionMatrixError(f"{subvertical_id} misreports formal candidate coverage")
        for dimension, quotas in QUOTA_DIMENSIONS.items():
            actual = Counter(str(slot["target_profile"].get(dimension)) for slot in members)
            if dict(actual) != dict(quotas):
                raise GTMCaseAcquisitionMatrixError(f"{subvertical_id}.{dimension} marginal quota drifted")
        lane_quotas = row.get("platform_search_lane_quotas")
        actual_lanes = Counter(str(slot.get("platform_search_lane")) for slot in members)
        if actual_lanes != Counter(lane_quotas):
            raise GTMCaseAcquisitionMatrixError(f"{subvertical_id} platform search lanes drifted")
        if sum(actual_lanes.values()) != 200 or set(actual_lanes.values()) - {16, 17}:
            raise GTMCaseAcquisitionMatrixError(f"{subvertical_id} platform search lanes are not balanced")
        platform_names.update(actual_lanes)
    if len(platform_names) != 12:
        raise GTMCaseAcquisitionMatrixError("all 12 public-source platform lanes are required")

    contract = payload.get("execution_contract", {})
    if (
        contract.get("authentication_captcha_paywall_or_access_restriction_bypass_allowed") is not False
        or contract.get("weak_duplicate_or_unknown_budget_backfill_allowed") is not False
    ):
        raise GTMCaseAcquisitionMatrixError("the acquisition access or evidence boundary was weakened")


__all__ = [
    "GTMCaseAcquisitionMatrixError",
    "build_case_acquisition_matrix",
    "verify_case_acquisition_matrix",
]
