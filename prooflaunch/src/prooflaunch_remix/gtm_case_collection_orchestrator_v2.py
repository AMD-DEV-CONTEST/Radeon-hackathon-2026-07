from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_evidence_funnel_v2 import QUOTA_DIMENSIONS, verify_case_evidence_funnel_standard


SCHEMA = "ProofLaunchGTMCaseCollectionOrchestratorV2"


class GTMCaseCollectionOrchestratorError(ValueError):
    pass


PRIORITY_SUBVERTICALS = (
    "b2b.industrial_climate.manufacturing",
    "b2b.industrial_climate.industrial_equipment",
    "b2b.industrial_climate.engineering_construction",
    "b2b.industrial_climate.commercial_real_estate",
    "b2b.professional_services.consulting",
    "b2c.consumer_ai_mobile_apps.creative_apps",
    "b2c.health_wellness.fitness",
    "b2c.beauty_fashion.beauty",
    "b2c.food_beverage.consumer_packaged_goods",
    "b2c.travel_hospitality.destinations",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _expanded(quota: Mapping[str, int]) -> list[str]:
    return [bucket for bucket, count in quota.items() for _ in range(int(count))]


def _adapter_routes(oss_landscape: Mapping[str, Any], platform: str) -> list[dict[str, Any]]:
    rows = []
    for candidate in oss_landscape.get("candidates", []):
        if platform not in candidate.get("platforms", []):
            continue
        decision = str(candidate.get("admission_decision", candidate.get("proposed_status", "")))
        access_mode = str(candidate.get("access_mode", ""))
        if any(token in decision for token in ("rejected", "blocked")):
            continue
        if access_mode in {"operator_credentials_required", "rejected"}:
            continue
        rows.append(
            {
                "repository": candidate.get("repository"),
                "revision": candidate.get("revision"),
                "license_spdx": candidate.get("license_spdx"),
                "admission_decision": decision,
                "access_mode": access_mode,
                "runtime_proven": bool(candidate.get("runtime_proven")),
                "integration_role": candidate.get("integration_role"),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["admission_decision"] == "production_admitted" else 1,
            0 if row["runtime_proven"] else 1,
            str(row["repository"]),
        )
    )
    return rows[:5]


def compile_case_collection_orchestrator(
    standard: Mapping[str, Any],
    coverage: Mapping[str, Any],
    oss_landscape: Mapping[str, Any],
) -> dict[str, Any]:
    verify_case_evidence_funnel_standard(standard)
    observed = {row["subvertical_id"]: row for row in coverage.get("subvertical_coverage", [])}
    if len(observed) != 81:
        raise GTMCaseCollectionOrchestratorError("coverage must include all 81 subverticals")

    dimension_arrays = {dimension: _expanded(quota) for dimension, quota in QUOTA_DIMENSIONS.items()}
    multipliers = dict(zip(QUOTA_DIMENSIONS, (1, 3, 7, 9, 11, 13), strict=True))
    slots: list[dict[str, Any]] = []
    workstreams: list[dict[str, Any]] = []
    for subvertical_index, subvertical in enumerate(standard["subverticals"]):
        subvertical_id = subvertical["subvertical_id"]
        wave = 1 if subvertical_id in PRIORITY_SUBVERTICALS else (2 if subvertical["business_model"] == "b2b" else 3)
        observed_count = observed[subvertical_id]["funnel_counts"]["structured_candidates"]
        for slot_index in range(200):
            requirements = {
                dimension: values[(slot_index * multipliers[dimension] + subvertical_index * 17) % 200]
                for dimension, values in dimension_arrays.items()
            }
            slots.append(
                {
                    "slot_id": f"{subvertical_id}:slot-{slot_index + 1:03d}",
                    "subvertical_id": subvertical_id,
                    "wave": wave,
                    **requirements,
                    "assignment_status": "unfilled",
                    "assigned_case_id": None,
                    "quota_credit": 0,
                }
            )
        workstreams.append(
            {
                **subvertical,
                "wave": wave,
                "target_candidates": 200,
                "observed_v2_candidates": observed_count,
                "candidate_gap": max(0, 200 - observed_count),
                "target_mechanism_audits": 40,
                "target_outcome_audits": 10,
                "target_execution_blueprints": 5,
                "status": "in_progress" if observed_count else "queued",
            }
        )

    platforms = [row["platform"] for row in standard.get("platform_contracts", [])]
    access_by_platform = {row["platform"]: row["access"] for row in standard.get("platform_contracts", [])}
    quota_markets = list(QUOTA_DIMENSIONS["quota_market"])
    jobs: list[dict[str, Any]] = []
    for workstream in workstreams:
        for market in quota_markets:
            for platform in platforms:
                adapters = _adapter_routes(oss_landscape, platform)
                jobs.append(
                    {
                        "job_id": f"{workstream['subvertical_id']}:{market}:{platform}",
                        "wave": workstream["wave"],
                        "subvertical_id": workstream["subvertical_id"],
                        "business_model": workstream["business_model"],
                        "quota_market": market,
                        "platform": platform,
                        "access_contract": access_by_platform[platform],
                        "adapter_routes": adapters,
                        "job_status": "ready" if adapters else "adapter_gap",
                        "discovery_target": 3,
                        "query_intents": [
                            f"{workstream['subvertical']} {market} recent organic breakout case",
                            f"{workstream['subvertical']} {market} durable repeat growth case",
                            f"{workstream['subvertical']} {market} failed or stalled go-to-market case",
                            f"{workstream['subvertical']} {market} mature category control",
                            f"{workstream['subvertical']} {market} turnaround go-to-market case",
                        ],
                        "required_receipt_fields": [
                            "source_url", "captured_at", "content_sha256", "access_method", "source_class"
                        ],
                        "external_action": "public_read_only_discovery",
                        "automatic_case_promotion_allowed": False,
                    }
                )

    slot_counts = Counter(slot["wave"] for slot in slots)
    job_counts = Counter(job["wave"] for job in jobs)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "coverage_sha256": coverage.get("content_sha256"),
        "oss_landscape_sha256": oss_landscape.get("content_sha256"),
        "priority_subvertical_ids": list(PRIORITY_SUBVERTICALS),
        "workstream_count": len(workstreams),
        "case_slot_count": len(slots),
        "collection_job_count": len(jobs),
        "wave_slot_counts": {str(key): value for key, value in sorted(slot_counts.items())},
        "wave_job_counts": {str(key): value for key, value in sorted(job_counts.items())},
        "workstreams": workstreams,
        "case_slots": slots,
        "collection_jobs": jobs,
        "execution_contract": {
            "discovery_overfetch_per_subvertical": 288,
            "target_valid_candidates_per_subvertical": 200,
            "source_copy_voice_or_asset_reuse_allowed": False,
            "access_control_bypass_allowed": False,
            "automatic_publish_spend_or_memory_write_allowed": False,
            "failed_and_stalled_examples_required": True,
            "adapter_enters_production_only_after_shadow_probe": True,
        },
        "truth_boundary": (
            "Slots and jobs prove executable coverage planning, not collected evidence. Only V2-valid cases assigned after "
            "source capture, deduplication, classification, and review receive quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_collection_orchestrator(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseCollectionOrchestratorError("collection orchestrator seal is invalid")
    if payload.get("workstream_count") != 81 or payload.get("case_slot_count") != 16_200:
        raise GTMCaseCollectionOrchestratorError("workstream or case-slot coverage drifted")
    if payload.get("collection_job_count") != 81 * 8 * 12:
        raise GTMCaseCollectionOrchestratorError("collection job coverage drifted")
    slots = payload.get("case_slots", [])
    if any(slot.get("quota_credit") != 0 or slot.get("assignment_status") != "unfilled" for slot in slots):
        raise GTMCaseCollectionOrchestratorError("an unfilled collection slot received quota credit")
    for subvertical_id in {slot["subvertical_id"] for slot in slots}:
        subset = [slot for slot in slots if slot["subvertical_id"] == subvertical_id]
        if len(subset) != 200:
            raise GTMCaseCollectionOrchestratorError(f"{subvertical_id} does not have 200 slots")
        for dimension, quota in QUOTA_DIMENSIONS.items():
            if Counter(slot[dimension] for slot in subset) != Counter(quota):
                raise GTMCaseCollectionOrchestratorError(f"{subvertical_id} slot quota drifted for {dimension}")
    if any(job.get("automatic_case_promotion_allowed") is not False for job in payload.get("collection_jobs", [])):
        raise GTMCaseCollectionOrchestratorError("collection job can auto-promote evidence")


__all__ = [
    "GTMCaseCollectionOrchestratorError",
    "PRIORITY_SUBVERTICALS",
    "compile_case_collection_orchestrator",
    "verify_case_collection_orchestrator",
]
